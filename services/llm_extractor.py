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

_GEMINI_MODELS = {'gemini-2.5-flash', 'gemini-2.5-pro'}


def _is_gemini(model: str) -> bool:
    return model in _GEMINI_MODELS

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


# 문항번호가 아닌 것으로 알려진 접두어 (프로세스/메타데이터)
_NON_QUESTION_PREFIXES = {
    'STEP', 'Step', 'PAGE', 'Page', 'ITEM', 'Item',
    'NOTE', 'Note', 'PART', 'Part',
}


def _is_valid_question_number(qn: str) -> bool:
    """문항번호가 실제 설문 문항인지 휴리스틱 검증.

    False positive 방지:
    - RegionCode2, SegCode15 → camelCase / 긴 접두어 → 변수명
    - STEP1, PAGE2 → 프로세스/메타데이터 접두어
    """
    prefix_match = re.match(r'^[A-Za-z]+', qn)
    if not prefix_match:
        return False
    alpha = prefix_match.group()

    # 1) 접두어 5자 초과 → 변수명일 가능성 (RegionCode, SegCode 등)
    if len(alpha) > 5:
        return False

    # 2) camelCase 감지 (소문자→대문자: RegionCode, SegCode)
    if re.search(r'[a-z][A-Z]', alpha):
        return False

    # 3) 비문항 접두어 차단 (STEP, PAGE, ITEM 등)
    if alpha in _NON_QUESTION_PREFIXES:
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


def regex_pre_extract(annotated_text: str) -> List[dict]:
    """정규식으로 문항번호와 유형을 빠르게 사전 추출.

    패턴 A: Q1. question text (마침표/괄호/콜론)
    패턴 B: Q2 [S] question text (공백+대괄호)
    패턴 C: [SC2. SENSITIVE INDUSTRY (MA)] (대괄호 헤더)

    Returns:
        [{"question_number": "Q1", "question_text": "...", "question_type": "SA"}, ...]
    """
    results = []
    lines = annotated_text.split('\n')

    current_qn = None
    current_text = ""
    current_type = None

    for line in lines:
        matched = _try_match_question(line)
        if matched:
            # 이전 문항 저장
            if current_qn:
                cleaned, qtype = _extract_type_from_text(current_text)
                results.append({
                    "question_number": current_qn,
                    "question_text": cleaned.strip(),
                    "question_type": current_type or qtype,
                })
            current_qn, current_text, current_type = matched
        elif current_qn:
            # 문항 텍스트 이어붙이기 (목록 항목이나 빈 줄이 아닌 경우)
            stripped = line.strip()
            if stripped and not stripped.startswith('===') and not stripped.startswith('|'):
                # 목록 항목이면 문항 텍스트에 추가하지 않음 (보기일 가능성)
                if stripped.startswith('#.') or stripped.startswith('- ') or stripped.startswith('  '):
                    pass
                else:
                    current_text += " " + stripped

    # 마지막 문항
    if current_qn:
        cleaned, qtype = _extract_type_from_text(current_text)
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

Survey questionnaires use many different formatting conventions. You MUST recognize ALL of these:

FORMAT A - Standard numbered:
  "Q1. What is your gender?" or "Q1) What is your gender? [SA]"
  The question number ends with a period, closing parenthesis, or colon.

FORMAT B - Bold header with label:
  "**SQ1.\t[Gender]**"
  "[SA]"
  "What is your gender?"
  The question number is bold. The label is in brackets. The type and question text may be on subsequent lines.

FORMAT C - Bracket header:
  "[SC2. SENSITIVE INDUSTRY (MA)]"
  "[PN: ASK ALL]"
  "Do you or any of your family members work in..."
  | 1 | Advertising |
  | 2 | Market research |
  The entire header is in square brackets. (MA)/(SA) at the end indicates the type. The answer options may follow as a table.

FORMAT D - Space-bracket type:
  "Q2 [S]" or "QPID100 [S]" or "BVT11 [MA]"
  No period after the number. The type is in brackets after a space.

FORMAT E - No number (section-based):
  Section headings serve as groupings. Questions may appear as plain text with answer tables below them.
  If a question has no explicit number, use the section name or nearby context to assign an identifier.

IMPORTANT RULES:
- Tables (markdown | format) that have 2 columns with code/number + label are answer option lists
- Tables with header rows + multiple data rows may be matrix/grid questions
- "[PN: ...]" lines are programmer notes containing filter/routing information
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

For each question, provide ALL of these fields:
1. **question_number**: The question identifier (e.g., "Q1", "SC2", "SQ1a")
2. **question_text**: The question text WITHOUT the number prefix or type brackets
3. **question_type**: SA, MA, OE, NUMERIC, SCALE, RANK, GRID, MATRIX, or original notation (e.g., "5pt x 7", "Top3")
4. **answer_options**: Array of {code, label} for ALL listed answer options
5. **skip_logic**: Array of {condition, target}. From "IF", "Go to", "Skip to", arrows, [PN: ...]
6. **filter**: Who answers this question. From "ASK IF", "ONLY IF", "모두에게", "[PN: ...]"
7. **response_base**: Response instruction (e.g., "Select one", "하나만 선택")
8. **instructions**: Interviewer notes (e.g., "SHOW CARD", "ROTATE", "보기 로테이션")

OUTPUT: Return ONLY valid JSON (no markdown code blocks):
{
  "questions": [
    {
      "question_number": "string",
      "question_text": "string",
      "question_type": "string or null",
      "answer_options": [{"code": "string", "label": "string"}],
      "skip_logic": [{"condition": "string", "target": "string"}],
      "filter": "string or null",
      "response_base": "string or null",
      "instructions": "string or null"
    }
  ]
}

Use [] for empty arrays, null for empty strings. Do NOT wrap in code blocks."""


def _build_prompt(chunk_text: str, chunk_index: int, total_chunks: int) -> str:
    """LLM 전면 추출 프롬프트 생성 — 정규식 힌트 없이 LLM이 단독 식별"""
    context = ""
    if total_chunks > 1:
        context = f"\n[Section {chunk_index + 1} of {total_chunks}]\n"

    return f"""Extract ALL survey questions from this questionnaire document.{context}

Identify questions directly from the text content. Use your understanding of survey structure
to distinguish actual questions asked to respondents from administrative metadata.

---BEGIN QUESTIONNAIRE CONTENT---
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
    """추출된 문항 유효성 검증 및 정규화"""
    if not isinstance(q, dict):
        return None

    qn = str(q.get("question_number", "")).strip()
    qt = str(q.get("question_text", "")).strip()
    if not qn or not qt:
        return None

    # Layer 3 안전망: LLM이 비문항 항목을 추출했을 때 걸러냄
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
        "response_base": q.get("response_base") or None,
        "instructions": q.get("instructions") or None,
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

    # "5점 척도 x 3", "5점척도x3" → "5pt x 3"
    m = re.match(r'(\d+)\s*점\s*척도?\s*x\s*(\d+)', raw, re.IGNORECASE)
    if m:
        return f"{m.group(1)}pt x {m.group(2)}"

    # "5점 척도", "5점척도", "5점" → "5pt"
    m = re.match(r'^(\d+)\s*점\s*척도?$', raw)
    if m:
        return f"{m.group(1)}pt"

    # ── 5. 동의어 매핑 ──
    if '단수' in lower or 'single' in lower or 'select one' in lower:
        return 'SA'
    if '복수' in lower or 'multiple' in lower or 'select all' in lower:
        return 'MA'
    if '주관' in lower or ('open' in lower and 'open/sa' not in lower):
        return 'OE'
    if lower == 'open/sa':
        return 'OE'
    if 'numeric' in lower or '숫자' in lower:
        return 'NUMERIC'
    if 'rating' in lower or 'likert' in lower or '척도' in lower:
        return 'SCALE'
    if '순위' in lower:
        return 'RANK'
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
    """Vertex AI Gemini API 호출. Returns: (raw_content, finish_reason)"""
    from vertexai.generative_models import GenerativeModel, GenerationConfig

    gemini = GenerativeModel(model, system_instruction=system_prompt)

    gen_config = GenerationConfig(
        temperature=llm_kwargs.get("temperature", 0.1),
        top_p=llm_kwargs.get("top_p", 0.9),
        max_output_tokens=llm_kwargs.get("max_tokens", 65536),
        response_mime_type="application/json",
    )

    response = gemini.generate_content(user_prompt, generation_config=gen_config)

    finish_reason = None
    if response.candidates and response.candidates[0].finish_reason:
        fr = response.candidates[0].finish_reason
        # Vertex AI uses enum (e.g., FinishReason.MAX_TOKENS)
        finish_reason = fr.name if hasattr(fr, 'name') else str(fr)
        if finish_reason == 'MAX_TOKENS':
            finish_reason = 'length'

    return response.text.strip(), finish_reason


def extract_questions_from_chunk(
    client: Any,
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    model: str = "gemini-2.5-pro",
    pre_extracted: Optional[List[dict]] = None,
) -> List[dict]:
    """LLM 전면 추출 — 정규식 힌트 없이 LLM이 단독으로 문항 식별"""
    user_prompt = _build_prompt(chunk_text, chunk_index, total_chunks)
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

        questions = parsed.get("questions", [])
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
        return []


# ──────────────────────────────────────────────────────────────────────
# 결과 병합
# ──────────────────────────────────────────────────────────────────────

def merge_chunk_results(chunk_results: List[List[dict]]) -> List[dict]:
    """여러 청크 결과를 병합하고 중복 제거"""
    seen = {}
    merged = []

    for chunk_questions in chunk_results:
        for q in chunk_questions:
            qn = q["question_number"]
            if qn in seen:
                existing = seen[qn]
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

                for field in ("filter", "response_base", "instructions", "question_type"):
                    if not existing.get(field) and q.get(field):
                        existing[field] = q[field]
            else:
                seen[qn] = q
                merged.append(q)

    return merged


# ──────────────────────────────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────────────────────────────

def _max_questions_for_model(model: str) -> int:
    """모델별 청크당 최대 문항 수.

    각 문항 JSON ≈ 100 토큰.
    Gemini: 65K 출력 → 안전하게 400문항 (40K), 대부분 재청킹 불필요
    기타: 16K 출력 → 80문항
    """
    if _is_gemini(model):
        return 400
    return 80


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

    # 2단계: LLM 전면 추출 (병렬)
    if total_chunks == 1:
        _notify("chunk_start", {
            "chunk_index": 0, "total_chunks": 1,
            "regex_hints": len(pre_extracted_per_chunk[0]),
        })
        result = extract_questions_from_chunk(
            client, chunks[0], 0, 1, model, pre_extracted_per_chunk[0]
        )
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
                client, chunks[idx], idx, total_chunks, model, pre_extracted_per_chunk[idx]
            )

        with ThreadPoolExecutor(max_workers=min(total_chunks, 4)) as executor:
            futures = {executor.submit(_extract, i): i for i in range(total_chunks)}
            for future in as_completed(futures):
                idx, result = future.result()
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

    _notify("merge_done", {"total_questions": len(questions)})

    logger.info(f"LLM-first extraction complete: {len(questions)} questions")
    return questions
