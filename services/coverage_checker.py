"""추출 커버리지 검증 — 원본 DOCX 파싱 결과와 LLM 추출 결과를 비교.

파싱된 구조(섹션, 표, 단락)에서 기대되는 정보량과
실제 추출된 SurveyQuestion 데이터를 비교하여 누락 항목을 감지합니다.
"""

import re
from dataclasses import dataclass, field
from typing import List

from services.docx_parser import DocxSection, DocxParagraph, DocxTable
from models.survey import SurveyQuestion


# 문항번호 패턴 (파싱된 텍스트에서 감지)
_QN_PATTERN = re.compile(
    r'(?:^|\n)\s*(?:\*\*)?'
    r'([A-Za-z]+[a-z]*\d+[a-z]?(?:-\d+)*)'
    r'[.)\s:\[]',
)

# 스킵/필터 패턴
_SKIP_PATTERN = re.compile(
    r'(?:go\s*to|skip\s*to|이동|건너뜀)',
    re.IGNORECASE,
)
_FILTER_PATTERN = re.compile(
    r'(?:ask\s*if|only\s*if|ask\s*all|\[pn:|모두에게|응답자만)',
    re.IGNORECASE,
)
_INSTRUCTION_PATTERN = re.compile(
    r'(?:show\s*card|rotate|randomize|보기\s*로테이션|카드\s*제시|제시)',
    re.IGNORECASE,
)


@dataclass
class CoverageItem:
    """누락 감지 항목."""
    category: str       # "question" | "options" | "skip_logic" | "filter" | "instructions"
    question_number: str  # 관련 문항번호 (없으면 "")
    description: str    # 사용자에게 보여줄 설명
    severity: str = "warning"  # "warning" | "info"


@dataclass
class CoverageReport:
    """커버리지 검증 결과."""
    # 통계
    detected_questions: int = 0     # 파싱에서 감지된 잠재 문항 수
    extracted_questions: int = 0    # LLM이 추출한 문항 수
    tables_total: int = 0           # 원본 표 수
    tables_with_options: int = 0    # code_label/generic 표 수 (보기 후보)
    options_matched: int = 0        # 보기가 있는 문항 수
    skip_patterns_found: int = 0    # 원본에서 감지된 스킵 패턴 수
    skip_extracted: int = 0         # 추출된 스킵로직 수
    filter_patterns_found: int = 0
    filter_extracted: int = 0
    instruction_patterns_found: int = 0
    instruction_extracted: int = 0
    # 누락 항목
    items: List[CoverageItem] = field(default_factory=list)

    @property
    def question_coverage(self) -> float:
        if self.detected_questions == 0:
            return 1.0
        return self.extracted_questions / self.detected_questions

    @property
    def options_coverage(self) -> float:
        if self.tables_with_options == 0:
            return 1.0
        return self.options_matched / self.tables_with_options

    @property
    def skip_coverage(self) -> float:
        if self.skip_patterns_found == 0:
            return 1.0
        return min(self.skip_extracted / self.skip_patterns_found, 1.0)

    @property
    def filter_coverage(self) -> float:
        if self.filter_patterns_found == 0:
            return 1.0
        return min(self.filter_extracted / self.filter_patterns_found, 1.0)

    @property
    def has_issues(self) -> bool:
        return len(self.items) > 0


def check_extraction_coverage(
    sections: List[DocxSection],
    questions: List[SurveyQuestion],
) -> CoverageReport:
    """파싱된 원본과 추출 결과를 비교하여 커버리지 리포트를 생성.

    Args:
        sections: parse_docx() 결과
        questions: LLM 추출 후 최종 SurveyQuestion 리스트

    Returns:
        CoverageReport
    """
    report = CoverageReport()
    report.extracted_questions = len(questions)
    extracted_qns = {q.question_number for q in questions}

    # ── 1. 원본에서 문항번호 패턴 감지 ──
    detected_qns = set()
    all_text = ""
    for section in sections:
        for item in section.content:
            if isinstance(item, DocxParagraph):
                all_text += item.text + "\n"

    for m in _QN_PATTERN.finditer(all_text):
        detected_qns.add(m.group(1))
    report.detected_questions = len(detected_qns)

    # 누락 문항 감지
    missed_qns = detected_qns - extracted_qns
    for qn in sorted(missed_qns):
        report.items.append(CoverageItem(
            category="question",
            question_number=qn,
            description=f"문항 {qn}이 문서에서 감지되었으나 추출되지 않았습니다.",
        ))

    # ── 2. 표 기반 보기 커버리지 ──
    tables_total = 0
    tables_with_options = 0
    for section in sections:
        for item in section.content:
            if isinstance(item, DocxTable):
                tables_total += 1
                ttype = getattr(item, 'table_type', 'unknown')
                if ttype in ('code_label', 'generic', 'unknown'):
                    tables_with_options += 1

    report.tables_total = tables_total
    report.tables_with_options = tables_with_options

    # 보기가 있는 문항 수
    questions_with_options = sum(1 for q in questions if q.answer_options)
    report.options_matched = questions_with_options

    # 보기가 없는데 보기 표가 근처에 있을 가능성
    if tables_with_options > 0 and questions_with_options < len(questions) * 0.5:
        no_options = [q.question_number for q in questions if not q.answer_options
                      and q.question_type in ('SA', 'MA', None)]
        for qn in no_options[:10]:
            report.items.append(CoverageItem(
                category="options",
                question_number=qn,
                description=f"문항 {qn}에 보기가 추출되지 않았습니다. 원본 문서를 확인해주세요.",
                severity="info",
            ))

    # ── 3. 스킵로직 패턴 커버리지 ──
    skip_patterns = len(_SKIP_PATTERN.findall(all_text))
    skip_extracted = sum(len(q.skip_logic) for q in questions)
    report.skip_patterns_found = skip_patterns
    report.skip_extracted = skip_extracted

    if skip_patterns > 0 and skip_extracted == 0:
        report.items.append(CoverageItem(
            category="skip_logic",
            question_number="",
            description=f"문서에서 {skip_patterns}개의 스킵 로직 패턴이 감지되었으나 추출된 것이 없습니다.",
        ))

    # ── 4. 필터 패턴 커버리지 ──
    filter_patterns = len(_FILTER_PATTERN.findall(all_text))
    filter_extracted = sum(1 for q in questions if q.filter_condition)
    report.filter_patterns_found = filter_patterns
    report.filter_extracted = filter_extracted

    if filter_patterns > 0 and filter_extracted == 0:
        report.items.append(CoverageItem(
            category="filter",
            question_number="",
            description=f"문서에서 {filter_patterns}개의 필터 패턴이 감지되었으나 추출된 것이 없습니다.",
        ))

    # ── 5. 지시문 패턴 커버리지 ──
    instruction_patterns = len(_INSTRUCTION_PATTERN.findall(all_text))
    instruction_extracted = sum(1 for q in questions if q.instructions)
    report.instruction_patterns_found = instruction_patterns
    report.instruction_extracted = instruction_extracted

    if instruction_patterns > 0 and instruction_extracted == 0:
        report.items.append(CoverageItem(
            category="instructions",
            question_number="",
            description=f"문서에서 {instruction_patterns}개의 지시문(SHOW CARD, ROTATE 등)이 감지되었으나 추출된 것이 없습니다.",
        ))

    return report
