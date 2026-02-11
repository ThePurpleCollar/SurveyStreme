"""설문 문항 품질 자동 검사 서비스.

개별 문항을 LLM으로 분석하여 이중질문, 유도질문, 모호한 표현,
보기 문제 등을 탐지하고 개선 제안을 제공한다.
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from streamlit.runtime.scriptrunner import get_script_run_ctx, add_script_run_ctx

from models.survey import SurveyQuestion
from services.llm_client import call_llm_json, MODEL_QUALITY_CHECKER

logger = logging.getLogger(__name__)

# ── 데이터 클래스 ──────────────────────────────────────────────────

CATEGORIES = [
    "DOUBLE_BARRELED",
    "LEADING_BIASED",
    "AMBIGUOUS",
    "RESPONSE_OPTIONS",
    "COMPLEX",
    "INAPPROPRIATE",
]

SEVERITIES = ["CRITICAL", "WARNING", "INFO"]

CATEGORY_LABELS = {
    "ko": {
        "DOUBLE_BARRELED": "이중질문",
        "LEADING_BIASED": "유도/편향 질문",
        "AMBIGUOUS": "모호한 표현",
        "RESPONSE_OPTIONS": "보기 문제",
        "COMPLEX": "복잡성",
        "INAPPROPRIATE": "부적절한 표현",
    },
    "en": {
        "DOUBLE_BARRELED": "Double-Barreled",
        "LEADING_BIASED": "Leading/Biased",
        "AMBIGUOUS": "Ambiguous Wording",
        "RESPONSE_OPTIONS": "Response Options",
        "COMPLEX": "Complexity",
        "INAPPROPRIATE": "Inappropriate",
    },
}

SEVERITY_LABELS = {
    "ko": {"CRITICAL": "심각", "WARNING": "주의", "INFO": "참고"},
    "en": {"CRITICAL": "Critical", "WARNING": "Warning", "INFO": "Info"},
}


@dataclass
class QualityIssue:
    category: str      # DOUBLE_BARRELED, LEADING_BIASED, ...
    severity: str      # CRITICAL, WARNING, INFO
    description: str
    suggestion: str


@dataclass
class QuestionQualityResult:
    question_number: str
    question_text: str
    issues: List[QualityIssue] = field(default_factory=list)


# ── 시스템 프롬프트 ────────────────────────────────────────────────

_SYSTEM_PROMPT_KO = """당신은 설문조사 방법론 전문가입니다. 주어진 설문 문항들의 품질을 분석하여 문제점을 찾아내세요.

다음 6가지 카테고리로 이슈를 분류하세요:

1. DOUBLE_BARRELED (기본 심각도: CRITICAL)
   - 하나의 질문에서 두 가지 이상의 개념을 동시에 물어봄
   - 예: "이 제품의 품질과 가격에 만족하십니까?" → 품질과 가격을 분리해야 함

2. LEADING_BIASED (기본 심각도: CRITICAL)
   - 특정 답변을 유도하거나 편향된 표현 사용
   - 예: "대부분의 전문가가 추천하는 이 제품을 사용할 의향이 있으십니까?"
   - 예: 긍정적/부정적 표현이 과도하게 포함된 질문

3. AMBIGUOUS (기본 심각도: WARNING)
   - "자주", "최근", "좋은", "많은" 등 주관적이거나 모호한 표현 사용
   - 측정 기준이 명확하지 않은 경우
   - 예: "최근에 이 제품을 자주 사용하셨습니까?" → "최근"과 "자주"의 기준 불명확

4. RESPONSE_OPTIONS (기본 심각도: WARNING)
   - 보기 범위 중복 (예: "1-5명", "5-10명" → 5명이 중복)
   - 보기 범위 누락 (빠진 구간이 있음)
   - 보기 불균형 (긍정/부정 보기 수 차이)
   - 필요한 "기타" 또는 "해당 없음" 보기 미포함
   - 척도 앵커 라벨 불일치

5. COMPLEX (기본 심각도: INFO)
   - 문항 텍스트가 과도하게 긴 경우 (100자 초과)
   - 보기 개수가 15개 초과
   - 이중 부정 사용

6. INAPPROPRIATE (기본 심각도: WARNING)
   - 응답자가 이해하기 어려운 전문 용어 사용
   - 불필요하게 어려운 표현
   - 민감한 질문에 대한 완충 표현 부재

분석 규칙:
- 이슈가 없는 문항은 issues를 빈 배열로 반환
- 하나의 문항에 여러 이슈가 있을 수 있음
- description은 구체적으로 어떤 부분이 문제인지 명시
- suggestion은 실제 적용 가능한 개선안 제시
- 보기(answer_options)가 제공된 경우 보기 품질도 함께 분석

출력 형식 (JSON):
{
  "results": [
    {
      "question_number": "Q1",
      "issues": [
        {
          "category": "DOUBLE_BARRELED",
          "severity": "CRITICAL",
          "description": "...",
          "suggestion": "..."
        }
      ]
    }
  ]
}"""

_SYSTEM_PROMPT_EN = """You are a survey methodology expert. Analyze the quality of given survey questions and identify issues.

Classify issues into these 6 categories:

1. DOUBLE_BARRELED (default severity: CRITICAL)
   - A single question asks about two or more concepts simultaneously
   - Example: "Are you satisfied with the quality and price of this product?" → Quality and price should be separate questions

2. LEADING_BIASED (default severity: CRITICAL)
   - Wording that leads respondents toward a particular answer or contains bias
   - Example: "Would you be willing to use this product recommended by most experts?"
   - Example: Questions with excessively positive/negative framing

3. AMBIGUOUS (default severity: WARNING)
   - Vague or subjective terms: "often", "recently", "good", "many"
   - Unclear measurement criteria
   - Example: "Have you used this product frequently recently?" → "frequently" and "recently" are undefined

4. RESPONSE_OPTIONS (default severity: WARNING)
   - Overlapping ranges (e.g., "1-5", "5-10" → 5 is duplicated)
   - Missing ranges (gaps between options)
   - Unbalanced options (different number of positive vs. negative choices)
   - Missing "Other" or "Not applicable" option when needed
   - Inconsistent scale anchor labels

5. COMPLEX (default severity: INFO)
   - Excessively long question text (over 100 characters)
   - More than 15 answer options
   - Double negatives

6. INAPPROPRIATE (default severity: WARNING)
   - Technical jargon that respondents may not understand
   - Unnecessarily complicated expressions
   - Sensitive questions without buffer/softening language

Analysis rules:
- Return empty issues array for questions with no problems
- A single question may have multiple issues
- description must specifically identify the problematic part
- suggestion must provide actionable improvement recommendations
- When answer_options are provided, also analyze option quality

Output format (JSON):
{
  "results": [
    {
      "question_number": "Q1",
      "issues": [
        {
          "category": "DOUBLE_BARRELED",
          "severity": "CRITICAL",
          "description": "...",
          "suggestion": "..."
        }
      ]
    }
  ]
}"""


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
    if q.answer_options:
        opts = " | ".join(f"{o.code}. {o.label}" for o in q.answer_options)
        parts.append(f"Options: {opts}")
    return "\n".join(parts)


def _build_batch_prompt(batch: List[SurveyQuestion]) -> str:
    """배치 내 문항들을 하나의 프롬프트로 결합."""
    sections = []
    for q in batch:
        sections.append(_format_question_for_prompt(q))
    return (
        "Analyze the following survey questions for quality issues:\n\n"
        + "\n\n---\n\n".join(sections)
    )


def _parse_batch_result(
    raw: dict, batch: List[SurveyQuestion],
) -> List[QuestionQualityResult]:
    """LLM JSON 응답을 QuestionQualityResult 리스트로 변환."""
    results_raw = raw.get("results", [])
    qn_to_text = {q.question_number: q.question_text for q in batch}

    parsed = []
    seen_qn = set()

    for item in results_raw:
        qn = str(item.get("question_number", "")).strip()
        if not qn:
            continue
        seen_qn.add(qn)

        issues = []
        for iss in item.get("issues", []):
            cat = str(iss.get("category", "")).upper()
            sev = str(iss.get("severity", "WARNING")).upper()
            if cat not in CATEGORIES:
                continue
            if sev not in SEVERITIES:
                sev = "WARNING"
            issues.append(QualityIssue(
                category=cat,
                severity=sev,
                description=str(iss.get("description", "")),
                suggestion=str(iss.get("suggestion", "")),
            ))

        parsed.append(QuestionQualityResult(
            question_number=qn,
            question_text=qn_to_text.get(qn, ""),
            issues=issues,
        ))

    # LLM이 누락한 문항은 이슈 없음으로 추가
    for q in batch:
        if q.question_number not in seen_qn:
            parsed.append(QuestionQualityResult(
                question_number=q.question_number,
                question_text=q.question_text,
                issues=[],
            ))

    return parsed


# ── 메인 함수 ──────────────────────────────────────────────────────

def check_survey_quality(
    questions: List[SurveyQuestion],
    model: str = MODEL_QUALITY_CHECKER,
    language: str = "ko",
    progress_callback: Optional[Callable] = None,
) -> List[QuestionQualityResult]:
    """설문 문항 품질을 분석한다.

    Args:
        questions: 분석할 SurveyQuestion 리스트
        model: 사용할 Gemini 모델
        language: 분석 언어 ("ko" 또는 "en")
        progress_callback: (event, data) 형태의 콜백.
            Events: "batch_start", "batch_done"

    Returns:
        QuestionQualityResult 리스트 (문항 순서 보존)
    """
    if not questions:
        return []

    def _notify(event: str, data: dict):
        if progress_callback:
            progress_callback(event, data)

    system_prompt = _SYSTEM_PROMPT_KO if language == "ko" else _SYSTEM_PROMPT_EN

    # 배치 분할
    batches: List[List[SurveyQuestion]] = []
    for i in range(0, len(questions), BATCH_SIZE):
        batches.append(questions[i:i + BATCH_SIZE])

    total_batches = len(batches)
    all_results: List[QuestionQualityResult] = []

    def _process_batch(batch_idx: int, batch: List[SurveyQuestion]):
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
            # 실패 시 모든 문항을 이슈 없음으로 반환
            results = [
                QuestionQualityResult(
                    question_number=q.question_number,
                    question_text=q.question_text,
                    issues=[],
                )
                for q in batch
            ]
        _notify("batch_done", {
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "issues_found": sum(len(r.issues) for r in results),
        })
        return batch_idx, results

    if total_batches == 1:
        _, results = _process_batch(0, batches[0])
        all_results.extend(results)
    else:
        indexed_results = [None] * total_batches
        ctx = get_script_run_ctx()

        def _init_worker():
            """ThreadPoolExecutor worker initializer: propagate Streamlit context."""
            if ctx:
                add_script_run_ctx(threading.current_thread(), ctx)

        with ThreadPoolExecutor(max_workers=3, initializer=_init_worker) as executor:
            futures = {
                executor.submit(_process_batch, i, b): i
                for i, b in enumerate(batches)
            }
            for future in as_completed(futures):
                idx, results = future.result()
                indexed_results[idx] = results

        for batch_results in indexed_results:
            if batch_results is not None:
                all_results.extend(batch_results)

    # 원본 문항 순서로 정렬
    qn_order = {q.question_number: i for i, q in enumerate(questions)}
    all_results.sort(key=lambda r: qn_order.get(r.question_number, 999999))

    return all_results
