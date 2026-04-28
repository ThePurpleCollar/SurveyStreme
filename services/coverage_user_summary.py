"""User-facing summary for extraction coverage diagnostics.

The raw coverage report is intentionally conservative and may include false
positives such as option codes, ages, sizes, and price points. This module turns
that diagnostic output into action-oriented messages for survey users.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from services.coverage_checker import CoverageItem, CoverageReport


@dataclass
class UserCoverageMetric:
    label: str
    value: str
    status: str
    tone: str = "ok"
    detail: str = ""


@dataclass
class UserCoverageAction:
    title: str
    message: str
    evidence: str = ""
    kind: str = ""


@dataclass
class UserCoverageSummary:
    status_label: str
    tone: str
    headline: str
    guidance: str
    metrics: List[UserCoverageMetric] = field(default_factory=list)
    key_items: List[UserCoverageAction] = field(default_factory=list)
    reference_items: List[UserCoverageAction] = field(default_factory=list)


_NUMERIC_ONLY = re.compile(r"^\d+$")
_ALPHANUMERIC_QN = re.compile(r"^(?=.*[A-Za-z])[\w-]*\d[\w-]*$")
_HIGH_RISK_TABLE = re.compile(
    r"(scale|brand|rotation|product|purchase choice|choice card|"
    r"not .{0,25} at all|strongly|"
    r"\b1\s*\|\s*2\s*\|\s*3\s*\|\s*4|"
    r"_____%|percent|attribute|\[scale\])",
    re.IGNORECASE,
)
_LOW_RISK_TABLE = re.compile(
    r"(methodology|sample size|qualification|hello|confidential|"
    r"photograph|record|publish|share|reveal|personal information)",
    re.IGNORECASE,
)
_LIKELY_VALUE_CONTEXT = re.compile(
    r"(inch|inches|years?\s+old|minutes?|hours?|people|person|"
    r"price|usd|\$|less than|larger|older|younger|others?\s*\()",
    re.IGNORECASE,
)


def summarize_coverage_for_user(report: CoverageReport) -> UserCoverageSummary:
    """Convert raw extraction coverage diagnostics into user-facing guidance."""
    key_items: list[UserCoverageAction] = []
    reference_items: list[UserCoverageAction] = []

    for item in report.items:
        action = _action_from_item(item)
        if _is_key_item(item):
            key_items.append(action)
        else:
            reference_items.append(action)

    key_items = _dedupe_actions(key_items)
    reference_items = _dedupe_actions(reference_items)

    if key_items:
        status_label = "확인 후 진행 권장"
        tone = "warning"
        guidance = (
            f"자동 점검 결과, 결과 품질에 영향을 줄 수 있는 {len(key_items)}개 항목이 보입니다. "
            "이 점검은 원본 문서에서 문항처럼 보이는 후보를 넓게 감지해 추출 결과와 비교합니다. "
            "따라서 보기 코드, 나이, TV 사이즈, 가격처럼 실제 문항이 아닌 값도 참고 항목으로 표시될 수 있습니다. "
            "아래의 '먼저 확인할 항목'만 우선 확인한 뒤 Table Guide 생성을 진행해주세요."
        )
    elif reference_items:
        status_label = "진행 가능"
        tone = "info"
        guidance = (
            "추출은 완료되었고 다음 단계로 진행할 수 있습니다. "
            "아래 참고 항목은 자동 점검에서 문항 후보로 감지되었지만, "
            "대부분 보기 코드나 안내 표일 수 있습니다. 결과 테이블에 이상이 없어 보이면 별도로 수정하지 않아도 됩니다."
        )
    else:
        status_label = "진행 가능"
        tone = "ok"
        guidance = (
            "자동 점검에서 큰 리스크가 감지되지 않았습니다. "
            "추출 결과를 간단히 훑어본 뒤 Table Guide 생성을 진행해도 됩니다."
        )

    return UserCoverageSummary(
        status_label=status_label,
        tone=tone,
        headline=f"{report.extracted_questions}개 문항을 추출했습니다.",
        guidance=guidance,
        metrics=_build_metrics(report, key_items),
        key_items=key_items,
        reference_items=reference_items,
    )


def _build_metrics(
    report: CoverageReport,
    key_items: list[UserCoverageAction],
) -> list[UserCoverageMetric]:
    question_risk = any(i.kind == "question" for i in key_items)
    table_risk = any(i.kind == "table" for i in key_items)

    if question_risk:
        question_status = "확인 필요"
        question_tone = "warning"
        question_detail = "하위문항이나 특수 문항 후보가 있어 결과 테이블에 포함됐는지 확인해주세요."
    elif report.detected_questions > report.extracted_questions:
        question_status = "참고 확인"
        question_tone = "info"
        question_detail = "추가 후보가 감지됐지만, 보기 코드나 숫자값이 문항처럼 잡힌 경우가 많습니다."
    else:
        question_status = "양호"
        question_tone = "ok"
        question_detail = "원본에서 감지된 문항 후보와 추출 결과가 크게 어긋나지 않습니다."

    option_status = "양호" if report.options_matched else "확인 필요"
    option_tone = "ok" if report.options_matched else "warning"
    option_detail = (
        "응답 보기 추출은 전반적으로 양호합니다."
        if report.options_matched
        else "선택형 문항의 보기 목록이 결과 테이블에 들어갔는지 확인해주세요."
    )

    if report.skip_extracted:
        skip_value = f"{report.skip_extracted}개 조건 반영"
        skip_status = "양호"
        skip_tone = "ok"
        skip_detail = "TERMINATE, SKIP, GO TO 같은 주요 이동 조건이 추출 결과에 반영되었습니다."
    elif report.skip_patterns_found:
        skip_value = "원본 조건 확인 필요"
        skip_status = "확인 필요"
        skip_tone = "warning"
        skip_detail = "원본에는 이동/종료 표현이 있으나 추출 결과의 스킵 로직이 비어 있습니다."
    else:
        skip_value = "감지된 조건 없음"
        skip_status = "해당 없음"
        skip_tone = "info"
        skip_detail = "원본에서 명확한 스킵/종료 키워드는 감지되지 않았습니다."

    if report.filter_extracted:
        filter_value = f"{report.filter_extracted}개 문항에 조건 반영"
        filter_status = "확인 권장"
        filter_tone = "info"
        filter_detail = (
            "[PN:] 같은 프로그래머 노트가 많으면 자동 점검이 조건 수를 높게 잡을 수 있습니다. "
            "주요 ASK ONLY IF 조건만 확인하면 됩니다."
        )
    elif report.filter_patterns_found:
        filter_value = "대상 조건 확인 필요"
        filter_status = "확인 필요"
        filter_tone = "warning"
        filter_detail = "원본에는 대상 조건 표현이 있으나 추출 결과의 필터 조건이 비어 있습니다."
    else:
        filter_value = "감지된 조건 없음"
        filter_status = "해당 없음"
        filter_tone = "info"
        filter_detail = "원본에서 명확한 조건부 표시 문구는 감지되지 않았습니다."

    uncertain_tables = report.generic_tables + report.unknown_tables
    if table_risk:
        table_status = "확인 필요"
        table_tone = "warning"
        table_detail = "척도표, 브랜드별 매트릭스, 제품 선택 카드가 누락되면 Table Guide 품질에 영향을 줄 수 있습니다."
    elif uncertain_tables:
        table_status = "참고 확인"
        table_tone = "info"
        table_detail = "안내문이나 방법론 표도 함께 포함될 수 있어, 필요한 경우만 확인하면 됩니다."
    else:
        table_status = "양호"
        table_tone = "ok"
        table_detail = "보기표와 일반 표의 구조가 크게 문제 없이 분류되었습니다."

    return [
        UserCoverageMetric(
            "문항 구조",
            f"{report.extracted_questions}개 문항 추출",
            question_status,
            question_tone,
            question_detail,
        ),
        UserCoverageMetric(
            "응답 보기",
            f"{report.options_matched}개 문항에 보기 포함",
            option_status,
            option_tone,
            option_detail,
        ),
        UserCoverageMetric("스킵/종료 로직", skip_value, skip_status, skip_tone, skip_detail),
        UserCoverageMetric("필터/대상 조건", filter_value, filter_status, filter_tone, filter_detail),
        UserCoverageMetric(
            "표/척도 구조",
            f"자동 판단 어려운 표 {uncertain_tables}개" if uncertain_tables else "표 구조 양호",
            table_status,
            table_tone,
            table_detail,
        ),
    ]


def _is_key_item(item: CoverageItem) -> bool:
    if item.category == "question":
        qn = (item.question_number or "").strip()
        if _NUMERIC_ONLY.match(qn):
            return False
        return bool(_ALPHANUMERIC_QN.match(qn))

    if item.category == "table_drilldown":
        evidence = item.evidence or ""
        if _LOW_RISK_TABLE.search(evidence):
            return False
        return bool(_HIGH_RISK_TABLE.search(evidence))

    if item.category in {"options", "skip_logic", "filter", "instructions"}:
        return item.severity == "warning"

    return False


def _action_from_item(item: CoverageItem) -> UserCoverageAction:
    evidence = _compact_evidence(item.evidence)

    if item.category == "question":
        qn = item.question_number or "문항 후보"
        if _NUMERIC_ONLY.match(qn) or _LIKELY_VALUE_CONTEXT.search(item.evidence or ""):
            return UserCoverageAction(
                title=f"{qn} 후보",
                message="보기 코드, 수치, 나이, 사이즈 또는 가격값일 가능성이 높습니다.",
                evidence=evidence,
                kind="reference",
            )
        return UserCoverageAction(
            title=qn,
            message=(
                "문항 또는 하위문항으로 보입니다. 결과 테이블에서 해당 항목이 보이는지, "
                "누락되었다면 원본의 어느 문항에 포함되어야 하는지 확인해주세요."
            ),
            evidence=evidence,
            kind="question",
        )

    if item.category == "table_drilldown":
        title = _extract_table_title(item.description)
        if _is_key_item(item):
            message = (
                "보기, 척도 또는 매트릭스 표일 가능성이 있습니다. 관련 문항의 보기, 행, 척도값이 "
                "결과 테이블에 반영됐는지 확인해주세요."
            )
            kind = "table"
        else:
            message = "안내문, 방법론, 동의문 또는 보조 표일 가능성이 높습니다. 결과가 자연스러우면 수정하지 않아도 됩니다."
            kind = "reference"
        return UserCoverageAction(title, message, evidence, kind)

    if item.category == "table_classification":
        return UserCoverageAction(
            "자동 판단이 어려운 표",
            "일부 표는 보기표인지 안내표인지 자동 판단이 어려웠습니다.",
            evidence,
            "reference",
        )

    return UserCoverageAction(
        item.question_number or _category_title(item.category),
        item.description,
        evidence,
        item.category,
    )


def _extract_table_title(description: str) -> str:
    match = re.search(r"표\s+(\d+)", description or "")
    if match:
        return f"표 {match.group(1)}"
    return "표 확인"


def _category_title(category: str) -> str:
    return {
        "options": "응답 보기",
        "skip_logic": "스킵/종료 로직",
        "filter": "필터/대상 조건",
        "instructions": "지시문",
    }.get(category, "확인 항목")


def _compact_evidence(evidence: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", evidence or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _dedupe_actions(items: list[UserCoverageAction]) -> list[UserCoverageAction]:
    seen = set()
    deduped = []
    for item in items:
        key = (item.title, item.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
