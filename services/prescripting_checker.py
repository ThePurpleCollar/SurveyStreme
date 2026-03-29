"""Pre-Scripting Review — 스크립팅 전 설문지 오류 검출.

알고리즘 검출 (LLM 불필요, 즉시 실행):
- 보기 코드 누락/중복
- 스킵 로직 대상 문항 존재 여부
- 필터 조건 참조 문항 존재 여부
- 데드엔드 경로 (스킵 후 도달 불가)
- 문항번호 중복
- 문항 유형 vs 보기 수 불일치

AI 검출 (LLM 기반, 선택 실행):
- 오타/문법 오류
- 보기 MECE 검증
- 문항 간 논리적 충돌
"""

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from models.survey import SurveyQuestion

logger = logging.getLogger(__name__)


@dataclass
class ReviewItem:
    """검출된 이슈 항목."""
    severity: str           # "critical" | "warning" | "info"
    category: str           # "option_code" | "skip_logic" | "filter" | "dead_end" |
                            # "duplicate_qn" | "type_mismatch" | "typo" | "mece" | "logic"
    question_number: str    # 관련 문항번호
    title: str              # 이슈 제목
    detail: str             # 상세 설명
    resolved: bool = False  # 사용자가 확인 완료 여부


@dataclass
class ReviewReport:
    """Pre-Scripting Review 결과."""
    items: List[ReviewItem] = field(default_factory=list)
    total_questions: int = 0

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.items if i.severity == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.items if i.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.items if i.severity == "info")

    @property
    def has_issues(self) -> bool:
        return len(self.items) > 0


# ── 카테고리 한국어 라벨 ──
CATEGORY_LABELS = {
    "option_code": "보기 코드",
    "skip_logic": "스킵 로직",
    "filter": "필터 조건",
    "dead_end": "데드엔드",
    "duplicate_qn": "문항번호 중복",
    "type_mismatch": "유형-보기 불일치",
    "typo": "오타/문법",
    "mece": "MECE 검증",
    "logic": "논리 충돌",
}

SEVERITY_LABELS = {
    "critical": "심각",
    "warning": "경고",
    "info": "참고",
}


def run_algorithmic_checks(questions: List[SurveyQuestion]) -> ReviewReport:
    """알고리즘 기반 즉시 검출. LLM 불필요.

    Args:
        questions: SurveyQuestion 리스트

    Returns:
        ReviewReport
    """
    report = ReviewReport(total_questions=len(questions))
    if not questions:
        return report

    # 문항번호 → 문항 매핑
    qn_map = {}
    for q in questions:
        if q.question_number not in qn_map:
            qn_map[q.question_number] = q

    all_qns = set(qn_map.keys())

    # ── 1. 문항번호 중복 ──
    seen_qns = {}
    for q in questions:
        qn = q.question_number
        if qn in seen_qns:
            # table_number가 다르면 정상 분할 (Grid 등)
            if q.table_number != seen_qns[qn].table_number:
                continue
            report.items.append(ReviewItem(
                severity="warning",
                category="duplicate_qn",
                question_number=qn,
                title=f"문항번호 중복: {qn}",
                detail=f"문항번호 '{qn}'이 2회 이상 사용되었습니다.",
            ))
        else:
            seen_qns[qn] = q

    # ── 2. 보기 코드 누락/중복 ──
    for q in questions:
        if not q.answer_options or len(q.answer_options) < 2:
            continue

        codes = [opt.code for opt in q.answer_options]

        # 중복 코드
        seen_codes = set()
        for code in codes:
            if code in seen_codes:
                report.items.append(ReviewItem(
                    severity="critical",
                    category="option_code",
                    question_number=q.question_number,
                    title=f"보기 코드 중복: {q.question_number}",
                    detail=f"코드 '{code}'가 중복 사용되었습니다.",
                ))
                break
            seen_codes.add(code)

        # 연속 숫자 코드의 누락 검사 (1,2,3,5 → 4 빠짐)
        numeric_codes = []
        for c in codes:
            try:
                numeric_codes.append(int(c))
            except ValueError:
                pass

        if len(numeric_codes) >= 3:
            numeric_codes.sort()
            # 특수 코드(98, 99 등) 제외
            regular = [c for c in numeric_codes if c < 90]
            if len(regular) >= 3:
                for i in range(len(regular) - 1):
                    gap = regular[i + 1] - regular[i]
                    if gap > 1:
                        missing = list(range(regular[i] + 1, regular[i + 1]))
                        report.items.append(ReviewItem(
                            severity="warning",
                            category="option_code",
                            question_number=q.question_number,
                            title=f"보기 코드 누락 의심: {q.question_number}",
                            detail=f"코드 {missing}가 누락된 것으로 보입니다. "
                                   f"현재 코드: {regular}",
                        ))
                        break

    # ── 3. 스킵 로직 대상 문항 존재 여부 ──
    for q in questions:
        for sl in q.skip_logic:
            target = sl.target.strip()
            if not target:
                continue
            # "Q5", "Q10" 등 문항번호 추출
            target_qn = re.match(r'([A-Za-z0-9_]+)', target)
            if target_qn:
                target_id = target_qn.group(1)
                if target_id not in all_qns and target_id.upper() not in ('END', 'COMPLETE', 'TERMINATE'):
                    report.items.append(ReviewItem(
                        severity="critical",
                        category="skip_logic",
                        question_number=q.question_number,
                        title=f"스킵 대상 문항 없음: {q.question_number} → {target_id}",
                        detail=f"문항 {q.question_number}의 스킵 로직이 '{target_id}'로 이동하지만, "
                               f"해당 문항이 존재하지 않습니다.",
                    ))

    # ── 4. 필터 조건 참조 문항 존재 여부 ──
    for q in questions:
        if not q.filter_condition:
            continue
        filt = q.filter_condition
        if filt.lower() in ('all respondents', '모두', '전원', '모두에게'):
            continue
        # 필터에서 참조하는 문항번호 추출 (Q1=1, Q3=1,2 등)
        refs = re.findall(r'([A-Za-z]+\d+[a-z]?)(?:\s*[=!<>])', filt)
        for ref in refs:
            if ref not in all_qns:
                report.items.append(ReviewItem(
                    severity="critical",
                    category="filter",
                    question_number=q.question_number,
                    title=f"필터 참조 문항 없음: {q.question_number}",
                    detail=f"필터 조건 '{filt}'에서 참조하는 문항 '{ref}'가 존재하지 않습니다.",
                ))

    # ── 5. 문항 유형 vs 보기 수 불일치 ──
    for q in questions:
        qtype = (q.question_type or "").upper()
        opt_count = len(q.answer_options)

        # SA인데 보기 0~1개
        if qtype == "SA" and 0 < opt_count < 2:
            report.items.append(ReviewItem(
                severity="warning",
                category="type_mismatch",
                question_number=q.question_number,
                title=f"SA 문항에 보기 부족: {q.question_number}",
                detail=f"단수응답(SA) 문항인데 보기가 {opt_count}개뿐입니다.",
            ))

        # MA인데 보기 0~1개
        if qtype == "MA" and 0 < opt_count < 2:
            report.items.append(ReviewItem(
                severity="warning",
                category="type_mismatch",
                question_number=q.question_number,
                title=f"MA 문항에 보기 부족: {q.question_number}",
                detail=f"복수응답(MA) 문항인데 보기가 {opt_count}개뿐입니다.",
            ))

        # OE인데 보기가 있음
        if qtype == "OE" and opt_count > 0:
            report.items.append(ReviewItem(
                severity="info",
                category="type_mismatch",
                question_number=q.question_number,
                title=f"주관식에 보기 존재: {q.question_number}",
                detail=f"주관식(OE) 문항인데 보기가 {opt_count}개 있습니다. 의도된 것인지 확인해주세요.",
            ))

    # ── 6. 데드엔드 검출 (간이) ──
    # 스킵 로직으로 건너뛰는 범위 내에 도달 불가능한 문항이 있는지
    q_order = [q.question_number for q in questions if q.question_number not in seen_qns
               or seen_qns.get(q.question_number) is q]
    # 중복 제거한 순서
    seen_order = set()
    ordered_qns = []
    for qn in q_order:
        if qn not in seen_order:
            seen_order.add(qn)
            ordered_qns.append(qn)

    qn_index = {qn: i for i, qn in enumerate(ordered_qns)}

    for q in questions:
        for sl in q.skip_logic:
            target = sl.target.strip()
            target_qn = re.match(r'([A-Za-z0-9_]+)', target)
            if not target_qn:
                continue
            target_id = target_qn.group(1)
            if target_id not in qn_index:
                continue

            src_idx = qn_index.get(q.question_number)
            tgt_idx = qn_index.get(target_id)
            if src_idx is None or tgt_idx is None:
                continue

            # 건너뛰는 범위가 3문항 이상이면 경고
            if tgt_idx - src_idx > 5:
                skipped = ordered_qns[src_idx + 1:tgt_idx]
                # 건너뛴 문항 중 다른 경로로 도달 가능한지는 간이 체크하지 않음
                # (완전한 데드엔드 검출은 Path Simulator에서)
                report.items.append(ReviewItem(
                    severity="info",
                    category="dead_end",
                    question_number=q.question_number,
                    title=f"대규모 스킵: {q.question_number} → {target_id}",
                    detail=f"{len(skipped)}개 문항을 건너뜁니다 ({', '.join(skipped[:5])}{'...' if len(skipped) > 5 else ''}). "
                           f"건너뛴 문항이 다른 경로로 도달 가능한지 확인해주세요.",
                ))

    # 심각도 정렬: critical → warning → info
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    report.items.sort(key=lambda x: (severity_order.get(x.severity, 9), x.question_number))

    return report


def run_ai_checks(questions: List[SurveyQuestion], language: str = "ko",
                  progress_callback=None) -> List[ReviewItem]:
    """AI 기반 검출 (LLM 사용). 오타, MECE, 논리 충돌.

    Args:
        questions: SurveyQuestion 리스트
        language: 분석 언어
        progress_callback: 진행 콜백

    Returns:
        ReviewItem 리스트
    """
    from services.llm_client import call_llm_json, MODEL_QUALITY_CHECKER

    items = []
    if not questions:
        return items

    # 배치 처리
    batch_size = 15
    batches = [questions[i:i + batch_size] for i in range(0, len(questions), batch_size)]

    system_prompt = f"""당신은 설문지 스크립팅 전 검토 전문가입니다.
다음 설문 문항들에서 오타, 문법 오류, MECE 위반(보기가 상호배타적/전체포괄적이지 않은 경우),
문항 간 논리적 충돌을 찾아 JSON으로 반환하세요.

출력 언어: {"한국어" if language == "ko" else "English"}

JSON 형식:
{{"issues": [
  {{"question_number": "Q1", "category": "typo|mece|logic",
    "severity": "critical|warning|info",
    "title": "이슈 제목", "detail": "상세 설명"}}
]}}

이슈가 없으면: {{"issues": []}}"""

    for batch_idx, batch in enumerate(batches):
        if progress_callback:
            progress_callback("batch_start", {
                "batch_index": batch_idx,
                "total_batches": len(batches),
                "question_count": len(batch),
            })

        user_lines = []
        for q in batch:
            opts = " | ".join(f"{o.code}.{o.label}" for o in q.answer_options[:20])
            line = f"[{q.question_number}] {q.question_text} ({q.question_type or '?'})"
            if opts:
                line += f"\n  보기: {opts}"
            if q.filter_condition:
                line += f"\n  필터: {q.filter_condition}"
            user_lines.append(line)

        try:
            result = call_llm_json(system_prompt, "\n\n".join(user_lines),
                                    MODEL_QUALITY_CHECKER, max_tokens=4096)
            for iss in result.get("issues", []):
                items.append(ReviewItem(
                    severity=iss.get("severity", "info"),
                    category=iss.get("category", "logic"),
                    question_number=iss.get("question_number", ""),
                    title=iss.get("title", ""),
                    detail=iss.get("detail", ""),
                ))
        except Exception as e:
            logger.error(f"AI check batch {batch_idx} failed: {e}")

        if progress_callback:
            progress_callback("batch_done", {
                "batch_index": batch_idx,
                "total_batches": len(batches),
                "issues_found": len(items),
            })

    return items
