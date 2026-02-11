import re
from typing import List, Tuple, Optional

from services.llm_extractor import _is_valid_question_number


def extract_question_type(text, question_type_keywords1, question_type_keywords2):
    """문항 텍스트에서 괄호 안의 문항 유형을 추출"""
    pattern = re.compile(r'(\[\s*(.*?)\s*\]|\(\s*(.*?)\s*\))')
    cleaned_text = text
    question_type = None
    for match in pattern.finditer(text):
        potential_type = match.group(2) or match.group(3)
        if potential_type:
            potential_type_lower = potential_type.lower()
            for keyword in question_type_keywords1:
                if potential_type_lower == keyword.lower():
                    question_type = potential_type.strip()
                    cleaned_text = text[:match.start()].strip()
                    return cleaned_text, question_type
    for match in pattern.finditer(text):
        potential_type = match.group(2) or match.group(3)
        if potential_type and any(keyword.lower() in potential_type.lower() for keyword in question_type_keywords2):
            question_type = potential_type.strip()
            cleaned_text = text[:match.start()].strip()
            break
    return cleaned_text, question_type


# ---------------------------------------------------------------------------
# PDF 문항번호 정규식 패턴 (3-pattern 구조, llm_extractor와 동일 체계)
# ---------------------------------------------------------------------------

# 핵심 문항번호 부분: Q1, SQ1a, Q1-1, Q1_1, BVT11, Q1A
_QN_CORE = (
    r'[A-Za-z]+[a-z]*\d+[a-z]?(?:[-_]\d+)*'
    r'|[A-Za-z]+\d+[A-Za-z]'
)

# Pattern A: 표준 구분자 — Q1. text, SQ1a) text, A1-1: text, Q1_1. text
_PDF_PATTERN_A = re.compile(rf'^({_QN_CORE})\s*[.):]\s*(.*)')

# Pattern B: 공백+대괄호 — Q2 [S] text, QPID100 [S] text
_PDF_PATTERN_B = re.compile(rf'^({_QN_CORE})\s+\[([^\]]+)\]\s*(.*)')

# Pattern C: 대괄호 헤더 — [SC2. SENSITIVE INDUSTRY (MA)]
_PDF_PATTERN_C = re.compile(r'^\[([A-Za-z]+\d+[a-z]?)\.?\s+([^\]]*)\]')


def _match_question_line(line: str) -> Optional[Tuple[str, str]]:
    """라인에서 문항번호 매칭 시도. Returns (qn, rest_text) or None."""
    # Pattern C: 대괄호 헤더 [SC2. ...]
    m = _PDF_PATTERN_C.match(line)
    if m:
        qn = m.group(1)
        if _is_valid_question_number(qn):
            return qn, m.group(2)

    # Pattern A: 표준 구분자 (dot/paren/colon)
    m = _PDF_PATTERN_A.match(line)
    if m:
        qn = m.group(1)
        if _is_valid_question_number(qn):
            return qn, m.group(2)

    # Pattern B: 공백+대괄호 타입 힌트
    m = _PDF_PATTERN_B.match(line)
    if m:
        qn = m.group(1)
        if _is_valid_question_number(qn):
            # 대괄호 내용을 텍스트에 포함하여 extract_question_type이 처리하도록
            bracket = m.group(2)
            rest = m.group(3)
            return qn, f"[{bracket}] {rest}" if rest else f"[{bracket}]"

    return None


def extract_question_data(texts) -> List[Tuple[str, str, Optional[str]]]:
    """텍스트에서 문항 번호, 텍스트, 유형을 추출"""
    question_type_keywords1 = ['SA', '단수', 'SELECT ONE', 'MA', '복수', 'SELECT ALL', 'OE', 'OPEN', '오픈', 'OPEN/SA', 'NUMERIC']
    question_type_keywords2 = ['SCALE', 'PT', '척도', 'TOP', 'RANK', '순위']
    question_data: List[Tuple[str, str, Optional[str]]] = []
    current_question_text = ""
    current_qn: Optional[str] = None
    for text in texts:
        lines = text.split('\n')
        for line in lines:
            result = _match_question_line(line)
            if result:
                if current_qn:
                    cleaned_text, current_qtype = extract_question_type(current_question_text, question_type_keywords1, question_type_keywords2)
                    question_data.append((current_qn, cleaned_text, current_qtype))
                    current_question_text = ""
                current_qn = result[0]
                current_question_text = result[1]
            else:
                current_question_text += " " + line
    if current_qn and current_question_text:
        cleaned_text, current_qtype = extract_question_type(current_question_text, question_type_keywords1, question_type_keywords2)
        question_data.append((current_qn, cleaned_text, current_qtype))
    return question_data


# ---------------------------------------------------------------------------
# SurveyDocument 후처리 (SummaryType / TableNumber)
# ---------------------------------------------------------------------------

_SCALE_MAP = {
    4:  '%/Top2(3+4)/Bot2(1+2)/Mean',
    5:  '%/Top2(4+5)/Mid(3)/Bot2(1+2)/Mean',
    6:  '%/Top2(5+6)/Mid(3+4)/Bot2(1+2)/Mean',
    7:  '%/Top2(6+7)/Mid(3+4+5)/Bot2(1+2)/Top3(5+6+7)/Mid(4)/Bot3(1+2+3)/Mean',
    10: '%/Top2(9+10)/Bot2(1+2)/Top3(8+9+10)/Bot3(1+2+3)/Mean',
}

_STANDARD_MAP = {
    'SA': '%', 'MA': '%', 'OE': '%', 'MATRIX': '%',
    'NUMERIC': '%, mean',
    'SCALE': '%/Top2/Bot2/Mean',
    'GRID': '%/Top2/Bot2/Mean',
    'RANK': '%',
}


def scale_summary_type(n: int) -> str:
    """척도 점수(N)에 따른 SummaryType 결정."""
    return _SCALE_MAP.get(n, '%/Top2/Bot2/Mean')


def apply_postprocessing(survey_doc) -> None:
    """추출된 문항에 SummaryType, TableNumber 등 후처리 적용.

    Parameters
    ----------
    survey_doc : SurveyDocument
        questions 리스트를 in-place로 수정한다.
    """
    # ── TableNumber 할당 ──
    qn_count: dict = {}
    for q in survey_doc.questions:
        qn = q.question_number
        qn_count[qn] = qn_count.get(qn, 0) + 1

    qn_current: dict = {}
    for q in survey_doc.questions:
        qn = q.question_number
        if qn_count[qn] > 1:
            qn_current.setdefault(qn, 0)
            qn_current[qn] += 1
            q.table_number = f"{qn}_{qn_current[qn]}"
        else:
            q.table_number = qn

    # ── SummaryType 할당 (패턴 기반 매핑) ──
    for q in survey_doc.questions:
        if not q.question_type:
            continue

        qtype = q.question_type

        # "Npt x M" (grid scale)
        m = re.match(r'^(\d+)pt\s*x\s*\d+$', qtype, re.IGNORECASE)
        if m:
            q.summary_type = scale_summary_type(int(m.group(1)))
            continue

        # "Npt" (simple scale)
        m = re.match(r'^(\d+)pt$', qtype, re.IGNORECASE)
        if m:
            q.summary_type = scale_summary_type(int(m.group(1)))
            continue

        # "TopN" / "RankN"
        if re.match(r'^(Top|Rank)\s*\d+$', qtype, re.IGNORECASE):
            q.summary_type = '%'
            continue

        # 표준 유형
        upper = qtype.upper()
        if upper in _STANDARD_MAP:
            q.summary_type = _STANDARD_MAP[upper]
            continue
