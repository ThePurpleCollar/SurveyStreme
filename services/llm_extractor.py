"""LLM 전면 방식으로 설문지에서 구조화된 데이터를 추출하는 모듈.

LLM이 단독 추출 엔진이며, 정규식은 문항 식별에 사용하지 않음.
- LLM이 전면 추출 ("Extract ALL questions")
- 정규식은 재청킹 밀도 추정용으로만 사용
"""

import json
import re
import logging
from typing import List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from models.survey import SurveyQuestion

def _is_gemini(model: str) -> bool:
    """모델명이 Gemini 계열인지 판별 (llm_client.py와 동일 로직)."""
    return model.startswith("gemini")

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# 정규식 사전 추출 (재청킹 밀도 추정용)
# ──────────────────────────────────────────────────────────────────────

# 문항번호 패턴 A: 기존 마침표/괄호/콜론 종료형
# Q1. question, SQ1a) question, A1-1: question
_QN_PATTERN_A = re.compile(
    r'^(?:\*\*)?'
    r'([A-Za-z]+[a-z]*\d+[a-z]?(?:-\d+)*'
    r'|[A-Za-z]+\d+[A-Za-z]'
    r')'
    r'[.\):]'
    r'\s*(.*)',
    re.MULTILINE
)

# 문항번호 패턴 B: 공백+대괄호형
# Q2 [S], QPID100 [S], BVT11 [S]
_QN_PATTERN_B = re.compile(
    r'^(?:\*\*)?'
    r'([A-Za-z]+[a-z]*\d+[a-z]?(?:-\d+)*'
    r'|[A-Za-z]+\d+[A-Za-z]'
    r')'
    r'\s+\[([^\]]+)\]'
    r'\s*(.*)',
    re.MULTILINE
)

# 문항번호 패턴 C: 대괄호 헤더형
# [SC2. SENSITIVE INDUSTRY (MA)] -> SC2 + MA
_QN_PATTERN_C = re.compile(
    r'^\[([A-Za-z]+\d+[a-z]?)\.?\s+([^\]]*)\]',
    re.MULTILINE
)

# 문항유형 패턴 (괄호/대괄호 안)
_TYPE_PATTERN = re.compile(r'[\[\(]\s*(.*?)\s*[\]\)]')

_TYPE_KEYWORDS_EXACT = {
    'sa', '단수', 'select one', 'ma', '복수', 'select all',
    'oe', 'open', '오픈', 'open/sa', 'numeric'
}
_TYPE_KEYWORDS_PARTIAL = ['scale', 'pt', '척도', 'top', 'rank', '순위']


# 알려진 유효 문항번호 접두어 (화이트리스트 — 휴리스틱 검사 건너뜀)
_VALID_QN_PREFIXES = {
    'Q', 'SQ', 'SC', 'S',           # Standard question prefixes
    'A', 'B', 'C', 'D', 'F',        # Section-based (A1, B2, ...)
    'P', 'T',                         # Product, Tracking
    'QA', 'QB', 'QC', 'QD',         # Question groups
    'BV', 'BVT',                      # Brand value tracking
    'DM', 'DEM',                      # Demographics
    'PR',                              # Product
}

# 비문항 접두어 (블랙리스트 — 항상 거부, 대문자 기준)
_NON_QUESTION_PREFIXES = {
    # Process / routing
    'STEP', 'PAGE', 'GOTO', 'SKIP', 'LOOP',
    # Structural markers
    'PART', 'SECTION', 'BLOCK', 'MODULE',
    # Metadata / informational
    'NOTE', 'ITEM', 'INFO', 'TEXT', 'MSG',
    # Survey flow
    'INTRO', 'END', 'CLOSE', 'THANK',
    # Display / programming logic
    'DISPLAY', 'SHOW', 'HIDE',
    # Sampling / quota
    'QUOTA', 'SAMPLE', 'CELL',
}


def _is_valid_question_number(qn: str) -> bool:
    """문항번호 유효성 검증 — 블랙리스트만 적용하는 느슨한 검증.

    LLM이 식별한 문항번호를 최대한 존중한다.
    영문자 접두어를 강제하지 않으며, 숫자 단독(1.), 한글(문항1) 등도 허용.
    오직 명백한 비문항 키워드(STEP, PAGE, NOTE 등)만 거부한다.
    """
    if not qn:
        return False

    # 블랙리스트: 명백한 비문항 접두어만 거부
    prefix_match = re.match(r'^[A-Za-z]+', qn)
    if prefix_match:
        upper_alpha = prefix_match.group().upper()
        if upper_alpha in _NON_QUESTION_PREFIXES:
            return False
        # camelCase 변수명 패턴 (RegionCode, SegCode 등)만 거부
        alpha = prefix_match.group()
        if len(alpha) > 7 and re.search(r'[a-z][A-Z]', alpha):
            return False

    return True


def _extract_type_from_text(text: str) -> tuple:
    """텍스트에서 문항유형을 추출. Returns: (cleaned_text, question_type)"""
    matches = list(_TYPE_PATTERN.finditer(text))
    for match in reversed(matches):  # 뒤에서부터 검색 (유형은 보통 문항 끝에)
        potential = match.group(1)
        potential_lower = potential.lower().strip()

        # 정확 매칭
        if potential_lower in _TYPE_KEYWORDS_EXACT:
            return text[:match.start()].strip(), potential.strip()

        # 부분 매칭
        for kw in _TYPE_KEYWORDS_PARTIAL:
            if kw in potential_lower:
                return text[:match.start()].strip(), potential.strip()

    return text, None


def _try_match_question(line: str):
    """한 줄에서 문항번호를 패턴 A/B/C 순으로 매칭 시도.

    Returns: (question_number, question_text, question_type) 또는 None
    """
    stripped = line.strip()

    # 패턴 C: 대괄호 헤더형 [SC2. SENSITIVE INDUSTRY (MA)]
    match_c = _QN_PATTERN_C.match(stripped)
    if match_c:
        qn = match_c.group(1)
        if not _is_valid_question_number(qn):
            return None
        rest = match_c.group(2)
        # 괄호 안에서 유형 추출 (MA), (SA) 등
        _, qtype = _extract_type_from_text(rest)
        # 유형 괄호 제거 후 나머지가 텍스트
        text = re.sub(r'\s*\([^)]*\)\s*$', '', rest).strip()
        return qn, text, qtype

    # 패턴 A: 마침표/괄호/콜론 종료형
    match_a = _QN_PATTERN_A.match(stripped)
    if match_a:
        qn = match_a.group(1)
        if not _is_valid_question_number(qn):
            return None
        return qn, match_a.group(2), None

    # 패턴 B: 공백+대괄호형 Q2 [S]
    match_b = _QN_PATTERN_B.match(stripped)
    if match_b:
        qn = match_b.group(1)
        if not _is_valid_question_number(qn):
            return None
        type_hint = match_b.group(2).strip()
        text = match_b.group(3)
        # 대괄호 안의 S, MA, SA 등을 유형으로 취급
        qtype = type_hint if type_hint else None
        return qn, text, qtype

    return None


# 느슨한 밀도 추정용 패턴 — 영어/숫자/한글 + 대괄호 시작 허용
_DENSITY_PATTERN = re.compile(
    r'^\s*(?:\*\*)?\[?'                           # 선택적 대괄호 '[' 시작
    r'([A-Za-z0-9가-힣]+[A-Za-z0-9가-힣\-]*)'   # 영/숫/한 + 하이픈
    r'[.)\]:\s]',                                 # 구분자
    re.MULTILINE,
)

# 렌더링 마커 접두어 — 밀도 추정에서 제외
_MARKER_PREFIXES = frozenset({
    '[TABLE', '[/TABLE', '[SECTION', '[CODING_REF', '[/CODING_REF',
    '[SCALE_HEADER', '[COL_HEADER', '[ROW]', '[TEXTBOX',
})


def regex_pre_extract(annotated_text: str) -> List[dict]:
    """느슨한 정규식으로 문항 수 밀도를 추정.

    이 함수의 목적은 오직 '재청킹(Rechunking)을 위한 대략적 문항 수 추정'이다.
    정확한 추출은 LLM에 전적으로 위임하므로, 여기서는 과소 추정보다 과대 추정이 낫다.

    기존 패턴 A/B/C도 유지하되, 추가로 느슨한 패턴을 적용하여
    숫자 시작(1.), 한글 시작(문항1) 등도 카운트한다.

    Returns:
        [{"question_number": "Q1", "question_text": "...", "question_type": None}, ...]
    """
    results = []
    lines = annotated_text.split('\n')

    current_qn = None
    current_text = ""
    current_type = None

    for line in lines:
        # 기존 패턴 우선 시도
        matched = _try_match_question(line)

        # 기존 패턴 실패 시 느슨한 패턴 폴백
        if not matched:
            stripped = line.strip()
            if stripped:
                m = _DENSITY_PATTERN.match(stripped)
                if m:
                    # 목록 항목, 들여쓰기된 텍스트, 테이블 행은 제외
                    if not (stripped.startswith('#.') or stripped.startswith('- ')
                            or stripped.startswith('|') or stripped.startswith('===')
                            or any(stripped.startswith(p) for p in _MARKER_PREFIXES)):
                        matched = (m.group(1), stripped[m.end():].strip(), None)

        if matched:
            if current_qn:
                try:
                    cleaned, qtype = _extract_type_from_text(current_text)
                except Exception:
                    cleaned, qtype = current_text, None
                results.append({
                    "question_number": current_qn,
                    "question_text": cleaned.strip(),
                    "question_type": current_type or qtype,
                })
            current_qn, current_text, current_type = matched
        elif current_qn:
            stripped = line.strip()
            if stripped and not stripped.startswith('===') and not stripped.startswith('|'):
                if stripped.startswith('#.') or stripped.startswith('- ') or stripped.startswith('  '):
                    pass
                else:
                    current_text += " " + stripped

    # 마지막 문항
    if current_qn:
        try:
            cleaned, qtype = _extract_type_from_text(current_text)
        except Exception:
            cleaned, qtype = current_text, None
        results.append({
            "question_number": current_qn,
            "question_text": cleaned.strip(),
            "question_type": current_type or qtype,
        })

    return results


# ──────────────────────────────────────────────────────────────────────
# LLM 전면 추출
# ──────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a professional survey questionnaire analyst. You extract ALL questions from survey questionnaire documents into structured JSON.

## WHAT IS A SURVEY QUESTION?

A survey question is any text that asks a respondent for input. It consists of:
1. **Question stem** — the text asking for a response
2. **Answer options** — the choices or input fields (may be a list, table, scale, or open-ended)
3. **Question identifier** — a number, code, or label that uniquely identifies the question

CRITICAL RULES on identifiers:
- Identifiers can take ANY form: "Q1", "1.", "문항1", "SQ2a", "SC_3", or even no explicit number at all.
- Do NOT restrict identifiers to English-letter prefixes. Numbers only ("1.", "2."), Korean ("문항1"), or mixed formats are all valid.
- If a question has NO explicit identifier, generate one yourself using the section name or a descriptive keyword (e.g., "SectionA_Q1", "BrandAwareness"). Generated IDs must be unique within the document.

## WHAT IS NOT A QUESTION?

Do NOT extract these items:
- Plain instructions or introductions ("Welcome to this survey", "다음은 브랜드에 관한 질문입니다")
- Interviewer directives (SHOW CARD, ROTATE) — these go into the `instructions` field of the associated question
- Programmer notes ([PN: ASK IF ...]) — these go into `filter` or `skip_logic` of the associated question
- Variable/coding declarations (RegionCode, SegCode, BrandCode) — data processing metadata
- Process steps (STEP1, STEP2, GOTO, SKIP) — routing instructions
- Section markers, page breaks, quota tables

## GRID/MATRIX QUESTIONS

Multiple items rated on a common scale or sharing the same answer set:
- **Grid (scale)**: Items as rows, scale points (1-5, 1-7, etc.) as columns → type: "Npt x M" (N=scale, M=items)
- **Matrix (non-scale)**: Items as rows, categorical answers as columns → type: "MATRIX"
- Extract row items as `sub_items`, scale columns as `answer_options`

## TABLE RECOGNITION

Tables in the document serve different purposes — identify by content:
- 2-column (code + label) → answer options for the preceding question
- Multi-column with numbered headers → grid/scale battery
- Multi-column with text headers → non-scale matrix

SKIP LOGIC — EXTRACTION RULES:
Extract routing/branching instructions as {condition, target} pairs.

  Source 1 — Explicit goto/skip after answer options:
    Q1. Do you own a car? [SA]
    | 1 | Yes |
    | 2 | No → Go to Q5 |
    → skip_logic: [{"condition":"Q1=2","target":"Q5"}]

  Source 2 — [PN: ...] programmer notes with routing:
    [PN: IF Q1=1 GO TO Q2, ELSE GO TO Q5]
    → skip_logic: [{"condition":"Q1=1","target":"Q2"}, {"condition":"Q1!=1","target":"Q5"}]

  Source 3 — Arrow notation or inline skip:
    Q3. Which brand? [SA]
    1. Brand A
    2. Brand B
    3. None of the above ──→ Skip to Q10
    → skip_logic: [{"condition":"Q3=3","target":"Q10"}]

  Source 4 — Conditional blocks:
    "IF Q2=1,2: ASK Q3-Q7. IF Q2=3: SKIP TO Q8"
    → On Q2: skip_logic: [{"condition":"Q2=3","target":"Q8"}]

  Condition format rules:
  - Use "QN=code" for single code: "Q1=1"
  - Use "QN=code1,code2" for multiple codes (OR): "Q1=1,2"
  - Use "QN!=code" for exclusion: "Q3!=99"
  - Use "&" for AND conditions: "Q1=1&Q3!=99"
  - Preserve the original question number format (e.g., "SQ1a", "SC2", "BVT11")

FILTER CONDITION — EXTRACTION RULES:
Extract WHO should answer each question. Filter appears BEFORE or AT the question.

  Source 1 — [PN: ASK IF ...] programmer notes:
    [PN: ASK IF Q1=1 OR Q1=2]
    Q2. What type of car do you own?
    → filter: "Q1=1,2"

  Source 2 — "ASK IF" / "ONLY IF" / "ASK ALL" text:
    ASK IF Q3=1 AND Q5!=99
    Q6. How often do you use this product?
    → filter: "Q3=1&Q5!=99"

  Source 3 — "모두에게" / "전원 응답" (Korean: ask all):
    모두에게 질문
    Q1. What is your gender?
    → filter: "All respondents"

  Source 4 — Inline filter in question header:
    [SC2. SENSITIVE INDUSTRY (MA)] [PN: ASK ALL]
    → filter: "All respondents"

  Source 5 — Implicit from previous skip logic:
    If Q1 skip_logic says "Q1=2 → Q5", then Q2, Q3, Q4 implicitly have filter "Q1=1".
    But ONLY extract EXPLICIT filter text. Do NOT infer implicit filters.

  Filter format rules:
  - Use same condition format as skip_logic: "QN=code", "QN=code1,code2", "&" for AND
  - "ASK ALL" / "모두에게" → "All respondents"
  - Preserve the exact question numbers referenced in the filter text
  - If no explicit filter text is found, set filter to null (do NOT guess)

IMPORTANT RULES:
- "[PN: ...]" lines are programmer notes containing filter/routing information — extract into skip_logic AND/OR filter
- "ASK IF", "ASK ALL", "ONLY IF" indicate filter conditions
- "ROTATE", "RANDOMIZE", "SHOW CARD" are interviewer instructions
- Even if pattern matching found 0 questions, extract ALL questions from the raw text
- Questions without explicit numbers should still be extracted - use section name or context as identifier

DO NOT EXTRACT these non-question items:
- Coding/variable definitions: RegionCode1, SegCode1, BrandCode1, CategoryCode1, etc.
  (identifiers with camelCase or long descriptive prefixes followed by numbers)
- Process/routing steps: STEP1, STEP2, STEP3 (allocation/sampling procedures)
- Section/page markers: PAGE1, PART1, Section1
- Data processing instructions, quota tables, or respondent allocation rules
These are administrative/metadata elements, NOT survey questions asked to respondents.

RENDERING MARKERS — Special annotations in document text:
- [SECTION: TEXT] = Section boundary. NOT a question.
- [TABLE:grid] [SCALE_HEADER] N | N ... [ROW] item [/TABLE]:
  Scale battery. STEM before the table = question_text.
  SCALE_HEADER count → question_type (e.g., "5pt x N").
  ROW items → sub_items list.
- [TABLE:matrix] [COL_HEADER] ... [ROW] item [/TABLE]:
  Non-scale matrix. COL_HEADER → answer_options, ROW items → sub_items.
- [TABLE:options]...[/TABLE] = Answer options for preceding question.
- [TABLE:multi_question ...]: Each DATA ROW is a separate question.
- [TABLE:info]: Informational. NOT a question.
- [CODING_REF]...[/CODING_REF]: Variable/coding reference table. NOT answer options.
  Do NOT extract these as answer_options. These are data processing specs.
- [TEXTBOX: TEXT] = Text box content (interviewer instructions, programmer notes, filters).

Annotation conventions in the text:
- **bold text** = emphasis, question headers
- "#. " or "- " prefix = list items (often answer options)
- [style:HeadingN] = section headings
- [CAPS]TEXT[/CAPS] = ALL CAPS text (often interviewer instructions)
- Tables in markdown format with | delimiters
- "=== Title ===" = section headings

QUESTION TYPE — OUTPUT FORMAT RULES:
Always output question_type in one of these exact formats:

• "SA" — Single answer (one selection only)
  Clues: [SA], [S], "Select one", "하나만 선택", binary (Yes/No, Male/Female)

• "MA" — Multiple answer (multiple selections)
  Clues: [MA], [M], "Select all that apply", "해당하는 것을 모두 선택", "복수"

• "OE" — Open-ended text
  Clues: no predefined code-label options, blank line, "Please specify", "기입"

• "NUMERIC" — Numeric input only
  Clues: age/amount/count entry, "____세", "____원", numeric validation

• "Npt" — N-point rating scale (single item)
  Count the scale endpoints to determine N. Examples:
  - Scale 1–5 → "5pt"
  - Scale 1–7 → "7pt"
  - Scale 0–10 → "11pt"
  Clues: "1=전혀 아니다 ~ 5=매우 그렇다", numbered scale anchors, Likert-type

• "Npt x M" — Grid/matrix scale (N-point scale applied to M items/rows)
  Same N logic as above, M = number of items rated on that scale. Examples:
  - 5-point scale for 3 brand attributes → "5pt x 3"
  - 7-point satisfaction for 8 items → "7pt x 8"
  Clues: table with items as rows and scale points as columns, "각 항목에 대해 평가"

• "TopN" — Ranking question (select and rank top N)
  Examples: "Top3", "Top5"
  Clues: "순위를 매겨주세요", "가장 ~한 것부터 N개", "1순위/2순위/3순위"

• "MATRIX" — Non-scale grid (same SA/MA answer set for multiple sub-questions)
  Clues: multiple items sharing identical non-scale answer options

• null — Cannot determine type

CRITICAL:
- For scales/grids, ALWAYS include the point count N. Never output just "SCALE" or "GRID".
- For rankings, ALWAYS include the rank count. Never output just "RANK".
- If unsure about N, count the answer option codes (e.g., 5 options labeled 1-5 → 5pt).

ANSWER OPTIONS — EXTRACTION RULES:
Extract answer_options as {code, label} pairs from these sources (in priority order):

  Source 1 — 2-column table (code + label) directly after a question:
    Q1. What is your gender? [SA]
    | 1 | Male |
    | 2 | Female |
    | 99 | Prefer not to say |
    → answer_options: [{"code":"1","label":"Male"}, {"code":"2","label":"Female"}, {"code":"99","label":"Prefer not to say"}]

  Source 2 — Numbered list items (#. or "N." or "N)" prefix):
    Q2. Which brands have you heard of? [MA]
      #. Samsung
      #. Apple
      #. LG
      #. Sony
    → answer_options: [{"code":"1","label":"Samsung"}, {"code":"2","label":"Apple"}, {"code":"3","label":"LG"}, {"code":"4","label":"Sony"}]
    Use sequential numbering (1, 2, 3...) as codes when list items don't have explicit codes.

  Source 3 — Inline code=label pairs (scale anchors):
    "1=전혀 아니다, 2=그렇지 않다, 3=보통, 4=그렇다, 5=매우 그렇다"
    or "1=Strongly disagree ... 5=Strongly agree"
    → answer_options: [{"code":"1","label":"전혀 아니다"}, ..., {"code":"5","label":"매우 그렇다"}]

  Source 4 — Bulleted list items (- prefix):
    - Product quality
    - Price competitiveness
    - Brand reputation
    → answer_options: [{"code":"1","label":"Product quality"}, {"code":"2","label":"Price competitiveness"}, {"code":"3","label":"Brand reputation"}]
    Assign sequential codes when bullet items have no explicit codes.

  Source 5 — "Code. Label" pattern in text:
    1. Very satisfied
    2. Somewhat satisfied
    3. Neither satisfied nor dissatisfied
    4. Somewhat dissatisfied
    5. Very dissatisfied
    → answer_options: [{"code":"1","label":"Very satisfied"}, ..., {"code":"5","label":"Very dissatisfied"}]

  CRITICAL RULES for answer_options:
  - ALWAYS extract ALL options listed. Missing even one option degrades data quality.
  - For grid/matrix questions, extract the SCALE COLUMNS as answer_options (not the row items).
    Example: 5pt grid → answer_options = [{code:"1",label:"Very Poor"}, ..., {code:"5",label:"Very Good"}]
  - Row items in a grid are part of the question structure, not answer_options.
  - Do NOT include interviewer instructions (SHOW CARD, ROTATE) as answer options.
  - Do NOT include "Don't know" / "Refused" / "N/A" codes UNLESS they appear in the official code list.
  - If a question clearly has response options but you cannot determine exact codes, use sequential numbers.
  - For SA/MA questions with NO visible options (e.g., "Select from list on screen"), use empty array [].

For each question, provide ALL of these fields:
1. **question_number**: The question identifier (e.g., "Q1", "SC2", "SQ1a")
2. **question_text**: The question text WITHOUT the number prefix or type brackets
3. **question_type**: SA, MA, OE, NUMERIC, SCALE, RANK, GRID, MATRIX, or original notation (e.g., "5pt x 7", "Top3")
4. **answer_options**: Array of {code, label} for ALL listed answer options (see ANSWER OPTIONS rules above)
5. **skip_logic**: Array of {condition, target}. From "IF", "Go to", "Skip to", arrows, [PN: ...]
6. **filter**: Who answers this question. From "ASK IF", "ONLY IF", "모두에게", "[PN: ...]"
7. **instructions**: Interviewer notes (e.g., "SHOW CARD", "ROTATE", "보기 로테이션")

OUTPUT: Return ONLY valid JSON matching this exact structure. Do NOT include markdown code blocks.

EXAMPLE with 3 question types (SA, Grid, OE):

{
  "questions": [
    {
      "question_number": "DE1",
      "question_text": "How would you describe the area where you live?",
      "question_type": "SA",
      "answer_options": [
        {"code": "1", "label": "Urban"},
        {"code": "2", "label": "Suburban"},
        {"code": "3", "label": "Rural"}
      ],
      "sub_items": [],
      "skip_logic": [{"condition": "DE1=3", "target": "DE5"}],
      "filter": "All respondents",
      "instructions": "DO NOT ROTATE",
      "programming_guide": {
        "rotate_options": false,
        "exclusive_codes": [],
        "dk_codes": [],
        "na_codes": ["99"],
        "pipe_from": null,
        "constant_sum_total": null,
        "rank_limit": null,
        "anchor_labels": {},
        "raw_notes": null
      }
    },
    {
      "question_number": "Q5",
      "question_text": "Please rate each brand on the following attributes.",
      "question_type": "5pt x 3",
      "answer_options": [
        {"code": "1", "label": "Very Poor"},
        {"code": "2", "label": "Poor"},
        {"code": "3", "label": "Average"},
        {"code": "4", "label": "Good"},
        {"code": "5", "label": "Very Good"}
      ],
      "sub_items": ["Brand awareness", "Product quality", "Value for money"],
      "skip_logic": [],
      "filter": "Q1=1,2",
      "instructions": "SHOW CARD B. ROTATE ITEMS",
      "programming_guide": {
        "rotate_options": true,
        "exclusive_codes": [],
        "dk_codes": [],
        "na_codes": [],
        "pipe_from": null,
        "constant_sum_total": null,
        "rank_limit": null,
        "anchor_labels": {"1": "Very Poor", "5": "Very Good"},
        "raw_notes": null
      }
    },
    {
      "question_number": "Q10",
      "question_text": "Is there anything else you would like to tell us?",
      "question_type": "OE",
      "answer_options": [],
      "sub_items": [],
      "skip_logic": [],
      "filter": null,
      "instructions": null,
      "programming_guide": null
    }
  ]
}

RULES:
- Use [] for empty arrays, null for missing/undetectable values.
- programming_guide: populate ONLY fields you can detect. If none, set to null.
- sub_items: for GRID/MATRIX questions only (battery row items). Empty [] for others.
- question_number: use whatever identifier appears in the document. If none, generate a unique one."""


def _build_chunk_context(
    chunk_index: int,
    total_chunks: int,
    all_pre_extracted: List[List[dict]],
    chunks: List[str],
) -> str:
    """청크 간 컨텍스트 생성 — 다른 청크의 정규식 사전 추출 결과 요약.

    Args:
        chunk_index: 현재 청크 인덱스
        total_chunks: 전체 청크 수
        all_pre_extracted: 모든 청크의 정규식 사전 추출 결과
        chunks: 모든 청크 텍스트 (이전 청크 말미 추출용)

    Returns:
        컨텍스트 문자열 (비어있을 수 있음)
    """
    if total_chunks <= 1:
        return ""

    parts = []

    # 다른 청크의 문항번호 요약
    other_questions = []
    for i, pre in enumerate(all_pre_extracted):
        if i == chunk_index:
            continue
        qnums = [q["question_number"] for q in pre]
        if qnums:
            label = "previous" if i < chunk_index else "later"
            other_questions.append(f"  Section {i + 1} ({label}): {', '.join(qnums)}")

    if other_questions:
        parts.append("KNOWN QUESTIONS IN OTHER SECTIONS:\n" + "\n".join(other_questions))

    # 이전 청크의 마지막 ~500자 (경계 문항 연속성)
    if chunk_index > 0:
        prev_text = chunks[chunk_index - 1]
        tail = prev_text[-500:] if len(prev_text) > 500 else prev_text
        # 첫 번째 줄바꿈에서 잘라 불완전한 줄 제거
        newline_idx = tail.find('\n')
        if newline_idx > 0:
            tail = tail[newline_idx + 1:]
        parts.append(f"END OF PREVIOUS SECTION (for continuity):\n{tail}")

    return "\n\n".join(parts)


def _build_prompt(
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    chunk_context: str = "",
) -> str:
    """LLM 전면 추출 프롬프트 생성 — 정규식 힌트 없이 LLM이 단독 식별"""
    section_info = ""
    if total_chunks > 1:
        section_info = f"\n[Section {chunk_index + 1} of {total_chunks}]\n"

    context_block = ""
    if chunk_context:
        context_block = f"""
---DOCUMENT CONTEXT---
{chunk_context}
---END CONTEXT---

Use the context above to understand question numbering patterns and avoid duplicating
questions from other sections. Focus on extracting questions that belong to THIS section.

"""

    return f"""Extract ALL survey questions from this questionnaire document.{section_info}

Identify questions directly from the text content. Use your understanding of survey structure
to distinguish actual questions asked to respondents from administrative metadata.
{context_block}---BEGIN QUESTIONNAIRE CONTENT---
{chunk_text}
---END QUESTIONNAIRE CONTENT---

Extract every question with complete structured data (answer_options, skip_logic, filter, etc.)."""


def _get_llm_kwargs(model: str) -> dict:
    """모델별 LLM 파라미터"""
    if _is_gemini(model):
        # Gemini 2.5: 65K max output, JSON은 Vertex AI에서 mime_type으로 처리
        return {
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": 65536,
        }
    elif "gpt" in model.lower():
        # GPT-4o: 16K max output
        return {
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": 16384,
            "response_format": {"type": "json_object"},
        }
    else:
        # Claude 등: JSON mode 미지원, 프롬프트에서 JSON 요청
        return {
            "temperature": 0.1,
            "top_p": 0.9,
            "max_tokens": 16384,
        }


def _extract_json_from_text(text: str) -> Optional[dict]:
    """텍스트에서 JSON 추출 (fallback)"""
    code_block = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass

    first = text.find('{')
    last = text.rfind('}')
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except json.JSONDecodeError:
            pass

    return None


def _validate_question(q: dict) -> Optional[dict]:
    """추출된 문항 유효성 검증 및 정규화.

    LLM이 반환한 결과를 최대한 존중한다.
    question_text가 존재하면 유효한 문항으로 취급.
    question_number 형태(숫자, 한글, 생성된 ID)와 무관하게 통과.
    오직 명백한 비문항 키워드(STEP, PAGE 등)만 거부.
    """
    if not isinstance(q, dict):
        return None

    qn = str(q.get("question_number", "")).strip()
    qt = str(q.get("question_text", "")).strip()

    # question_text가 없으면 문항이 아님
    if not qt:
        return None

    # question_number가 비어있으면 LLM이 생성하지 못한 것 → 텍스트 기반 임시 ID
    if not qn:
        qn = f"_AUTO_{hash(qt) % 10000:04d}"

    # 블랙리스트만 적용 — 명백한 비문항만 거부
    if not _is_valid_question_number(qn):
        logger.debug(f"Rejected non-question identifier: {qn}")
        return None

    options = q.get("answer_options", [])
    if not isinstance(options, list):
        options = []
    normalized_options = []
    for opt in options:
        if isinstance(opt, dict) and "label" in opt:
            normalized_options.append({
                "code": str(opt.get("code", "")),
                "label": str(opt["label"])
            })

    skip_logic = q.get("skip_logic", [])
    if not isinstance(skip_logic, list):
        skip_logic = []
    normalized_logic = []
    for sl in skip_logic:
        if isinstance(sl, dict) and ("condition" in sl or "target" in sl):
            normalized_logic.append({
                "condition": str(sl.get("condition", "")),
                "target": str(sl.get("target", ""))
            })

    return {
        "question_number": qn,
        "question_text": qt,
        "question_type": _normalize_question_type(q.get("question_type")),
        "answer_options": normalized_options,
        "skip_logic": normalized_logic,
        "filter": q.get("filter") or None,
        "instructions": q.get("instructions") or None,
        "sub_items": q.get("sub_items", []),
        "programming_guide": q.get("programming_guide"),
    }


def _normalize_question_type(raw_type) -> Optional[str]:
    """question_type 정규화 — LLM 비표준 출력 안전망"""
    if not raw_type:
        return None
    raw = str(raw_type).strip()
    if not raw:
        return None

    # ── 1. 상세 형식 보존 (downstream SummaryType 계산에 필요) ──
    # "5pt x 3", "7pt x 8" (grid scale)
    m = re.match(r'^(\d+)\s*pt\s*x\s*(\d+)$', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt x {m.group(2)}"

    # "5pt", "7pt" (simple scale)
    m = re.match(r'^(\d+)\s*pt$', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt"

    # "Top3", "Top 3", "Rank3", "Rank 3"
    m = re.match(r'^(top|rank)\s*(\d+)$', raw, re.IGNORECASE)
    if m:
        return f"Top{m.group(2)}"

    # "3순위", "3 순위"
    m = re.match(r'^(\d+)\s*순위$', raw)
    if m:
        return f"Top{m.group(1)}"

    # ── 2. 표준 유형 정확 매칭 ──
    standard_types = ['SA', 'MA', 'OE', 'NUMERIC', 'SCALE', 'RANK', 'GRID', 'MATRIX']
    if raw.upper() in standard_types:
        return raw.upper()

    # ── 3. 단일 문자 약어 ──
    upper = raw.upper()
    if upper == 'S':
        return 'SA'
    if upper == 'M':
        return 'MA'
    if upper == 'O':
        return 'OE'

    # ── 4. 변형 패턴 → 상세 형식으로 변환 ──
    lower = raw.lower()

    # "5-point scale x 3" → "5pt x 3"
    m = re.match(r'(\d+)\s*-?\s*point\s*(?:scale)?\s*x\s*(\d+)', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt x {m.group(2)}"

    # "5-point scale", "5-point" → "5pt"
    m = re.match(r'(\d+)\s*-?\s*point(?:\s*scale)?$', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt"

    # "5점 척도 x 3", "5점척도x3", "5점 x 3" → "5pt x 3"
    m = re.match(r'(\d+)\s*점\s*(?:척도?)?\s*x\s*(\d+)', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt x {m.group(2)}"

    # "5점 척도", "5점척도", "5점" → "5pt"
    m = re.match(r'^(\d+)\s*점\s*(?:척도?)?$', raw)
    if m:
        return f"{m.group(1)}pt"

    # "5pt scale", "5-pt scale" → "5pt"
    m = re.match(r'^(\d+)\s*-?\s*pt\s+scale$', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt"

    # "scale 1-5", "1-5 scale", "1 to 5", "1-5", "0~10" → range-based scale
    m = re.match(r'^(?:scale\s+)?(\d+)\s*(?:[-–~]|to)\s*(\d+)(?:\s+scale)?$', raw, re.IGNORECASE)
    if m:
        low, high = int(m.group(1)), int(m.group(2))
        if high > low:
            return f"{high - low + 1}pt"

    # "Likert 5", "Likert-5", "Likert-7" → "5pt" / "7pt"
    m = re.match(r'^likert\s*[-:]?\s*(\d+)$', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt"

    # "NPS", "Net Promoter Score" → "11pt" (0–10 scale)
    if lower in ('nps', 'net promoter score', 'net promoter'):
        return '11pt'

    # ── 5. 동의어 매핑 ──
    # SA
    if '단수' in lower or 'single' in lower or 'select one' in lower:
        return 'SA'
    if ('one' in lower or 'single' in lower) and ('choice' in lower or 'select' in lower or 'answer' in lower):
        return 'SA'
    if lower in ('binary', 'yes/no', 'dichotomous', 'boolean'):
        return 'SA'
    if lower in ('dropdown', 'drop-down', 'pull-down', 'pulldown'):
        return 'SA'
    if '객관식' in lower:
        return 'SA'

    # MA
    if '복수' in lower or 'multiple' in lower or 'select all' in lower:
        return 'MA'
    if 'multi' in lower and ('choice' in lower or 'select' in lower or 'response' in lower):
        return 'MA'
    if lower in ('choose all', 'check all', 'pick all'):
        return 'MA'

    # OE
    if '주관' in lower or ('open' in lower and 'open/sa' not in lower):
        return 'OE'
    if lower == 'open/sa':
        return 'OE'
    if 'free text' in lower or 'freetext' in lower or 'verbatim' in lower:
        return 'OE'
    if 'open-end' in lower or 'open end' in lower:
        return 'OE'
    if lower in ('text entry', 'text input', 'essay'):
        return 'OE'
    if '서술형' in lower or '기술형' in lower:
        return 'OE'

    # NUMERIC
    if 'numeric' in lower or '숫자' in lower:
        return 'NUMERIC'
    if 'constant sum' in lower or 'allocation' in lower or '배분' in lower:
        return 'NUMERIC'

    # SCALE
    if 'rating' in lower or 'likert' in lower or '척도' in lower:
        return 'SCALE'
    if lower in ('slider', 'sliding scale'):
        return 'SCALE'

    # RANK
    if '순위' in lower:
        return 'RANK'
    if 'ranking' in lower or 'rank order' in lower:
        return 'RANK'

    # GRID / MATRIX
    if 'grid' in lower:
        return 'GRID'
    if 'matrix' in lower:
        return 'MATRIX'

    return raw  # 원본 유지


# ──────────────────────────────────────────────────────────────────────
# 청크별 LLM 추출
# ──────────────────────────────────────────────────────────────────────

def _call_openai(client: OpenAI, model: str, system_prompt: str,
                  user_prompt: str, llm_kwargs: dict) -> tuple:
    """OpenAI 호환 API 호출. Returns: (raw_content, finish_reason)"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        **llm_kwargs
    )
    raw_content = response.choices[0].message.content.strip()
    finish_reason = getattr(response.choices[0], 'finish_reason', None)
    return raw_content, finish_reason


def _call_gemini(model: str, system_prompt: str,
                 user_prompt: str, llm_kwargs: dict) -> tuple:
    """Vertex AI Gemini API 호출. 안전 필터 해제로 NDA/PII 문서 차단 방지."""
    from vertexai.generative_models import (
        GenerativeModel, GenerationConfig, HarmCategory, HarmBlockThreshold,
    )

    gemini = GenerativeModel(model, system_instruction=system_prompt)

    gen_config = GenerationConfig(
        temperature=llm_kwargs.get("temperature", 0.1),
        top_p=llm_kwargs.get("top_p", 0.9),
        max_output_tokens=llm_kwargs.get("max_tokens", 65536),
        response_mime_type="application/json",
    )

    # 설문지 분석을 위한 안전 필터 해제 (NDA/PII 텍스트 차단 방지)
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }

    response = gemini.generate_content(
        user_prompt, generation_config=gen_config, safety_settings=safety_settings,
    )

    if not response.candidates:
        raise ValueError("Gemini response blocked or empty (no candidates)")

    finish_reason = None
    if response.candidates[0].finish_reason:
        fr = response.candidates[0].finish_reason
        # Vertex AI uses enum (e.g., FinishReason.MAX_TOKENS)
        finish_reason = fr.name if hasattr(fr, 'name') else str(fr)
        if finish_reason == 'MAX_TOKENS':
            finish_reason = 'length'

    try:
        raw_text = response.text.strip()
    except ValueError:
        block_reason = getattr(response.candidates[0], "finish_reason", "unknown")
        raise ValueError(f"Gemini response blocked (reason: {block_reason})")

    return raw_text, finish_reason


def extract_questions_from_chunk(
    client: Any,
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    model: str = "gemini-2.5-pro",
    pre_extracted: Optional[List[dict]] = None,
    chunk_context: str = "",
) -> List[dict]:
    """LLM 전면 추출 — 정규식 힌트 없이 LLM이 단독으로 문항 식별"""
    user_prompt = _build_prompt(chunk_text, chunk_index, total_chunks, chunk_context)
    llm_kwargs = _get_llm_kwargs(model)

    try:
        if _is_gemini(model):
            raw_content, finish_reason = _call_gemini(
                model, SYSTEM_PROMPT, user_prompt, llm_kwargs)
        else:
            raw_content, finish_reason = _call_openai(
                client, model, SYSTEM_PROMPT, user_prompt, llm_kwargs)

        if finish_reason == 'length':
            logger.warning(f"Chunk {chunk_index}: Response truncated (finish_reason=length)")

        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            parsed = _extract_json_from_text(raw_content)
            if parsed is None:
                logger.error(f"Chunk {chunk_index}: Failed to parse JSON "
                             f"(response length={len(raw_content)}, finish_reason={finish_reason})")
                return []

        # LLM이 {"questions": [...]} 또는 직접 [...] 배열을 반환할 수 있음
        if isinstance(parsed, list):
            questions = parsed
        elif isinstance(parsed, dict):
            questions = parsed.get("questions", [])
        else:
            return []
        if not isinstance(questions, list):
            return []

        validated = [_validate_question(q) for q in questions]
        validated = [q for q in validated if q is not None]

        pre_count = len(pre_extracted) if pre_extracted else 0
        logger.info(f"Chunk {chunk_index}: LLM extracted {len(validated)} questions "
                     f"(regex density estimate: {pre_count})")

        return validated

    except Exception as e:
        logger.error(f"Chunk {chunk_index}: LLM call failed: {e}")
        raise  # 에러를 상위로 전파하여 사용자 알림 가능하게 함


# ──────────────────────────────────────────────────────────────────────
# 결과 병합
# ──────────────────────────────────────────────────────────────────────

def _text_similarity(a: str, b: str) -> float:
    """두 문자열의 간이 유사도 (0.0~1.0). 토큰 기반 Jaccard."""
    if not a or not b:
        return 0.0
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _options_identical(opts_a: list, opts_b: list) -> bool:
    """두 보기 리스트의 label이 동일한지 비교."""
    labels_a = {opt.get("label", "") for opt in opts_a if isinstance(opt, dict)}
    labels_b = {opt.get("label", "") for opt in opts_b if isinstance(opt, dict)}
    if not labels_a and not labels_b:
        return True
    return labels_a == labels_b


def merge_chunk_results(chunk_results: List[List[dict]]) -> List[dict]:
    """여러 청크 결과를 병합하고 중복 제거.

    동일 question_number라도 question_text 유사도가 낮거나
    answer_options가 완전히 다르면 서로 다른 문항으로 보존한다.
    이는 LLM이 번호 없는 문항에 동일한 임시 ID를 부여했을 때
    서로 다른 문항이 덮어씌워지는 것을 방지한다.
    """
    seen = {}      # qn → dict (기존과 동일)
    merged = []

    for chunk_questions in chunk_results:
        if not chunk_questions:
            continue
        for q in chunk_questions:
            qn = q["question_number"]

            if qn in seen:
                existing = seen[qn]
                text_sim = _text_similarity(
                    existing.get("question_text", ""),
                    q.get("question_text", ""),
                )
                opts_same = _options_identical(
                    existing.get("answer_options", []),
                    q.get("answer_options", []),
                )

                # 유사도가 높으면 동일 문항 → 기존 방식으로 보강
                if text_sim > 0.3 or opts_same:
                    if len(q.get("question_text", "")) > len(existing.get("question_text", "")):
                        existing["question_text"] = q["question_text"]

                    existing_codes = {opt["code"] for opt in existing.get("answer_options", [])}
                    for opt in q.get("answer_options", []):
                        if opt["code"] not in existing_codes:
                            existing["answer_options"].append(opt)
                            existing_codes.add(opt["code"])

                    existing_conditions = {sl["condition"] for sl in existing.get("skip_logic", [])}
                    for sl in q.get("skip_logic", []):
                        if sl["condition"] not in existing_conditions:
                            existing["skip_logic"].append(sl)
                            existing_conditions.add(sl["condition"])

                    for field in ("filter", "instructions", "question_type",
                                  "sub_items", "programming_guide"):
                        if not existing.get(field) and q.get(field):
                            existing[field] = q[field]
                else:
                    # 유사도 낮음 → 서로 다른 문항, 번호 충돌 해소
                    new_qn = f"{qn}_dup{len(merged)}"
                    q["question_number"] = new_qn
                    seen[new_qn] = q
                    merged.append(q)
                    logger.info(f"Merge: duplicate ID '{qn}' resolved as '{new_qn}' "
                                f"(text_sim={text_sim:.2f})")
            else:
                seen[qn] = q
                merged.append(q)

    return merged


# ──────────────────────────────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────────────────────────────

def _max_questions_for_model(model: str) -> int:
    """모델별 청크당 최대 문항 수.

    각 문항 JSON ≈ 200-300 토큰 (보기, 스킵, 필터, programming_guide 포함).
    Gemini: 65K 출력 → 안전하게 150문항 (~45K 토큰)
    기타: 16K 출력 → 60문항
    """
    if _is_gemini(model):
        return 150
    return 60


def _rechunk_by_question_count(chunks: List[str], pre_per_chunk: List[List[dict]],
                                max_per_chunk: int) -> tuple:
    """정규식 문항 수 기반 적응형 재청킹.

    청크 내 문항이 max_per_chunk를 초과하면 텍스트를
    문항 경계에서 분할하여 LLM 출력 잘림을 방지합니다.
    """
    new_chunks = []
    new_pre = []

    for chunk_text, pre_questions in zip(chunks, pre_per_chunk):
        if len(pre_questions) <= max_per_chunk:
            new_chunks.append(chunk_text)
            new_pre.append(pre_questions)
            continue

        # 문항이 너무 많음 → 텍스트를 문항 경계에서 분할
        lines = chunk_text.split('\n')
        sub_chunk_lines = []
        question_count = 0

        for line in lines:
            matched = _try_match_question(line)
            if matched and question_count >= max_per_chunk and sub_chunk_lines:
                # 현재 sub-chunk 저장
                sub_text = '\n'.join(sub_chunk_lines)
                new_chunks.append(sub_text)
                new_pre.append(regex_pre_extract(sub_text))
                sub_chunk_lines = []
                question_count = 0

            sub_chunk_lines.append(line)
            if matched:
                question_count += 1

        # 남은 라인
        if sub_chunk_lines:
            sub_text = '\n'.join(sub_chunk_lines)
            new_chunks.append(sub_text)
            new_pre.append(regex_pre_extract(sub_text))

    return new_chunks, new_pre


def extract_survey_questions(
    client: OpenAI,
    chunks: List[str],
    model: str = "gemini-2.5-pro",
    progress_callback=None,
) -> List[SurveyQuestion]:
    """LLM 전면 추출 파이프라인.

    1단계: 정규식 사전 추출 (재청킹 밀도 추정용)
    1-b단계: 청크당 문항이 너무 많으면 재분할 (출력 잘림 방지)
    2단계: LLM이 단독으로 문항 식별 및 추출
    3단계: 결과 병합 및 SurveyQuestion 변환

    Args:
        client: OpenAI 클라이언트
        chunks: 어노테이션 텍스트 청크 리스트
        model: 사용할 모델명
        progress_callback: (event, data) 콜백.
            Events: "regex_done", "rechunk", "chunk_start", "chunk_done", "merge_done"

    Returns:
        SurveyQuestion 리스트
    """
    def _notify(event: str, data: dict):
        if progress_callback:
            progress_callback(event, data)

    # 1단계: 정규식 사전 추출 (재청킹 밀도 추정용)
    pre_extracted_per_chunk = []
    total_pre = 0
    for chunk in chunks:
        pre = regex_pre_extract(chunk)
        pre_extracted_per_chunk.append(pre)
        total_pre += len(pre)

    _notify("regex_done", {"total_hints": total_pre, "chunk_count": len(chunks)})

    # 1-b단계: 문항 수 기반 적응형 재청킹 (모델 출력 한도에 맞춤)
    max_per_chunk = _max_questions_for_model(model)
    max_q = max((len(p) for p in pre_extracted_per_chunk), default=0)
    if max_q > max_per_chunk:
        logger.info(f"Rechunking: max {max_q} questions/chunk > limit {max_per_chunk} ({model})")
        original_count = len(chunks)
        chunks, pre_extracted_per_chunk = _rechunk_by_question_count(
            chunks, pre_extracted_per_chunk, max_per_chunk
        )
        total_pre = sum(len(p) for p in pre_extracted_per_chunk)
        _notify("rechunk", {
            "original_chunks": original_count,
            "new_chunks": len(chunks),
            "reason": f"{max_q} questions > limit {max_per_chunk}",
        })

    total_chunks = len(chunks)
    logger.info(f"Regex hints: {total_pre} questions from {total_chunks} chunks")

    # 1-c단계: 청크 간 컨텍스트 빌드 (정규식 사전 추출 기반, 병렬 유지)
    chunk_contexts = []
    for i in range(total_chunks):
        ctx = _build_chunk_context(i, total_chunks, pre_extracted_per_chunk, chunks)
        chunk_contexts.append(ctx)

    # 2단계: LLM 전면 추출 (병렬)
    if total_chunks == 1:
        _notify("chunk_start", {
            "chunk_index": 0, "total_chunks": 1,
            "regex_hints": len(pre_extracted_per_chunk[0]),
        })
        try:
            result = extract_questions_from_chunk(
                client, chunks[0], 0, 1, model, pre_extracted_per_chunk[0],
                chunk_context=chunk_contexts[0],
            )
        except Exception as e:
            result = []
            _notify("chunk_error", {
                "chunk_index": 0, "total_chunks": 1,
                "error": str(e),
            })
        _notify("chunk_done", {
            "chunk_index": 0, "total_chunks": 1,
            "questions_extracted": len(result),
        })
        chunk_results = [result]
    else:
        chunk_results = [None] * total_chunks

        # 시작 알림 일괄 발행 (병렬 처리 전)
        for i in range(total_chunks):
            _notify("chunk_start", {
                "chunk_index": i, "total_chunks": total_chunks,
                "regex_hints": len(pre_extracted_per_chunk[i]),
            })

        def _extract(idx):
            return idx, extract_questions_from_chunk(
                client, chunks[idx], idx, total_chunks, model,
                pre_extracted_per_chunk[idx],
                chunk_context=chunk_contexts[idx],
            )

        with ThreadPoolExecutor(max_workers=min(total_chunks, 4)) as executor:
            futures = {executor.submit(_extract, i): i for i in range(total_chunks)}
            for future in as_completed(futures):
                try:
                    idx, result = future.result()
                except Exception as e:
                    idx = futures[future]
                    result = []
                    logger.error(f"Chunk {idx} extraction failed: {e}")
                    _notify("chunk_error", {
                        "chunk_index": idx, "total_chunks": total_chunks,
                        "error": str(e),
                    })
                chunk_results[idx] = result
                _notify("chunk_done", {
                    "chunk_index": idx, "total_chunks": total_chunks,
                    "questions_extracted": len(result),
                })

    # 3단계: 병합
    merged = merge_chunk_results(chunk_results)

    questions = []
    for q_dict in merged:
        try:
            sq = SurveyQuestion.from_llm_dict(q_dict)
            questions.append(sq)
        except Exception as e:
            logger.warning(f"Failed to create SurveyQuestion: {q_dict.get('question_number', '?')}: {e}")

    # 3-b단계: 2-pass 검증 — 정규식이 찾았는데 LLM이 놓친 문항 감지
    llm_qns = {q.question_number for q in questions}
    regex_qns = set()
    for pre in pre_extracted_per_chunk:
        for item in pre:
            regex_qns.add(item["question_number"])

    missed = regex_qns - llm_qns
    if missed:
        missed_sorted = sorted(missed)
        logger.warning(f"2-pass check: {len(missed)} questions found by regex but missed by LLM: "
                        f"{', '.join(missed_sorted)}")
        _notify("missed_questions", {
            "count": len(missed),
            "question_numbers": missed_sorted,
        })

    _notify("merge_done", {"total_questions": len(questions), "missed_count": len(missed) if missed else 0})

    logger.info(f"LLM-first extraction complete: {len(questions)} questions"
                f"{f' ({len(missed)} missed vs regex)' if missed else ''}")
    return questions
