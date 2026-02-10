"""링크테스트 체크리스트 자동 생성 서비스.

설문지 문항을 분석하여 링크테스트(프로그래밍 검수)에 필요한
체크항목을 알고리즘 + LLM으로 생성한다.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from models.survey import SurveyQuestion
from services.llm_client import call_llm_json
from services.skip_logic_service import (
    build_skip_logic_graph,
    parse_target,
    SkipLogicGraph,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CATEGORIES = [
    "SKIP_LOGIC",
    "PIPING",
    "ROTATION",
    "EXCLUSIVE_OPTION",
    "SCALE_CONSISTENCY",
    "FILTER_VALIDITY",
    "DEAD_END",
]

PRIORITIES = ["HIGH", "MEDIUM", "LOW"]

CATEGORY_LABELS = {
    "ko": {
        "SKIP_LOGIC": "스킵 로직",
        "PIPING": "파이핑",
        "ROTATION": "보기 로테이션",
        "EXCLUSIVE_OPTION": "배타적 보기",
        "SCALE_CONSISTENCY": "척도 일관성",
        "FILTER_VALIDITY": "필터 유효성",
        "DEAD_END": "데드엔드",
    },
    "en": {
        "SKIP_LOGIC": "Skip Logic",
        "PIPING": "Piping",
        "ROTATION": "Rotation",
        "EXCLUSIVE_OPTION": "Exclusive Option",
        "SCALE_CONSISTENCY": "Scale Consistency",
        "FILTER_VALIDITY": "Filter Validity",
        "DEAD_END": "Dead End",
    },
}

PRIORITY_LABELS = {
    "ko": {"HIGH": "높음", "MEDIUM": "보통", "LOW": "낮음"},
    "en": {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"},
}


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class ChecklistItem:
    item_id: int
    category: str           # CATEGORIES 중 하나
    priority: str           # HIGH / MEDIUM / LOW
    question_number: str    # 관련 Q# ("GLOBAL" 가능)
    title: str              # 짧은 설명
    detail: str             # 상세 검증 지시
    expected_behavior: str  # 테스터가 확인해야 할 동작
    source: str             # "ALGORITHMIC" | "LLM"


@dataclass
class ChecklistResult:
    items: List[ChecklistItem]
    language: str
    total_questions_analyzed: int

    def count_by_category(self) -> Dict[str, int]:
        counts = {cat: 0 for cat in CATEGORIES}
        for item in self.items:
            if item.category in counts:
                counts[item.category] += 1
        return counts

    def count_by_priority(self) -> Dict[str, int]:
        counts = {p: 0 for p in PRIORITIES}
        for item in self.items:
            if item.priority in counts:
                counts[item.priority] += 1
        return counts

    def filter_by_priority(self, priorities: List[str]) -> List[ChecklistItem]:
        return [i for i in self.items if i.priority in priorities]

    def filter_by_category(self, categories: List[str]) -> List[ChecklistItem]:
        return [i for i in self.items if i.category in categories]


# ---------------------------------------------------------------------------
# 알고리즘 검사 1: 스킵 로직
# ---------------------------------------------------------------------------

def _check_skip_logic(
    questions: List[SurveyQuestion],
    graph: SkipLogicGraph,
    lang: str,
) -> List[ChecklistItem]:
    """각 스킵 규칙에 대한 체크항목 생성."""
    items: List[ChecklistItem] = []

    for q in questions:
        if not q.skip_logic:
            continue
        for sl in q.skip_logic:
            parsed = parse_target(sl.target)
            target_display = parsed or sl.target

            if lang == "ko":
                title = f"{q.question_number} 스킵 로직 검증"
                detail = (
                    f"{q.question_number}에서 조건 '{sl.condition}' 충족 시 "
                    f"{target_display}(으)로 이동하는지 확인"
                )
                expected = (
                    f"해당 조건 선택 시 {target_display}(으)로 정확히 이동. "
                    f"중간 문항은 표시되지 않아야 함."
                )
            else:
                title = f"{q.question_number} skip logic verification"
                detail = (
                    f"When condition '{sl.condition}' is met at {q.question_number}, "
                    f"verify navigation to {target_display}"
                )
                expected = (
                    f"Selecting the condition should navigate to {target_display}. "
                    f"Intermediate questions should be skipped."
                )

            items.append(ChecklistItem(
                item_id=0,  # 나중에 부여
                category="SKIP_LOGIC",
                priority="HIGH",
                question_number=q.question_number,
                title=title,
                detail=detail,
                expected_behavior=expected,
                source="ALGORITHMIC",
            ))

    return items


# ---------------------------------------------------------------------------
# 알고리즘 검사 2: 데드엔드
# ---------------------------------------------------------------------------

def _check_dead_ends(
    questions: List[SurveyQuestion],
    graph: SkipLogicGraph,
    lang: str,
) -> List[ChecklistItem]:
    """도달 불가 / 고아 문항 탐지."""
    items: List[ChecklistItem] = []

    if not questions:
        return items

    question_nodes = [q.question_number for q in questions]
    first_node = question_nodes[0]

    # BFS 도달성
    adj: Dict[str, List[str]] = {qn: [] for qn in question_nodes}
    adj["END"] = []
    for edge in graph.edges:
        if edge.source in adj:
            adj[edge.source].append(edge.target)

    reachable = set()
    queue = [first_node]
    reachable.add(first_node)
    while queue:
        curr = queue.pop(0)
        for nxt in adj.get(curr, []):
            if nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)

    for qn in question_nodes:
        if qn not in reachable:
            if lang == "ko":
                title = f"{qn} 도달 불가 문항"
                detail = f"{qn}은(는) 어떤 경로로도 도달할 수 없습니다. 스킵 로직 설정을 확인하세요."
                expected = f"{qn}에 도달할 수 있는 경로가 존재해야 함"
            else:
                title = f"{qn} unreachable question"
                detail = f"{qn} cannot be reached through any path. Check skip logic settings."
                expected = f"There should be a valid path to reach {qn}"

            items.append(ChecklistItem(
                item_id=0,
                category="DEAD_END",
                priority="HIGH",
                question_number=qn,
                title=title,
                detail=detail,
                expected_behavior=expected,
                source="ALGORITHMIC",
            ))

    return items


# ---------------------------------------------------------------------------
# 알고리즘 검사 3: 필터 유효성
# ---------------------------------------------------------------------------

def _check_filter_validity(
    questions: List[SurveyQuestion],
    lang: str,
) -> List[ChecklistItem]:
    """filter_condition의 Q# 참조가 유효한지 검증."""
    items: List[ChecklistItem] = []
    valid_qns = {q.question_number.upper() for q in questions}

    _qn_pattern = re.compile(r'([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)', re.IGNORECASE)

    for q in questions:
        if not q.filter_condition:
            continue

        match = _qn_pattern.search(q.filter_condition)
        if not match:
            continue

        ref_qn = match.group(1).upper()
        if ref_qn not in valid_qns:
            if lang == "ko":
                title = f"{q.question_number} 필터 참조 오류"
                detail = (
                    f"{q.question_number}의 필터 조건 '{q.filter_condition}'이 "
                    f"존재하지 않는 문항 {ref_qn}을(를) 참조합니다."
                )
                expected = f"필터 조건이 유효한 문항을 참조해야 함"
            else:
                title = f"{q.question_number} invalid filter reference"
                detail = (
                    f"Filter condition '{q.filter_condition}' at {q.question_number} "
                    f"references non-existent question {ref_qn}."
                )
                expected = f"Filter condition should reference a valid question"

            items.append(ChecklistItem(
                item_id=0,
                category="FILTER_VALIDITY",
                priority="HIGH",
                question_number=q.question_number,
                title=title,
                detail=detail,
                expected_behavior=expected,
                source="ALGORITHMIC",
            ))
        else:
            # 유효한 참조 — 필터 동작 확인 체크항목
            if lang == "ko":
                title = f"{q.question_number} 필터 조건 동작 확인"
                detail = (
                    f"{q.question_number}은(는) '{q.filter_condition}' 조건으로 필터링됩니다. "
                    f"조건을 충족하지 않는 응답자에게 이 문항이 표시되지 않는지 확인하세요."
                )
                expected = f"필터 조건 미충족 시 {q.question_number} 비표시"
            else:
                title = f"{q.question_number} filter condition check"
                detail = (
                    f"{q.question_number} is filtered by '{q.filter_condition}'. "
                    f"Verify that respondents not meeting the condition do not see this question."
                )
                expected = f"{q.question_number} should not display when filter condition is not met"

            items.append(ChecklistItem(
                item_id=0,
                category="FILTER_VALIDITY",
                priority="MEDIUM",
                question_number=q.question_number,
                title=title,
                detail=detail,
                expected_behavior=expected,
                source="ALGORITHMIC",
            ))

    return items


# ---------------------------------------------------------------------------
# 알고리즘 검사 4: 배타적 보기
# ---------------------------------------------------------------------------

_EXCLUSIVE_PATTERNS = re.compile(
    r'없[음다]|모[름르]|해당\s*없|해당\s*사항|기타|'
    r'none|nothing|n/?a|not\s*applicable|don.?t\s*know|other|'
    r'all\s*of\s*the\s*above|위의\s*모두',
    re.IGNORECASE,
)


def _check_exclusive_options(
    questions: List[SurveyQuestion],
    lang: str,
) -> List[ChecklistItem]:
    """SA/MA의 기타/없음/모름 보기 배타성 확인."""
    items: List[ChecklistItem] = []

    for q in questions:
        if not q.answer_options:
            continue
        qtype = (q.question_type or "").upper()
        if qtype not in ("MA", "SA", "MULTI", "SINGLE"):
            continue

        exclusive_opts = []
        for opt in q.answer_options:
            if _EXCLUSIVE_PATTERNS.search(opt.label):
                exclusive_opts.append(opt)

        if not exclusive_opts and qtype in ("MA", "MULTI"):
            continue

        for opt in exclusive_opts:
            if qtype in ("MA", "MULTI"):
                if lang == "ko":
                    title = f"{q.question_number} 배타적 보기 확인 ({opt.code})"
                    detail = (
                        f"{q.question_number} (MA)에서 '{opt.code}. {opt.label}' 선택 시 "
                        f"다른 보기와 동시 선택이 불가능한지 확인"
                    )
                    expected = f"'{opt.label}' 선택 시 다른 보기 자동 해제"
                else:
                    title = f"{q.question_number} exclusive option check ({opt.code})"
                    detail = (
                        f"In {q.question_number} (MA), verify that selecting "
                        f"'{opt.code}. {opt.label}' deselects all other options"
                    )
                    expected = f"Selecting '{opt.label}' should deselect all other options"

                items.append(ChecklistItem(
                    item_id=0,
                    category="EXCLUSIVE_OPTION",
                    priority="HIGH",
                    question_number=q.question_number,
                    title=title,
                    detail=detail,
                    expected_behavior=expected,
                    source="ALGORITHMIC",
                ))

    return items


# ---------------------------------------------------------------------------
# 알고리즘 검사 5: 로테이션
# ---------------------------------------------------------------------------

_ROTATION_PATTERNS = re.compile(
    r'rotat[eion]|random|shuffle|랜덤|로테이션|순서\s*무작위|보기\s*순서|역순',
    re.IGNORECASE,
)


def _check_rotation(
    questions: List[SurveyQuestion],
    lang: str,
) -> List[ChecklistItem]:
    """instructions에서 ROTATE/랜덤 키워드 탐지."""
    items: List[ChecklistItem] = []

    for q in questions:
        text_to_check = (q.instructions or "") + " " + (q.response_base or "")
        if not _ROTATION_PATTERNS.search(text_to_check):
            continue

        if lang == "ko":
            title = f"{q.question_number} 보기 로테이션 확인"
            detail = (
                f"{q.question_number}에 로테이션/랜덤 지시가 있습니다 "
                f"('{(q.instructions or '')[:60]}'). "
                f"보기 순서가 응답자마다 다르게 표시되는지 확인하세요."
            )
            expected = "보기 순서가 응답자마다 무작위로 변경됨"
        else:
            title = f"{q.question_number} rotation verification"
            detail = (
                f"{q.question_number} has rotation/randomization instructions "
                f"('{(q.instructions or '')[:60]}'). "
                f"Verify that option order varies between respondents."
            )
            expected = "Option order should vary randomly between respondents"

        items.append(ChecklistItem(
            item_id=0,
            category="ROTATION",
            priority="MEDIUM",
            question_number=q.question_number,
            title=title,
            detail=detail,
            expected_behavior=expected,
            source="ALGORITHMIC",
        ))

    return items


# ---------------------------------------------------------------------------
# LLM 검사: 파이핑 + 척도 일관성
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_KO = """당신은 설문조사 프로그래밍 검수(링크테스트) 전문가입니다.
주어진 설문 문항들을 분석하여 다음 두 가지를 검사하세요:

1. **PIPING**: 문항 텍스트나 보기에서 다른 문항의 응답을 참조(파이핑)하는 부분을 찾으세요.
   - [Q1 응답], {Q2_answer}, <<Q3>> 등의 패턴
   - "앞서 선택한", "위에서 응답한" 등의 참조 표현
   - 파이핑 참조가 올바른 문항을 가리키는지 확인 항목 생성

2. **SCALE_CONSISTENCY**: 유사한 척도 문항들의 일관성을 검사하세요.
   - 같은 유형의 질문인데 척도가 다른 경우 (5점 vs 7점)
   - 척도 앵커 라벨이 불일치하는 경우

출력 형식 (JSON):
{
  "items": [
    {
      "category": "PIPING" 또는 "SCALE_CONSISTENCY",
      "priority": "HIGH" 또는 "MEDIUM" 또는 "LOW",
      "question_number": "Q1",
      "title": "짧은 설명",
      "detail": "상세 검증 지시",
      "expected_behavior": "테스터가 확인해야 할 동작"
    }
  ]
}

이슈가 없으면 items를 빈 배열로 반환하세요."""

_SYSTEM_PROMPT_EN = """You are a survey programming QA (link test) expert.
Analyze the given survey questions for two types of issues:

1. **PIPING**: Find references to other question responses in question text or options.
   - Patterns like [Q1 response], {Q2_answer}, <<Q3>>
   - Phrases like "previously selected", "answered above"
   - Generate check items to verify piping references point to correct questions

2. **SCALE_CONSISTENCY**: Check consistency among similar scale questions.
   - Same type of questions using different scales (5-point vs 7-point)
   - Inconsistent scale anchor labels

Output format (JSON):
{
  "items": [
    {
      "category": "PIPING" or "SCALE_CONSISTENCY",
      "priority": "HIGH" or "MEDIUM" or "LOW",
      "question_number": "Q1",
      "title": "short description",
      "detail": "detailed verification instruction",
      "expected_behavior": "what tester should verify"
    }
  ]
}

Return empty items array if no issues found."""


def _format_questions_for_llm(questions: List[SurveyQuestion]) -> str:
    """문항들을 LLM 프롬프트용 텍스트로 변환."""
    parts = []
    for q in questions:
        lines = [f"[{q.question_number}]"]
        if q.question_type:
            lines.append(f"Type: {q.question_type}")
        lines.append(f"Text: {q.question_text}")
        if q.filter_condition:
            lines.append(f"Filter: {q.filter_condition}")
        if q.answer_options:
            opts = " | ".join(f"{o.code}. {o.label}" for o in q.answer_options)
            lines.append(f"Options: {opts}")
        if q.instructions:
            lines.append(f"Instructions: {q.instructions}")
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)




BATCH_SIZE = 30


def _check_piping_and_scales(
    questions: List[SurveyQuestion],
    model: str,
    lang: str,
    progress_callback: Optional[Callable] = None,
) -> List[ChecklistItem]:
    """LLM으로 파이핑 참조 + 척도 일관성 검사."""
    items: List[ChecklistItem] = []
    system_prompt = _SYSTEM_PROMPT_KO if lang == "ko" else _SYSTEM_PROMPT_EN

    # 배치 분할
    batches = [questions[i:i + BATCH_SIZE] for i in range(0, len(questions), BATCH_SIZE)]
    total_batches = len(batches)

    def _notify(event: str, data: dict):
        if progress_callback:
            progress_callback(event, data)

    for batch_idx, batch in enumerate(batches):
        _notify("batch_start", {
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "question_count": len(batch),
        })

        user_prompt = (
            "Analyze the following survey questions for piping references "
            "and scale consistency issues:\n\n"
            + _format_questions_for_llm(batch)
        )

        try:
            raw = call_llm_json(system_prompt, user_prompt, model)
            for item_raw in raw.get("items", []):
                cat = str(item_raw.get("category", "")).upper()
                if cat not in ("PIPING", "SCALE_CONSISTENCY"):
                    continue
                priority = str(item_raw.get("priority", "MEDIUM")).upper()
                if priority not in PRIORITIES:
                    priority = "MEDIUM"

                items.append(ChecklistItem(
                    item_id=0,
                    category=cat,
                    priority=priority,
                    question_number=str(item_raw.get("question_number", "GLOBAL")),
                    title=str(item_raw.get("title", "")),
                    detail=str(item_raw.get("detail", "")),
                    expected_behavior=str(item_raw.get("expected_behavior", "")),
                    source="LLM",
                ))
        except Exception as e:
            logger.error(f"LLM checklist batch {batch_idx} failed: {e}")

        _notify("batch_done", {
            "batch_index": batch_idx,
            "total_batches": total_batches,
            "items_found": len(items),
        })

    return items


# ---------------------------------------------------------------------------
# 메인 함수
# ---------------------------------------------------------------------------


def generate_checklist(
    questions: List[SurveyQuestion],
    language: str = "ko",
    model: str = "gemini-2.5-flash",
    progress_callback: Optional[Callable] = None,
) -> ChecklistResult:
    """링크테스트 체크리스트를 생성한다.

    Args:
        questions: 분석할 SurveyQuestion 리스트
        language: "ko" 또는 "en"
        model: LLM 모델명
        progress_callback: (event, data) 형태의 콜백.
            Events: "phase", "batch_start", "batch_done"

    Returns:
        ChecklistResult
    """
    if not questions:
        return ChecklistResult(items=[], language=language, total_questions_analyzed=0)

    def _notify(event: str, data: dict):
        if progress_callback:
            progress_callback(event, data)

    all_items: List[ChecklistItem] = []
    graph = build_skip_logic_graph(questions)

    # Phase 1: 알고리즘 검사 (즉시)
    _notify("phase", {"name": "algorithmic", "status": "start"})

    all_items.extend(_check_skip_logic(questions, graph, language))
    all_items.extend(_check_dead_ends(questions, graph, language))
    all_items.extend(_check_filter_validity(questions, language))
    all_items.extend(_check_exclusive_options(questions, language))
    all_items.extend(_check_rotation(questions, language))

    _notify("phase", {"name": "algorithmic", "status": "done", "count": len(all_items)})

    # Phase 2: LLM 검사
    _notify("phase", {"name": "llm", "status": "start"})

    llm_items = _check_piping_and_scales(
        questions, model, language, progress_callback=progress_callback,
    )
    all_items.extend(llm_items)

    _notify("phase", {"name": "llm", "status": "done", "count": len(llm_items)})

    # item_id 부여
    for i, item in enumerate(all_items, start=1):
        item.item_id = i

    return ChecklistResult(
        items=all_items,
        language=language,
        total_questions_analyzed=len(questions),
    )
