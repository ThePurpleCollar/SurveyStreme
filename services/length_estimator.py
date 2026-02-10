"""설문 소요 시간 추정 서비스.

추출된 SurveyDocument의 문항들을 LLM으로 분석하여
문항별 응답 소요 시간을 추정하고 집계 결과를 제공한다.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict

from models.survey import SurveyQuestion
from services.llm_client import call_llm_json, MODEL_LENGTH_ESTIMATOR

logger = logging.getLogger(__name__)

# ── 데이터 클래스 ──────────────────────────────────────────────────


COGNITIVE_TASKS = ["lookup", "factual", "recall", "evaluation", "comparison", "generative", "sensitive"]

COGNITIVE_TASK_LABELS = {
    "ko": {
        "lookup": "조회/식별",
        "factual": "사실 확인",
        "recall": "기억 회상",
        "evaluation": "평가/태도",
        "comparison": "비교/순위",
        "generative": "생성/서술",
        "sensitive": "민감/개인",
    },
    "en": {
        "lookup": "Lookup",
        "factual": "Factual",
        "recall": "Recall",
        "evaluation": "Evaluation",
        "comparison": "Comparison",
        "generative": "Generative",
        "sensitive": "Sensitive",
    },
}


@dataclass
class QuestionTimeEstimate:
    question_number: str
    question_text: str
    question_type: str       # SurveyQuestion.question_type
    option_count: int        # len(answer_options)
    estimated_seconds: int   # LLM 추정 시간 (1~300초 클램핑)
    complexity: str          # "low" | "medium" | "high"
    cognitive_task: str      # "lookup" | "factual" | "recall" | "evaluation" | "comparison" | "generative" | "sensitive"
    reasoning: str           # LLM의 추정 근거


@dataclass
class SurveyLengthResult:
    question_estimates: List[QuestionTimeEstimate] = field(default_factory=list)

    @property
    def total_seconds(self) -> int:
        return sum(e.estimated_seconds for e in self.question_estimates)

    @property
    def total_questions(self) -> int:
        return len(self.question_estimates)

    @property
    def avg_seconds_per_question(self) -> float:
        if not self.question_estimates:
            return 0.0
        return self.total_seconds / self.total_questions

    def time_by_type(self) -> Dict[str, int]:
        """유형별 총 소요 시간 (초)."""
        result: Dict[str, int] = {}
        for e in self.question_estimates:
            qtype = e.question_type or "Unknown"
            result[qtype] = result.get(qtype, 0) + e.estimated_seconds
        return result

    def count_by_type(self) -> Dict[str, int]:
        """유형별 문항 수."""
        result: Dict[str, int] = {}
        for e in self.question_estimates:
            qtype = e.question_type or "Unknown"
            result[qtype] = result.get(qtype, 0) + 1
        return result

    def count_by_complexity(self) -> Dict[str, int]:
        """복잡도별 문항 수."""
        result: Dict[str, int] = {"low": 0, "medium": 0, "high": 0}
        for e in self.question_estimates:
            key = e.complexity if e.complexity in result else "medium"
            result[key] += 1
        return result

    def time_by_cognitive_task(self) -> Dict[str, int]:
        """인지 태스크별 총 소요 시간 (초)."""
        result: Dict[str, int] = {}
        for e in self.question_estimates:
            task = e.cognitive_task or "factual"
            result[task] = result.get(task, 0) + e.estimated_seconds
        return result

    def count_by_cognitive_task(self) -> Dict[str, int]:
        """인지 태스크별 문항 수."""
        result: Dict[str, int] = {}
        for e in self.question_estimates:
            task = e.cognitive_task or "factual"
            result[task] = result.get(task, 0) + 1
        return result


# ── 시스템 프롬프트 ────────────────────────────────────────────────

_SYSTEM_PROMPT_KO = """당신은 설문조사 방법론 전문가입니다. 주어진 설문 문항들의 응답 소요 시간을 추정하세요.

## 1. 구조적 기준 시간 (문항 유형별 베이스라인)

| 문항 유형 | 기준 시간 |
|----------|----------|
| SA 2~5개 보기 | 5~10초 |
| SA 6~15개 보기 | 10~20초 |
| MA 5~10개 보기 | 15~25초 |
| MA 11~20개 보기 | 20~35초 |
| OE (주관식) | 30~60초 |
| NUMERIC | 5~15초 |
| Npt (단일 척도) | 5~10초 |
| Npt x M (매트릭스 척도) | 행당 5~8초 |
| TopN (순위) | 15~30초 |
| MATRIX (그리드) | 행당 5~8초 |

## 2. 인지적 부하 가중치 (핵심 — 반드시 반영)

보기 수나 유형만으로 소요 시간을 결정하지 마세요. **응답자가 수행해야 하는 인지 작업의 종류**에 따라 시간이 크게 달라집니다:

| 인지 태스크 유형 | 보정 방향 | 예시 |
|----------------|----------|------|
| **조회/식별 (Lookup)** | ×0.5~0.7 (빠름) | 나이, 성별, 거주 지역, 보유 브랜드/모델 — 보기가 많아도 자신의 답을 바로 찾음 |
| **사실 확인 (Factual)** | ×0.8~1.0 | 구매 여부, 사용 빈도(명확한 구간), 이용 경험 유무 |
| **기억 회상 (Recall)** | ×1.2~1.5 (느림) | 최근 구매 브랜드, 광고 인지, 과거 이용 경험 상세 — 기억을 더듬어야 함 |
| **평가/태도 (Evaluation)** | ×1.0~1.3 | 만족도, 호감도, 동의 수준, NPS — 자기 감정을 판단해야 함 |
| **비교/순위 (Comparison)** | ×1.5~2.0 (매우 느림) | Key Buying Factor 순위, 브랜드 선호 순위, Best-Worst — 보기 간 비교·트레이드오프 필요 |
| **생성/서술 (Generative)** | ×1.5~2.5 | 자유 서술, 아이디어 제안, 이유 설명 — 응답을 스스로 만들어야 함 |
| **민감/개인 (Sensitive)** | ×1.2~1.5 | 소득, 건강, 정치 성향 — 응답 전 망설임 발생 |

**적용 예시:**
- SA 100개 보기 × 나이(조회) = 기준시간 × 0.5 → 약 10~15초 (보기 수에 비해 빠름)
- SA 10개 보기 × KBF Top3 순위(비교) = 기준시간 × 1.8 → 약 35~55초 (보기 수에 비해 느림)
- MA 15개 보기 × 과거 이용 브랜드(회상) = 기준시간 × 1.3 → 약 30~45초

## 3. 복잡도 분류

- **low**: 조회/식별 또는 단순 사실 확인, 직관적 응답
- **medium**: 평가/태도, 적당한 회상, 보통 수준의 사고
- **high**: 비교/순위, 깊은 회상, 서술, 민감 주제, 복합적 인지 작업

## 4. 추가 고려사항

- 문항 텍스트의 길이와 복잡도 (긴 지시문 → 읽기 시간 추가)
- 응답 방식 (단일선택, 복수선택, 순위, 주관식 등)
- 필터 조건이나 안내문의 존재 여부
- 매트릭스/그리드 문항의 행 수
- 보기 텍스트 길이 (긴 보기 문구 → 읽기 시간 추가)

## 5. 출력 형식 (JSON)

{
  "results": [
    {
      "question_number": "Q1",
      "estimated_seconds": 10,
      "complexity": "low",
      "cognitive_task": "lookup",
      "reasoning": "나이를 묻는 문항, 100개 보기지만 자신의 나이를 바로 찾으므로 조회(lookup) 태스크, 빠른 응답 가능"
    }
  ]
}

cognitive_task 값: lookup, factual, recall, evaluation, comparison, generative, sensitive"""

_SYSTEM_PROMPT_EN = """You are a survey methodology expert. Estimate the response time for each given survey question.

## 1. Structural Baseline Times (by question type)

| Question Type | Baseline Time |
|--------------|---------------|
| SA with 2-5 options | 5-10 seconds |
| SA with 6-15 options | 10-20 seconds |
| MA with 5-10 options | 15-25 seconds |
| MA with 11-20 options | 20-35 seconds |
| OE (open-ended) | 30-60 seconds |
| NUMERIC | 5-15 seconds |
| Npt (single scale) | 5-10 seconds |
| Npt x M (matrix scale) | 5-8 seconds per row |
| TopN (ranking) | 15-30 seconds |
| MATRIX (grid) | 5-8 seconds per row |

## 2. Cognitive Load Multipliers (Critical — must apply)

Do NOT determine time from option count or question type alone. The **type of cognitive task** the respondent must perform dramatically affects response time:

| Cognitive Task | Multiplier | Examples |
|---------------|------------|----------|
| **Lookup/Identification** | ×0.5-0.7 (fast) | Age, gender, region, owned brand/model — respondent quickly finds their answer even with many options |
| **Factual** | ×0.8-1.0 | Purchase yes/no, usage frequency (clear intervals), experience yes/no |
| **Recall** | ×1.2-1.5 (slow) | Recent purchases, ad awareness, past experience details — requires memory retrieval |
| **Evaluation/Attitude** | ×1.0-1.3 | Satisfaction, favorability, agreement, NPS — requires self-assessment |
| **Comparison/Ranking** | ×1.5-2.0 (very slow) | Key Buying Factor ranking, brand preference ranking, Best-Worst — requires comparing and trading off between options |
| **Generative** | ×1.5-2.5 | Free-text responses, idea generation, reason explanation — respondent must create the answer |
| **Sensitive/Personal** | ×1.2-1.5 | Income, health, political views — hesitation before responding |

**Application examples:**
- SA 100 options × Age (lookup) = baseline × 0.5 → ~10-15s (fast despite many options)
- SA 10 options × KBF Top3 ranking (comparison) = baseline × 1.8 → ~35-55s (slow despite few options)
- MA 15 options × Past brands used (recall) = baseline × 1.3 → ~30-45s

## 3. Complexity Classification

- **low**: Lookup/identification or simple factual, intuitive response
- **medium**: Evaluation/attitude, moderate recall, some thought required
- **high**: Comparison/ranking, deep recall, generative, sensitive topics, compound cognitive tasks

## 4. Additional Considerations

- Question text length and complexity (long instructions → additional reading time)
- Response method (single-select, multi-select, ranking, open-ended, etc.)
- Presence of filter conditions or instructions
- Number of rows in matrix/grid questions
- Option text length (longer option labels → additional reading time)

## 5. Output Format (JSON)

{
  "results": [
    {
      "question_number": "Q1",
      "estimated_seconds": 10,
      "complexity": "low",
      "cognitive_task": "lookup",
      "reasoning": "Age question with 100 options, but respondent finds their age immediately (lookup task), fast response"
    }
  ]
}

cognitive_task values: lookup, factual, recall, evaluation, comparison, generative, sensitive"""


# ── 배칭 및 프롬프트 생성 ──────────────────────────────────────────

BATCH_SIZE = 25


def _format_question_for_prompt(q: SurveyQuestion) -> str:
    """문항 정보를 프롬프트용 텍스트로 변환."""
    parts = [f"[{q.question_number}]"]
    if q.question_type:
        parts.append(f"Type: {q.question_type}")
    parts.append(f"Text: {q.question_text}")
    if q.filter_condition:
        parts.append(f"Filter: {q.filter_condition}")
    if q.response_base:
        parts.append(f"Response Base: {q.response_base}")
    if q.instructions:
        parts.append(f"Instructions: {q.instructions}")
    if q.answer_options:
        opts = " | ".join(f"{o.code}. {o.label}" for o in q.answer_options)
        parts.append(f"Options ({len(q.answer_options)}): {opts}")
    return "\n".join(parts)


def _build_batch_prompt(batch: List[SurveyQuestion]) -> str:
    """배치 내 문항들을 하나의 프롬프트로 결합."""
    sections = []
    for q in batch:
        sections.append(_format_question_for_prompt(q))
    return (
        "Estimate the response time for each of the following survey questions:\n\n"
        + "\n\n---\n\n".join(sections)
    )


# ── 폴백 추정 ────────────────────────────────────────────────────

_TYPE_DEFAULTS: Dict[str, int] = {
    "SA": 10,
    "MA": 20,
    "OE": 45,
    "NUMERIC": 10,
    "Npt": 8,
    "Npt x M": 30,
    "TopN": 20,
    "MATRIX": 25,
}


def _fallback_estimate(q: SurveyQuestion) -> QuestionTimeEstimate:
    """LLM 실패 시 유형 기반 기본값으로 추정."""
    qtype = q.question_type or ""
    base_time = _TYPE_DEFAULTS.get(qtype, 15)
    option_count = len(q.answer_options)

    # 보기 10개 초과 시 1.3배 가중치
    if option_count > 10:
        base_time = int(base_time * 1.3)

    return QuestionTimeEstimate(
        question_number=q.question_number,
        question_text=q.question_text,
        question_type=qtype,
        option_count=option_count,
        estimated_seconds=max(1, min(300, base_time)),
        complexity="medium",
        cognitive_task="factual",
        reasoning="Fallback estimate based on question type defaults",
    )


# ── 결과 파싱 ────────────────────────────────────────────────────

def _parse_batch_result(
    raw: dict, batch: List[SurveyQuestion],
) -> List[QuestionTimeEstimate]:
    """LLM JSON 응답을 QuestionTimeEstimate 리스트로 변환."""
    results_raw = raw.get("results", [])
    qn_to_q = {q.question_number: q for q in batch}

    parsed = []
    seen_qn = set()

    for item in results_raw:
        qn = str(item.get("question_number", "")).strip()
        if not qn:
            continue
        seen_qn.add(qn)

        q = qn_to_q.get(qn)
        if q is None:
            continue

        estimated = item.get("estimated_seconds", 15)
        try:
            estimated = int(estimated)
        except (ValueError, TypeError):
            estimated = 15
        estimated = max(1, min(300, estimated))

        complexity = str(item.get("complexity", "medium")).lower()
        if complexity not in ("low", "medium", "high"):
            complexity = "medium"

        cognitive_task = str(item.get("cognitive_task", "factual")).lower()
        if cognitive_task not in COGNITIVE_TASKS:
            cognitive_task = "factual"

        reasoning = str(item.get("reasoning", ""))

        parsed.append(QuestionTimeEstimate(
            question_number=qn,
            question_text=q.question_text,
            question_type=q.question_type or "",
            option_count=len(q.answer_options),
            estimated_seconds=estimated,
            complexity=complexity,
            cognitive_task=cognitive_task,
            reasoning=reasoning,
        ))

    # LLM이 누락한 문항은 폴백 추정으로 추가
    for q in batch:
        if q.question_number not in seen_qn:
            parsed.append(_fallback_estimate(q))

    return parsed


# ── 메인 함수 ──────────────────────────────────────────────────────

def estimate_survey_length(
    questions: List[SurveyQuestion],
    model: str = MODEL_LENGTH_ESTIMATOR,
    language: str = "ko",
    progress_callback: Optional[Callable] = None,
) -> SurveyLengthResult:
    """설문 응답 소요 시간을 추정한다.

    Args:
        questions: 분석할 SurveyQuestion 리스트
        model: 사용할 Gemini 모델
        language: 분석 언어 ("ko" 또는 "en")
        progress_callback: (event, data) 형태의 콜백.
            Events: "batch_start", "batch_done"

    Returns:
        SurveyLengthResult (문항별 추정 + 집계)
    """
    if not questions:
        return SurveyLengthResult()

    def _notify(event: str, data: dict):
        if progress_callback:
            progress_callback(event, data)

    system_prompt = _SYSTEM_PROMPT_KO if language == "ko" else _SYSTEM_PROMPT_EN

    # 배치 분할
    batches: List[List[SurveyQuestion]] = []
    for i in range(0, len(questions), BATCH_SIZE):
        batches.append(questions[i:i + BATCH_SIZE])

    total_batches = len(batches)
    all_estimates: List[QuestionTimeEstimate] = []

    for batch_idx, batch in enumerate(batches):
        _notify("batch_start", {
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "question_count": len(batch),
        })
        user_prompt = _build_batch_prompt(batch)
        try:
            raw = call_llm_json(system_prompt, user_prompt, model)
            results = _parse_batch_result(raw, batch)
        except Exception as e:
            logger.error(f"Batch {batch_idx} failed: {e}")
            results = [_fallback_estimate(q) for q in batch]
        all_estimates.extend(results)
        _notify("batch_done", {
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "question_count": len(batch),
        })

    # 원본 문항 순서로 정렬
    qn_order = {q.question_number: i for i, q in enumerate(questions)}
    all_estimates.sort(key=lambda e: qn_order.get(e.question_number, 999999))

    return SurveyLengthResult(question_estimates=all_estimates)
