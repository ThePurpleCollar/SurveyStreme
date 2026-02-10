"""Table Guide Builder 서비스 레이어.

Phase 2: Base Definition + Net/Recode
Phase 3: Banner Management + Sort + SubBanner
Phase 4: Special Instructions + Full Compile + Export
"""

import io
import logging
import re
from datetime import datetime
from typing import List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from models.survey import (
    Banner, BannerPoint, SurveyDocument, SurveyQuestion, TableGuideDocument,
)
from services.llm_client import (
    DEFAULT_MODEL, MODEL_TITLE_GENERATOR, call_llm, call_llm_json,
)

logger = logging.getLogger(__name__)


def _call_llm_json_with_fallback(system_prompt: str, user_prompt: str,
                                  model: str, **kwargs) -> dict:
    """call_llm_json + text-mode 폴백.

    일부 모델/프록시에서 response_format=json_object가 빈 응답을 반환하는 경우
    call_llm(text mode)로 재시도 후 JSON 파싱.
    """
    import json as _json

    try:
        return call_llm_json(system_prompt, user_prompt, model, **kwargs)
    except Exception as e:
        logger.warning(f"call_llm_json failed ({e}), retrying with text mode...")

    # Text-mode fallback
    full_prompt = (
        f"{system_prompt}\n\n"
        "IMPORTANT: Respond with valid JSON only. No markdown code fences, no explanation.\n\n"
        f"{user_prompt}"
    )
    raw = call_llm(full_prompt, model, max_tokens=kwargs.get("max_tokens", 8192))

    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    return _json.loads(text)

# ── 모델 할당 ────────────────────────────────────────────────────
MODEL_INTELLIGENCE = MODEL_TITLE_GENERATOR          # GPT-5 — 깊은 이해력 필요
MODEL_BASE_GENERATOR = DEFAULT_MODEL               # GPT-4.1-mini
MODEL_NET_GENERATOR = DEFAULT_MODEL                # GPT-4.1-mini
MODEL_BANNER_SUGGESTER = DEFAULT_MODEL             # GPT-4.1-mini
MODEL_SUBBANNER_SUGGESTER = DEFAULT_MODEL          # GPT-4.1-mini
MODEL_SPECIAL_INSTRUCTIONS = DEFAULT_MODEL         # GPT-4.1-mini

BATCH_SIZE = 20


# ── 공통 유틸 ──────────────────────────────────────────────────────

def _format_questions_compact(questions: List[SurveyQuestion],
                               include_options: bool = False,
                               max_option_len: int = 150) -> str:
    """문항 리스트를 LLM 프롬프트용 compact 텍스트로 변환.

    Args:
        questions: 문항 리스트
        include_options: 보기를 포함할지 여부
        max_option_len: 보기 텍스트 최대 길이

    Returns:
        포맷된 텍스트 문자열
    """
    seen = set()
    lines = []
    for q in questions:
        if q.question_number in seen:
            continue
        seen.add(q.question_number)

        text = (q.question_text or "").replace("\n", " ")[:100]
        qtype = q.question_type or ""
        filt = f" [Filter: {(q.filter_condition or '')[:50]}]" if q.filter_condition else ""
        line = f"[{q.question_number}] {text} ({qtype})"
        if include_options and q.answer_options:
            opts = q.answer_options_compact()
            if len(opts) > max_option_len:
                opts = opts[:max_option_len] + "..."
            line += f"\n  Options: {opts}"
        if filt:
            line += filt
        lines.append(line)
    return "\n".join(lines)


def _format_questions_full(questions: List[SurveyQuestion]) -> str:
    """선정된 후보 문항의 FULL 상세 정보를 LLM 프롬프트용으로 변환.

    배너 설계 단계에서 보기 코드, 필터, 스킵 로직 등 모든 정보 포함.
    """
    seen = set()
    lines = []
    for q in questions:
        if q.question_number in seen:
            continue
        seen.add(q.question_number)

        lines.append(f"[{q.question_number}]")
        lines.append(f"  Text: {q.question_text}")
        lines.append(f"  Type: {q.question_type or 'SA'}")
        if q.answer_options:
            lines.append(f"  Options: {q.answer_options_compact()}")
        if q.filter_condition:
            lines.append(f"  Filter: {q.filter_condition}")
        if q.skip_logic:
            lines.append(f"  Skip: {q.skip_logic_display()}")
        if q.response_base:
            lines.append(f"  Response Base: {q.response_base}")
        lines.append("")
    return "\n".join(lines)


def _build_code_map(questions: List[SurveyQuestion]) -> dict:
    """문항번호 → 유효 코드 리스트 맵 생성 (검증용).

    Returns:
        dict: {"SQ1": ["1", "2", "3"], "SQ2": ["1", "2", "3", "4"]}
    """
    code_map = {}
    for q in questions:
        if q.question_number not in code_map and q.answer_options:
            code_map[q.question_number] = [opt.code for opt in q.answer_options]
    return code_map


# ======================================================================
# Survey Intelligence Analysis
# ======================================================================

_INTELLIGENCE_SYSTEM_PROMPT = """You are a senior marketing research strategist analyzing a complete survey questionnaire.
Your task is to deeply understand the survey's purpose, client, research framework, and recommend optimal analysis dimensions.

## User-Provided Context
If the user has specified a Client Brand or Study Objective, use these as authoritative ground truth:
- **Client Brand**: The brand commissioning the study. All brand-based segmentation should center on this brand (e.g., "Client Brand Users" vs "Competitor Users"). If not provided, infer from question texts and answer options.
- **Study Objective**: The stated research purpose. Use this to prioritize which analytical dimensions and segments are most relevant. If not provided, infer from the survey flow.

## Analysis Tasks
1. **Client/Brand Identification**: Use the user-provided Client Brand if available. Otherwise extract brand/company names from question texts, answer options, and instructions.
2. **Study Type Classification**: Classify into one of: Brand Tracking, U&A (Usage & Attitude), Satisfaction/NPS, Ad/Creative Test, Concept Test, Product Test, Segmentation, Omnibus, Custom. Use the most specific applicable type.
3. **Research Objectives**: If user provided a Study Objective, incorporate it as the primary objective and infer 2-4 additional objectives from the survey flow. Otherwise infer 3-5 core research questions.
4. **Analysis Framework**: Map each question number to its role in the study: screening, demographics, awareness, usage_experience, evaluation, intent_loyalty, or other.
5. **Key Segment Variables**: Identify the most important cross-analysis variables — demographics (age, gender, region), behavioral (usage, purchase), attitudinal (satisfaction, preference), brand-based (client brand users vs competitors).
6. **Banner Recommendations**: Suggest 2-4 banner groupings that would yield the most actionable cross-tabulation insights for the client brand.

## JSON Output Format
{
  "client_name": "string or empty if not identifiable",
  "study_type": "string",
  "research_objectives": ["objective1", "objective2", "objective3"],
  "analysis_framework": {
    "screening": ["S1", "S2"],
    "demographics": ["DQ1", "DQ2"],
    "awareness": ["Q1", "Q2"],
    "usage_experience": ["Q3", "Q4"],
    "evaluation": ["Q5", "Q6"],
    "intent_loyalty": ["Q7", "Q8"],
    "other": ["Q9"]
  },
  "key_segments": [
    {"question": "S2", "name": "Age Group", "type": "demographic"},
    {"question": "Q3", "name": "Brand Users", "type": "behavioral"}
  ],
  "banner_recommendations": [
    {
      "name": "Demographics",
      "rationale": "Standard demographic cuts for profiling",
      "points": ["S1(Gender)", "S2(Age Group)"]
    }
  ]
}"""


def analyze_survey_intelligence(questions: List[SurveyQuestion],
                                language: str = "ko",
                                client_brand: str = "",
                                study_objective: str = "") -> dict:
    """설문지 전체를 분석하여 구조화된 Survey Intelligence를 반환.

    단일 LLM 호출로 클라이언트, 조사유형, 목적, 프레임워크, 세그먼트를 추출.

    Args:
        questions: 전체 문항 리스트
        language: 설문지 언어
        client_brand: 사용자가 입력한 클라이언트 브랜드명 (e.g. "Hyundai")
        study_objective: 사용자가 입력한 조사 목적

    Returns:
        dict: intelligence 결과 (client_name, study_type, research_objectives, ...)
    """
    if not questions:
        return {}

    # 중복 문항번호 제거
    seen = set()
    unique_qs = []
    for q in questions:
        if q.question_number not in seen:
            seen.add(q.question_number)
            unique_qs.append(q)

    # 문항 요약 생성 (토큰 효율을 위해 compact)
    lines = []
    if client_brand:
        lines.append(f"Client Brand: {client_brand}")
    if study_objective:
        lines.append(f"Study Objective: {study_objective}")
    if lines:
        lines.append("")
    lines.append(f"Survey questionnaire with {len(unique_qs)} questions (language: {language}):\n")
    for q in unique_qs:
        text = (q.question_text or "").replace("\n", " ")[:100]
        qtype = q.question_type or ""
        opts = q.answer_options_compact()
        if len(opts) > 150:
            opts = opts[:150] + "..."
        filt = f" [Filter: {(q.filter_condition or '')[:50]}]" if q.filter_condition else ""
        line = f"[{q.question_number}] {text} ({qtype})"
        if opts:
            line += f"\n  Options: {opts}"
        if filt:
            line += filt
        lines.append(line)

    user_prompt = "\n".join(lines)

    try:
        result = call_llm_json(_INTELLIGENCE_SYSTEM_PROMPT, user_prompt,
                               MODEL_INTELLIGENCE, max_tokens=8192)
        # 기본값 보장
        result.setdefault("client_name", "")
        result.setdefault("study_type", "")
        result.setdefault("research_objectives", [])
        result.setdefault("analysis_framework", {})
        result.setdefault("key_segments", [])
        result.setdefault("banner_recommendations", [])
        # 사용자 입력이 있으면 LLM 결과 보강
        if client_brand and not result["client_name"]:
            result["client_name"] = client_brand
        return result
    except Exception as e:
        logger.error(f"Survey intelligence analysis failed: {e}")
        # 실패해도 사용자 입력 정보는 보존
        fallback = {"client_name": client_brand, "study_type": "",
                     "research_objectives": [], "analysis_framework": {},
                     "key_segments": [], "banner_recommendations": []}
        if study_objective:
            fallback["research_objectives"] = [study_objective]
        return fallback


# ======================================================================
# Phase 2: Base Definition
# ======================================================================

_BASE_SYSTEM_PROMPT = """You are a DP specialist for marketing research cross-tabulation.
Your task is to generate a human-readable Base description for each survey question.

## Rules
1. If a question has a filter_condition, describe WHO is included in the base.
   - Convert raw filter codes like "Q2=1,2" into readable labels using the referenced question's text and answer options.
   - Example: Q2=1,2 where Q2 is "Brand Awareness" with options 1=Aware, 2=Used → "Q2(Brand Awareness) 'Aware' or 'Used' respondents"
2. If no filter_condition exists, the base is "All Respondents".
3. Keep descriptions concise (one line).
4. Respond in the same language as the question text.
5. When Survey Context is provided, use the overall questionnaire flow to better interpret filter references and produce more accurate base descriptions.

## JSON Output Format
{
  "results": [
    {"question_number": "Q1", "base": "All Respondents"},
    {"question_number": "Q3", "base": "Q2(Brand Awareness) 'Aware' or 'Used' respondents"}
  ]
}"""


def generate_bases(questions: List[SurveyQuestion], language: str = "ko",
                   progress_callback=None, survey_context: str = "") -> dict:
    """Base 설명 생성 — 필터 있으면 LLM 보강, 없으면 'All Respondents'.

    Returns:
        dict: {question_number: base_string}
    """
    result = {}
    needs_llm = []

    # 문항별 컨텍스트 맵 (필터 해석에 사용)
    qn_context = {}
    for q in questions:
        qn_context[q.question_number] = {
            "text": q.question_text,
            "options": q.answer_options_compact(),
        }

    for q in questions:
        if q.filter_condition and q.filter_condition.strip():
            needs_llm.append(q)
        else:
            result[q.question_number] = "All Respondents"

    if not needs_llm:
        return result

    # 배치 분할
    batches = [needs_llm[i:i + BATCH_SIZE] for i in range(0, len(needs_llm), BATCH_SIZE)]
    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches):
        if progress_callback:
            progress_callback("base_batch_start", {
                "batch_index": batch_idx, "total_batches": total_batches,
                "question_count": len(batch),
            })

        # 프롬프트에 필터 문항의 컨텍스트 포함
        lines = []
        if survey_context:
            lines.append(survey_context)
            lines.append("")
        referenced_qns = set()
        for q in batch:
            # 필터에서 참조하는 문항번호 추출
            refs = re.findall(r'([A-Z]+\d+[a-zA-Z]*)', q.filter_condition or "")
            for ref in refs:
                if ref in qn_context:
                    referenced_qns.add(ref)

        # 참조 문항 컨텍스트
        if referenced_qns:
            lines.append("## Referenced Questions Context")
            for ref_qn in sorted(referenced_qns):
                ctx = qn_context[ref_qn]
                lines.append(f"[{ref_qn}] {ctx['text']}")
                if ctx['options']:
                    lines.append(f"  Options: {ctx['options']}")
            lines.append("")

        lines.append("## Questions to process")
        for q in batch:
            lines.append(f"[{q.question_number}] Filter: {q.filter_condition}")
            lines.append(f"  Text: {q.question_text}")

        user_prompt = "\n".join(lines)

        try:
            raw = call_llm_json(_BASE_SYSTEM_PROMPT, user_prompt, MODEL_BASE_GENERATOR)
            for r in raw.get("results", []):
                qn = str(r.get("question_number", "")).strip()
                base = str(r.get("base", "")).strip()
                if qn and base:
                    result[qn] = base
        except Exception as e:
            logger.error(f"Base generation batch {batch_idx} failed: {e}")

        # LLM이 누락한 문항은 필터 텍스트 그대로 사용
        for q in batch:
            if q.question_number not in result:
                result[q.question_number] = q.filter_condition or "All Respondents"

        if progress_callback:
            progress_callback("base_batch_done", {
                "batch_index": batch_idx, "total_batches": total_batches,
            })

    return result


# ======================================================================
# Phase 2: Net/Recode
# ======================================================================

_NET_SYSTEM_PROMPT = """You are a DP specialist for marketing research cross-tabulation.
Your task is to suggest meaningful Net/Recode groupings for survey questions.

## Rules
1. For SA/MA questions with answer options, suggest logical groupings:
   - Income ranges → Low/Mid/High
   - Age groups → Young/Middle/Senior
   - Likert scales → Top2/Bot2
   - Frequency → Frequent/Infrequent
2. Only suggest nets when grouping adds analytical value. If no meaningful grouping exists, return empty string.
3. Format: "NetName(codes): NetName(codes)" e.g. "Top2(4+5) / Bot2(1+2)"
4. Keep it concise.
5. When Survey Context is provided, consider the question's role in the overall study (e.g., screening, demographics, evaluation) to decide whether a net adds analytical value and what groupings are most meaningful.

## JSON Output Format
{
  "results": [
    {"question_number": "S2", "net_recode": "Young(1+2) / Middle(3+4) / Senior(5+6)"},
    {"question_number": "Q5", "net_recode": ""}
  ]
}"""


def _generate_scale_net(summary_types: list,
                        answer_options: list | None = None) -> str:
    """SCALE 문항의 Net/Recode를 알고리즘으로 생성.

    answer_options에서 실제 스케일 범위를 감지하여 정확한 Top2/Bot2 코드 생성.
    SummaryType에 이미 Top2/Bot2/Mean 정보가 있으면 해당 정보 참고.
    """
    # 실제 숫자 코드 추출 → 스케일 범위 결정
    numeric_codes = []
    if answer_options:
        for opt in answer_options:
            code = getattr(opt, "code", str(opt)) if not isinstance(opt, str) else opt
            try:
                numeric_codes.append(int(code))
            except (ValueError, TypeError):
                pass

    if numeric_codes:
        numeric_codes.sort()
        lo1, lo2 = numeric_codes[0], numeric_codes[1] if len(numeric_codes) > 1 else numeric_codes[0]
        hi1, hi2 = numeric_codes[-1], numeric_codes[-2] if len(numeric_codes) > 1 else numeric_codes[-1]
        top2_str = f"Top2({hi2}+{hi1})"
        bot2_str = f"Bot2({lo1}+{lo2})"
    else:
        # 코드 정보 없으면 일반적인 5점 척도 가정
        top2_str = "Top2(4+5)"
        bot2_str = "Bot2(1+2)"

    has_top2 = any("top2" in st.lower() for st in summary_types if st)
    has_bot2 = any("bot2" in st.lower() or "bottom2" in st.lower() for st in summary_types if st)
    has_mean = any("mean" in st.lower() for st in summary_types if st)

    parts = []
    if has_top2:
        parts.append(top2_str)
    if has_bot2:
        parts.append(bot2_str)
    if has_mean:
        parts.append("Mean")

    if parts:
        return " / ".join(parts)

    # 기본: Top2 / Bot2 / Mean
    return f"{top2_str} / {bot2_str} / Mean"


def generate_net_recodes(questions: List[SurveyQuestion], language: str = "ko",
                         progress_callback=None, survey_context: str = "") -> dict:
    """Net/Recode 제안 — SCALE은 알고리즘, SA/MA는 LLM.

    Returns:
        dict: {question_number: net_recode_string}
    """
    result = {}
    needs_llm = []

    # 문항별 SummaryType 수집
    qn_summary_types = {}
    for q in questions:
        if q.question_number not in qn_summary_types:
            qn_summary_types[q.question_number] = []
        if q.summary_type:
            qn_summary_types[q.question_number].append(q.summary_type)

    # 이미 처리된 문항번호 추적 (중복 방지)
    seen_qn = set()
    for q in questions:
        if q.question_number in seen_qn:
            continue
        seen_qn.add(q.question_number)

        qtype = (q.question_type or "").strip().upper()
        sts = qn_summary_types.get(q.question_number, [])

        # SCALE/매트릭스 → 알고리즘
        if "SCALE" in qtype or re.match(r'\d+\s*PT\s*X\s*\d+', qtype):
            result[q.question_number] = _generate_scale_net(sts, q.answer_options)
        elif q.answer_options and len(q.answer_options) >= 4:
            # SA/MA with enough options → LLM 제안 대상
            needs_llm.append(q)
        else:
            result[q.question_number] = ""

    if not needs_llm:
        return result

    batches = [needs_llm[i:i + BATCH_SIZE] for i in range(0, len(needs_llm), BATCH_SIZE)]
    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches):
        if progress_callback:
            progress_callback("net_batch_start", {
                "batch_index": batch_idx, "total_batches": total_batches,
                "question_count": len(batch),
            })

        lines = []
        if survey_context:
            lines.append(survey_context)
            lines.append("")
        lines.append("Generate Net/Recode suggestions for these questions:\n")
        for q in batch:
            lines.append(f"[{q.question_number}] {q.question_text}")
            lines.append(f"  Type: {q.question_type or 'SA'}")
            lines.append(f"  Options: {q.answer_options_compact()}")
            lines.append("")

        user_prompt = "\n".join(lines)

        try:
            raw = call_llm_json(_NET_SYSTEM_PROMPT, user_prompt, MODEL_NET_GENERATOR)
            for r in raw.get("results", []):
                qn = str(r.get("question_number", "")).strip()
                net = str(r.get("net_recode", "")).strip()
                if qn:
                    result[qn] = net
        except Exception as e:
            logger.error(f"Net/Recode batch {batch_idx} failed: {e}")

        for q in batch:
            if q.question_number not in result:
                result[q.question_number] = ""

        if progress_callback:
            progress_callback("net_batch_done", {
                "batch_index": batch_idx, "total_batches": total_batches,
            })

    return result


# ======================================================================
# Phase 3: Banner Management — 3-Step CoT Pipeline
# ======================================================================

# ── Step 1: Analysis Plan ────────────────────────────────────────────

_ANALYSIS_PLAN_SYSTEM_PROMPT = """You are a research director at a top-tier marketing research firm (Ipsos/Kantar/Nielsen level) designing a cross-tabulation analysis framework.

## Your Mindset
You are NOT listing questions that could become banners. You are designing the **analytical lenses** through which the client's brand team will read every table in the report. Each lens must answer a specific strategic question. The output of this step directly determines the quality of the entire Table Guide.

## Your CoT Process (follow these steps exactly)

### Step 1: Study Comprehension
- What is the study type? (Brand Tracking / U&A / Satisfaction / Ad Test / Concept Test / Segmentation / etc.)
- Who is the client? What brand/category?
- What are the 3-5 core research questions this study must answer?
- What decisions will the client make based on this data?

### Step 2: Analytical Perspective Design
Based on Step 1, determine what analytical lenses (categories) are needed.
Each perspective must answer a specific strategic question for the client.

Guidelines:
- Minimum 3, maximum 7 perspectives
- Each perspective must have 2-5 banner dimensions
- At least 30% of total dimensions must be composite (combining 2+ questions)
- Every perspective must pass the "So What?" test — if removed, would the client miss critical insight?

### Step 3: Dimension Specification
For each perspective, define concrete dimensions with:
- Candidate questions (exact question numbers)
- Grouping strategy (exact codes)
- Whether it's composite or simple

## Common Perspectives (for reference, NOT mandatory)
Below are examples commonly found in different study types. Use as inspiration, not as a checklist.
- **Demographics**: Gender, Age, Region (almost always needed, but keep minimal)
- **Brand Funnel**: Awareness → Consideration → Usage → Loyalty (for brand studies)
- **Behavioral Segments**: Usage intensity, Purchase recency, Channel preference
- **Attitudinal Segments**: Satisfaction tiers, NPS groups, Intent levels
- **Product/Market Specific**: Vehicle type, Engine preference, Price segment, etc.
- **Media/Touchpoint**: Information sources, Channel exposure (for ad/media studies)
- **Decision Journey**: Pre-purchase → Purchase → Post-purchase (for path-to-purchase)

Different study types prioritize differently:
- Brand Tracking → Brand Funnel + Competitive + Attitudinal
- U&A → Behavioral + Usage + Demographics
- Satisfaction/NPS → Attitudinal + Service Journey + Demographics
- Ad/Creative Test → Exposure + Recall + Attitudinal
- Concept Test → Interest Segments + Behavioral + Need States

## Rules for Dimension Design
1. **At least 30% of dimensions MUST be composite** (is_composite: true) — combining 2+ questions
2. **Grouping strategies must be specific**: exact code groupings, not vague descriptions
3. **Every dimension must answer a strategic question** — "So what?" test
4. **EXCLUDE**: OE questions, screening termination questions, country/market filters
5. **Think in terms of SEGMENTS, not questions**: "High-Intent EV Switchers" not "Q15 responses"

## JSON Output Format
{
  "cot_reasoning": {
    "study_type": "Identified study type and rationale",
    "client_brand": "Identified or inferred client brand",
    "core_research_questions": ["Q1", "Q2", "Q3"],
    "client_decisions": "What decisions will the client make from this data?",
    "perspective_rationale": "Why these specific perspectives were chosen over alternatives"
  },
  "analysis_strategy": "3-4 sentences: What is the core analytical story? What strategic questions will this banner framework answer?",
  "categories": [
    {
      "category_name": "Descriptive name for this analytical perspective",
      "business_rationale": "What strategic question does this perspective answer?",
      "priority": "critical | important | supplementary",
      "banner_dimensions": [
        {
          "dimension_name": "Human-readable segment name (how it appears in report)",
          "analytical_question": "What strategic question does this dimension reveal?",
          "candidate_questions": ["SQ1", "SQ2"],
          "grouping_strategy": "Specific grouping: Code 1,2 = Group A, Code 3,4 = Group B",
          "is_composite": false
        }
      ]
    }
  ]
}"""


def _create_analysis_plan(questions: List[SurveyQuestion],
                          language: str,
                          survey_context: str,
                          intelligence: dict | None) -> dict | None:
    """Step 1: 분석 계획 생성 — 어떤 교차분석이 필요한지 전략적으로 분석.

    Args:
        questions: 전체 문항 리스트
        language: 설문지 언어
        survey_context: Study Brief + Intelligence + Question Flow
        intelligence: Survey Intelligence 결과 dict

    Returns:
        분석 계획 dict 또는 None (실패 시)
    """
    lines = []
    if survey_context:
        lines.append(survey_context)
        lines.append("")

    # Intelligence가 있으면 배너 추천 정보 포함
    if intelligence:
        recs = intelligence.get("banner_recommendations", [])
        if recs:
            lines.append("## Prior Banner Recommendations (from intelligence)")
            for rec in recs:
                lines.append(f"- {rec.get('name', '')}: {rec.get('rationale', '')}")
                pts = rec.get("points", [])
                if pts:
                    lines.append(f"  Variables: {', '.join(pts)}")
            lines.append("")

    lines.append(f"## Complete Question List ({len(questions)} questions, language: {language})")
    lines.append("")
    lines.append(_format_questions_compact(questions, include_options=True))

    user_prompt = "\n".join(lines)

    try:
        result = _call_llm_json_with_fallback(
            _ANALYSIS_PLAN_SYSTEM_PROMPT, user_prompt,
            MODEL_INTELLIGENCE, temperature=0.3, max_tokens=8192,
        )
        result.setdefault("analysis_strategy", "")
        result.setdefault("categories", [])
        result.setdefault("cot_reasoning", {})
        # Log CoT reasoning for debugging
        cot = result.get("cot_reasoning", {})
        if cot:
            logger.info(f"Analysis plan CoT: study_type={cot.get('study_type', '')}, "
                        f"client={cot.get('client_brand', '')}, "
                        f"perspectives={len(result.get('categories', []))}")
        # Flatten banner_dimensions from categories for downstream compatibility
        _PRIORITY_MAP = {"critical": "high", "important": "high", "supplementary": "medium"}
        all_dims = []
        for cat in result.get("categories", []):
            cat_name = cat.get("category_name", "")
            cat_priority = _PRIORITY_MAP.get(cat.get("priority", ""), "high")
            for dim in cat.get("banner_dimensions", []):
                dim["category"] = cat_name
                # Map is_composite to variable_type for compatibility
                if dim.get("is_composite"):
                    dim.setdefault("variable_type", "composite")
                dim.setdefault("priority", cat_priority)
                all_dims.append(dim)
        result["banner_dimensions"] = all_dims
        # Extract composite opportunities from is_composite dims
        composites = []
        for dim in all_dims:
            if dim.get("is_composite"):
                composites.append({
                    "name": dim.get("dimension_name", ""),
                    "component_questions": dim.get("candidate_questions", []),
                    "logic": dim.get("grouping_strategy", ""),
                    "analytical_value": dim.get("analytical_question", ""),
                })
        result["composite_opportunities"] = composites
        total_dims = len(all_dims)
        cat_count = len(result["categories"])
        logger.info(f"Analysis plan: {cat_count} categories, {total_dims} dimensions, "
                    f"{len(composites)} composite opportunities")
        return result
    except Exception as e:
        logger.error(f"Analysis plan creation failed: {e}")
        return None


# ── Step 2: Banner Design ────────────────────────────────────────────

_BANNER_DESIGN_SYSTEM_PROMPT = """You are the head of DP at a top-tier research firm, implementing a cross-tabulation banner framework from an analysis plan.

## Your Task
Convert EVERY dimension from the analysis plan into production-ready banner specifications with exact conditions. The quality of the final report depends entirely on the precision of your banner definitions.

## Quality Standard
Each banner must pass the "VP of Insights" test: if a VP sees this banner in a cross-tab, they should immediately understand what segment they're looking at and why it matters for the brand strategy.

## Implementation Rules

### Condition Format
- Single code: `SQ1=1`
- Multiple codes (OR): `SQ1=1,2,3`
- Cross-question AND: `Q3=1&Q5=1,2`
- **NEVER** use negative conditions (`!=`, `NOT`, `≠`)
- Every value must have an explicit, executable condition
- Values within a banner must be **mutually exclusive**

### Simple Banners (single question)
- **Demographics**: Gender (Male/Female), Age (3-4 bands), Region (2-4 clusters)
- **Behavioral**: Group codes into NET segments — never list individual codes as banner values
- **Scales**: Top2 / Mid / Bot2 (never individual scale points)

### Composite Banners (multiple questions combined with "&")
These are the MOST VALUABLE banners. They create strategic segments that don't exist in any single question.
Examples:
- **Brand Funnel**: Combine awareness + consideration + ownership questions
  - "Loyal Owner" = `SQ10=1&SQ17=1` (owns client brand AND intends to repurchase)
  - "At-Risk Owner" = `SQ10=1&SQ17=2,3,4,5` (owns but considering switch)
  - "Conquest Target" = `SQ10=2,3,4&D4=1` (owns competitor but considers client)
- **Engaged Intender**: Combine purchase intent + information seeking
  - "Active Researcher" = `SQ11=1,2&TP1=1,2,3` (high intent AND seeking info)
  - "Passive Intender" = `SQ11=1,2&TP1=98,99` (high intent but NOT actively looking)

### Value Label Guidelines
- Labels must be short (2-4 words), descriptive, and meaningful
- BAD: "Code 1-3", "Q5=1,2", "Group A"
- GOOD: "Loyal Owner", "Active Researcher", "Price-Sensitive", "EV Considerer"

## Output Requirements
- **Minimum 12 banners** across all categories
- **At least 4 composite banners** (banner_type: "composite")
- **category field MUST match** the analysis plan's category_name exactly
- Every category must have at least 2 banners
- Do NOT skip any dimension from the analysis plan

## JSON Output Format
{
  "banners": [
    {
      "category": "Brand Relationship",
      "name": "Brand Funnel Stage",
      "rationale": "Identifies where in the awareness→consideration→purchase funnel the client is losing prospects to competitors",
      "banner_type": "composite",
      "source_questions": ["A3", "D4", "SQ10"],
      "values": [
        {
          "label": "Loyal Owner",
          "condition": "SQ10=1&SQ17=1",
          "reasoning": "Owns client brand AND intends to repurchase — core loyal base"
        },
        {
          "label": "At-Risk Owner",
          "condition": "SQ10=1&SQ17=2,3,4,5",
          "reasoning": "Owns client brand but considering competitors — retention priority"
        },
        {
          "label": "Conquest Target",
          "condition": "SQ10=2,3,4&D4=1",
          "reasoning": "Competitor owner who considers client brand — acquisition opportunity"
        },
        {
          "label": "Non-Considerer",
          "condition": "SQ10=2,3,4&D4=2,3,4,5",
          "reasoning": "Competitor owner not considering client — awareness/image gap"
        }
      ]
    }
  ]
}"""


def _design_banners_from_plan(analysis_plan: dict,
                               questions: List[SurveyQuestion],
                               language: str,
                               survey_context: str) -> dict | None:
    """Step 2: 분석 계획 기반 배너 설계.

    Args:
        analysis_plan: Step 1의 분석 계획
        questions: 전체 문항 리스트
        language: 설문지 언어
        survey_context: Study Brief + Intelligence

    Returns:
        배너 스펙 dict ({"banners": [...]}) 또는 None
    """
    # 분석 계획에서 후보 문항번호 수집
    candidate_qns = set()
    for dim in analysis_plan.get("banner_dimensions", []):
        for qn in dim.get("candidate_questions", []):
            candidate_qns.add(qn.strip())
    for comp in analysis_plan.get("composite_opportunities", []):
        for qn in comp.get("component_questions", []):
            candidate_qns.add(qn.strip())

    if not candidate_qns:
        logger.warning("Analysis plan has no candidate questions")
        return None

    # 후보 문항의 full 상세 정보 수집
    qn_map = {}
    for q in questions:
        if q.question_number not in qn_map:
            qn_map[q.question_number] = q
    candidate_qs = [qn_map[qn] for qn in candidate_qns if qn in qn_map]

    if not candidate_qs:
        logger.warning("No matching questions found for analysis plan candidates")
        return None

    # 프롬프트 구성
    import json as _json
    lines = []
    if survey_context:
        lines.append(survey_context)
        lines.append("")

    lines.append("## Analysis Plan")
    lines.append(f"Strategy: {analysis_plan.get('analysis_strategy', '') or analysis_plan.get('analysis_reasoning', '')}")
    lines.append("")

    # Category-based dimension listing
    categories = analysis_plan.get("categories", [])
    if categories:
        lines.append("### Categories & Dimensions")
        for cat in categories:
            cat_name = cat.get("category_name", "")
            lines.append(f"\n#### {cat_name}")
            lines.append(f"Rationale: {cat.get('business_rationale', '')}")
            for dim in cat.get("banner_dimensions", []):
                composite_tag = " [COMPOSITE]" if dim.get("is_composite") else ""
                lines.append(f"- **{dim.get('dimension_name', '')}**{composite_tag}")
                lines.append(f"  Question: {dim.get('analytical_question', '')}")
                lines.append(f"  Candidates: {', '.join(dim.get('candidate_questions', []))}")
                lines.append(f"  Grouping: {dim.get('grouping_strategy', '')}")
    else:
        # Fallback for old-style plans without categories
        lines.append("### Banner Dimensions")
        for dim in analysis_plan.get("banner_dimensions", []):
            lines.append(f"- **{dim.get('dimension_name', '')}** ({dim.get('variable_type', '')})")
            lines.append(f"  Question: {dim.get('analytical_question', '')}")
            lines.append(f"  Candidates: {', '.join(dim.get('candidate_questions', []))}")
            lines.append(f"  Grouping: {dim.get('grouping_strategy', '')}")

    composites = analysis_plan.get("composite_opportunities", [])
    if composites:
        lines.append("")
        lines.append("### Composite Opportunities")
        for comp in composites:
            lines.append(f"- **{comp.get('name', '')}**: {comp.get('logic', '')}")
            lines.append(f"  Value: {comp.get('analytical_value', '')}")

    lines.append("")
    lines.append(f"## Candidate Question Details ({len(candidate_qs)} questions)")
    lines.append("")
    lines.append(_format_questions_full(candidate_qs))

    user_prompt = "\n".join(lines)

    try:
        result = _call_llm_json_with_fallback(
            _BANNER_DESIGN_SYSTEM_PROMPT, user_prompt,
            MODEL_INTELLIGENCE, temperature=0.2, max_tokens=16384,
        )
        banners = result.get("banners", [])
        logger.info(f"Banner design: {len(banners)} banners generated")
        return result
    except Exception as e:
        logger.error(f"Banner design failed: {e}")
        return None


# ── Step 3: Validation ───────────────────────────────────────────────

_BANNER_VALIDATION_SYSTEM_PROMPT = """You are a DP quality checker validating cross-tabulation banner specifications.

## Your Task
Check each banner value's condition against the actual answer codes and fix any issues.

## Validation Rules
1. **CODE_EXISTS**: Every code in a condition must exist in that question's answer options. Remove or replace codes that don't exist.
2. **MUTUAL_EXCLUSIVITY**: Within the same banner, values should not overlap (same respondent shouldn't fall into two values). Flag but do not remove if overlap exists — just add a warning.
3. **NO_NEGATIVE**: Conditions must NOT use "!=", "NOT", "≠", or "<>". Convert to positive conditions using actual existing codes.
4. **COMPOSITE_CONSISTENCY**: For "&" conditions, all referenced questions must be present in the provided code map.
5. **COMPLETENESS**: If a major segment seems missing (e.g., banner has "Male" but no "Female"), add a warning.

## Input Format
You will receive:
- A list of banners with their conditions
- A code_map showing each question's valid codes

## JSON Output Format
Return the CORRECTED banners in the same format, with an additional "warnings" field:
{
  "banners": [
    {
      "category": "Demographics",
      "name": "...",
      "rationale": "...",
      "banner_type": "simple or composite",
      "source_questions": ["SQ1"],
      "values": [
        {
          "label": "...",
          "condition": "SQ1=1",
          "reasoning": "..."
        }
      ],
      "warnings": ["optional list of validation warnings"]
    }
  ],
  "validation_summary": "Brief summary of changes made"
}

## Rules
- If a condition references codes that don't exist, correct them to the closest valid codes or remove the value
- If a banner has only 1 valid value after correction, remove the entire banner
- Preserve all valid banners and values as-is
- Only modify what needs fixing
- PRESERVE the "category" field on each banner exactly as provided — do not remove or rename it"""


def _validate_banners(banner_spec: dict,
                      questions: List[SurveyQuestion]) -> dict:
    """Step 3: 생성된 배너를 실제 보기 코드 대비 검증.

    Args:
        banner_spec: Step 2의 배너 스펙 ({"banners": [...]})
        questions: 전체 문항 리스트 (코드 맵 생성용)

    Returns:
        검증/수정된 배너 스펙 dict
    """
    code_map = _build_code_map(questions)

    import json as _json
    lines = []
    lines.append("## Banners to Validate")
    lines.append(_json.dumps(banner_spec, ensure_ascii=False, indent=2))
    lines.append("")
    lines.append("## Valid Code Map (question -> valid codes)")
    # 관련 문항만 포함 (compact)
    relevant_qns = set()
    for b in banner_spec.get("banners", []):
        for qn in b.get("source_questions", []):
            relevant_qns.add(qn)
        for v in b.get("values", []):
            cond = v.get("condition", "")
            for part in cond.split("&"):
                qn_part = part.split("=")[0].strip()
                if qn_part:
                    relevant_qns.add(qn_part)

    for qn in sorted(relevant_qns):
        codes = code_map.get(qn, [])
        if codes:
            lines.append(f"  {qn}: [{', '.join(codes)}]")
        else:
            lines.append(f"  {qn}: (no codes found)")

    user_prompt = "\n".join(lines)

    try:
        result = _call_llm_json_with_fallback(
            _BANNER_VALIDATION_SYSTEM_PROMPT, user_prompt,
            DEFAULT_MODEL, temperature=0.1, max_tokens=16384,
        )
        summary = result.get("validation_summary", "")
        if summary:
            logger.info(f"Banner validation: {summary}")
        return result
    except Exception as e:
        logger.error(f"Banner validation failed: {e}")
        return banner_spec  # 실패 시 원본 반환


# ── Legacy Banner Prompt (폴백용) ────────────────────────────────────

_BANNER_SYSTEM_PROMPT = """You are a senior DP specialist designing cross-tabulation banners for marketing research.

## Critical Constraints
1. **Generate 3-6 banners MAXIMUM**. Each banner should represent a distinct analytical dimension. Combine related variables into one banner rather than creating many small ones.
2. **Each banner should have 2-6 values**. If a question has many codes, you MUST group them into meaningful NET categories (e.g., group age ranges into 3-4 bands, group brands into "Korean Brands" vs "Imported Brands", group scales into Top2/Bot2).
3. **Every banner value MUST have an explicit condition** using "QN=code" format.
4. **Multi-question combinations**: Use "&" to combine questions when it creates an analytically meaningful segment (e.g., "Q3=1&Q5=1"). This is powerful — use it when a combined segment provides more insight than individual questions alone.

## What to EXCLUDE
- **Screening/filter questions** used to terminate respondents (e.g., industry screeners) — these are NOT segmentation variables
- **Country/market-specific questions** (filter references country, market, or specific geography) — not suitable for total/integrated banners
- **Low-value or redundant dimensions** — if a variable doesn't reveal meaningful differences in the main study questions, don't include it

## How to Group Banner Values (NET logic)
- **Scales/ratings**: Always use Top2 (top 2 codes) / Mid / Bot2 (bottom 2 codes), NOT individual codes
- **Age**: Group into 3-4 meaningful bands (e.g., 18-29, 30-44, 45+), NOT individual year ranges
- **Regions**: Group into 2-4 major geographic clusters, NOT individual cities/provinces
- **Brands**: Group by strategic segments (e.g., "Client Brand" vs "Domestic Competitors" vs "Imported Brands" vs "Non-Owner"), NOT individual brands. Only list individual brands if the study is specifically about that brand vs 1-2 key competitors.
- **Purchase timing**: Group into "Recent" vs "Older" or similar 2-3 groups
- **Behavioral variables**: Create binary or 3-way splits that tell a clear analytical story (e.g., "Owner" vs "Non-Owner", "High Intent" vs "Low Intent")

## JSON Output Format
{
  "banners": [
    {
      "name": "Banner name (the analytical dimension)",
      "rationale": "1-2 sentence explanation of WHY this banner is analytically valuable — what insight does it reveal when cross-tabulated?",
      "source_questions": ["SQ1"],
      "values": [
        {"label": "Value label (short)", "condition": "SQ1=1"},
        {"label": "Value label (short)", "condition": "SQ1=2"}
      ]
    }
  ]
}

## Condition Format Rules
- Single code: "SQ1=1"
- Multiple codes (OR within one question): "SQ1=1,2,3"
- Combined questions (AND across questions): "Q3=1&Q5=1"
- Always use exact question numbers and answer codes from the questionnaire
- **NEVER use negative conditions** like "!=", "NOT", or "≠". Only use positive "=" conditions. If a question already has a filter (only asked to a subset), you don't need to re-state the filter — just use that question's codes directly (e.g., if SQ6 is only asked when SQ5≠99, use "SQ6=1,2,3" without adding "&SQ5!=99").
- **Each banner value must be mutually exclusive and clearly defined**. Do NOT create catch-all values like "Multiple answers" or "All of the above".

## Example: Good Banner Design for a Brand Tracking Study
{
  "banners": [
    {
      "name": "Gender",
      "rationale": "Standard demographic cut to identify gender-based differences in brand awareness and preference.",
      "source_questions": ["SQ1"],
      "values": [
        {"label": "Male", "condition": "SQ1=1"},
        {"label": "Female", "condition": "SQ1=2"}
      ]
    },
    {
      "name": "Age Group",
      "rationale": "Generational segmentation reveals different brand consideration sets and media consumption patterns.",
      "source_questions": ["SQ2"],
      "values": [
        {"label": "18-29", "condition": "SQ2=1,2"},
        {"label": "30-44", "condition": "SQ2=3,4,5"},
        {"label": "45+", "condition": "SQ2=6,7,8"}
      ]
    },
    {
      "name": "Ownership Segment",
      "rationale": "Comparing client brand owners vs competitors reveals satisfaction drivers and switching barriers critical for retention strategy.",
      "source_questions": ["SQ5", "SQ6"],
      "values": [
        {"label": "Client Brand Owner", "condition": "SQ6=1"},
        {"label": "Domestic Competitor Owner", "condition": "SQ6=2,3"},
        {"label": "Import Brand Owner", "condition": "SQ6=4,5,6,7,8"},
        {"label": "Non-Owner", "condition": "SQ5=99"}
      ]
    },
    {
      "name": "Purchase Intent",
      "rationale": "Separating high vs low intent groups helps prioritize acquisition targets and tailor messaging.",
      "source_questions": ["SQ11"],
      "values": [
        {"label": "High Intent (Top2)", "condition": "SQ11=1,2"},
        {"label": "Low Intent (Bot2)", "condition": "SQ11=4,5"}
      ]
    }
  ]
}"""


def _banner_id_from_index(i: int) -> str:
    """배너 인덱스 → ID 문자열 (A-Z, 이후 AA, AB, ..., AZ, BA, ...)."""
    if i < 26:
        return chr(65 + i)
    # 26 이상: AA=26, AB=27, ... AZ=51, BA=52, ...
    first = chr(65 + (i // 26) - 1)
    second = chr(65 + (i % 26))
    return first + second


def _assign_categories_from_plan(banner_spec: dict, analysis_plan: dict) -> None:
    """Analysis Plan의 dimension→category 매핑으로 배너에 카테고리 부여.

    source_questions와 candidate_questions의 겹침, 또는
    배너 이름과 dimension 이름의 유사도로 매칭합니다.
    이미 category가 있는 배너는 건드리지 않습니다.
    """
    if not analysis_plan:
        return

    # Build dimension → category mappings
    dim_cat_map: dict[str, str] = {}    # dim_name_lower → category_name
    qs_cat_map: list[tuple[set, str]] = []  # (candidate_qs_set, category_name)
    for cat in analysis_plan.get("categories", []):
        cat_name = cat.get("category_name", "")
        if not cat_name:
            continue
        for dim in cat.get("banner_dimensions", []):
            dim_name = dim.get("dimension_name", "")
            if dim_name:
                dim_cat_map[dim_name.lower()] = cat_name
            cqs = set(dim.get("candidate_questions", []))
            if cqs:
                qs_cat_map.append((cqs, cat_name))

    for banner in banner_spec.get("banners", []):
        if banner.get("category"):
            continue  # Already assigned

        bname = (banner.get("name", "") or "").lower()

        # Try 1: Match by banner name ↔ dimension name (substring)
        for dim_name_lower, cat_name in dim_cat_map.items():
            if dim_name_lower in bname or bname in dim_name_lower:
                banner["category"] = cat_name
                break

        if banner.get("category"):
            continue

        # Try 2: Match by source_questions overlap with candidate_questions
        src_qs = set(banner.get("source_questions", []))
        if src_qs:
            best_cat = ""
            best_overlap = 0
            for cqs, cat_name in qs_cat_map:
                overlap = len(src_qs & cqs)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_cat = cat_name
            if best_cat:
                banner["category"] = best_cat


def _infer_banner_category(banner_name: str) -> str:
    """배너 이름에서 카테고리를 추정 (category 필드가 없는 경우 폴백).

    매칭 순서가 중요: 더 구체적인 키워드를 먼저 검사.
    """
    name_lower = banner_name.lower()

    # EV/Powertrain (engine, ev 등 — demographics의 "age"보다 먼저 검사)
    ev_kw = [" ev ", "ev ", " ev", "electric", "전기차", "hybrid", "하이브리드",
             "engine type", "엔진 유형", "powertrain"]
    if any(kw in f" {name_lower} " or name_lower.startswith(kw.strip())
           for kw in ev_kw):
        return "EV & Powertrain"

    # Brand/Funnel (brand, funnel, awareness, loyalty)
    brand_kw = ["brand", "funnel", "awareness", "loyalty", "consideration",
                "ownership segment", "브랜드", "보유", "인지", "충성"]
    if any(kw in name_lower for kw in brand_kw):
        return "Brand & Ownership"

    # Purchase/Usage behavior
    behav_kw = ["purchase", "intent", "usage", "buying", "구매", "의향",
                "사용", "이용", "frequency", "빈도"]
    if any(kw in name_lower for kw in behav_kw):
        return "Purchase & Usage"

    # Satisfaction/Evaluation
    eval_kw = ["satisfaction", "rating", "nps", "recommend", "만족",
               "평가", "추천"]
    if any(kw in name_lower for kw in eval_kw):
        return "Evaluation"

    # Demographics (가장 마지막 — 넓은 매칭)
    demo_kw = ["gender", "age group", "age band", "region", "city",
               "income", "education", "occupation", "marital",
               "성별", "연령", "지역", "소득", "학력", "직업"]
    if any(kw in name_lower for kw in demo_kw):
        return "Demographics"

    # Vehicle/Car ownership (brand와 별도)
    car_kw = ["car ownership", "vehicle", "차량", "자동차", "car type"]
    if any(kw in name_lower for kw in car_kw):
        return "Vehicle Ownership"

    return ""


def _parse_banner_spec_to_models(raw: dict) -> List[Banner]:
    """LLM JSON 배너 스펙을 Banner 모델 리스트로 변환."""
    banners = []
    for i, b_data in enumerate(raw.get("banners", [])):
        banner_id = _banner_id_from_index(i)
        source_qs = b_data.get("source_questions", [])
        source_str = "&".join(source_qs) if source_qs else ""

        points = []
        for j, v_data in enumerate(b_data.get("values", [])):
            condition = v_data.get("condition", "")
            # source_question: condition에서 문항번호 추출 또는 배너 레벨 source 사용
            if condition:
                # "SQ1=1" → "SQ1", "A1=2&A2=5" → "A1&A2"
                parts = condition.split("&")
                sq = "&".join(p.split("=")[0].strip() for p in parts)
            else:
                sq = source_str

            points.append(BannerPoint(
                point_id=f"BP_{banner_id}_{j + 1}",
                label=v_data.get("label", ""),
                source_question=sq,
                condition=condition,
            ))

        banner_type = b_data.get("banner_type", "simple")
        # "&" 조건이 있으면 composite으로 강제
        has_composite = any("&" in (v.get("condition", "")) for v in b_data.get("values", []))
        if has_composite:
            banner_type = "composite"

        banner_name = b_data.get("name", f"Banner {banner_id}")
        category = b_data.get("category", "")
        if not category:
            category = _infer_banner_category(banner_name)

        banners.append(Banner(
            banner_id=banner_id,
            name=banner_name,
            points=points,
            rationale=b_data.get("rationale", ""),
            banner_type=banner_type,
            category=category,
        ))

    return banners


def _fallback_heuristic_candidates(questions: List[SurveyQuestion],
                                    intelligence: dict | None) -> List[SurveyQuestion]:
    """Step 1 실패 시 폴백: 기존 휴리스틱으로 후보 문항 선정."""
    intel_segment_qns = set()
    if intelligence:
        for seg in intelligence.get("key_segments", []):
            qn = seg.get("question", "").strip()
            if qn:
                intel_segment_qns.add(qn.upper())

    demo_keywords_ko = ["성별", "연령", "지역", "소득", "학력", "직업", "결혼"]
    demo_keywords_en = ["gender", "age", "region", "income", "education", "occupation", "marital"]
    demo_keywords = demo_keywords_ko + demo_keywords_en
    country_keywords = ["country", "market", "국가", "마켓", "나라"]

    candidates = []
    seen_qn = set()
    for q in questions:
        if q.question_number in seen_qn:
            continue
        seen_qn.add(q.question_number)

        filt_lower = (q.filter_condition or "").lower()
        if any(kw in filt_lower for kw in country_keywords):
            continue

        is_screening = q.question_number.upper().startswith("S")
        is_demo = any(kw in (q.question_text or "").lower() for kw in demo_keywords)
        is_intel_segment = q.question_number.upper() in intel_segment_qns
        has_options = len(q.answer_options) >= 2

        if (is_screening or is_demo or is_intel_segment) and has_options:
            candidates.append(q)

    return candidates


def _fallback_direct_banner(candidates: List[SurveyQuestion],
                             survey_context: str) -> List[Banner]:
    """분석 계획 없이 직접 배너 설계 (폴백 경로)."""
    if not candidates:
        return []

    lines = []
    if survey_context:
        lines.append(survey_context)
        lines.append("")
    lines.append("Design banner specifications from these candidate questions.\n"
                 "Only generate meaningful banners. Each banner value must have an explicit condition.\n")
    for q in candidates:
        lines.append(f"[{q.question_number}] {q.question_text}")
        lines.append(f"  Type: {q.question_type or 'SA'}")
        lines.append(f"  Options: {q.answer_options_compact()}")
        if q.filter_condition:
            lines.append(f"  Filter: {q.filter_condition}")
        lines.append("")

    user_prompt = "\n".join(lines)

    try:
        raw = call_llm_json(_BANNER_SYSTEM_PROMPT, user_prompt, MODEL_BANNER_SUGGESTER)
    except Exception as e:
        logger.error(f"Fallback banner suggestion failed: {e}")
        return []

    return _parse_banner_spec_to_models(raw)


_MIN_BANNER_COUNT = 8           # 최소 배너 수
_MIN_COMPOSITE_COUNT = 3        # 최소 composite 배너 수
_MIN_CATEGORY_COUNT = 3         # 최소 카테고리 수
_MAX_RETRY = 1                  # 품질 미달 시 재시도 횟수


def _assess_banner_quality(banner_spec: dict) -> dict:
    """배너 스펙의 품질 지표를 평가.

    Returns:
        dict: {total_banners, composite_count, category_count, categories, issues}
    """
    banners = banner_spec.get("banners", [])
    total = len(banners)
    composite_count = 0
    categories = set()

    for b in banners:
        cat = b.get("category", "")
        if cat:
            categories.add(cat)
        btype = b.get("banner_type", "simple")
        has_and = any("&" in v.get("condition", "") for v in b.get("values", []))
        if btype == "composite" or has_and:
            composite_count += 1

    issues = []
    if total < _MIN_BANNER_COUNT:
        issues.append(f"Only {total} banners (minimum: {_MIN_BANNER_COUNT})")
    if composite_count < _MIN_COMPOSITE_COUNT:
        issues.append(f"Only {composite_count} composite banners (minimum: {_MIN_COMPOSITE_COUNT})")
    if len(categories) < _MIN_CATEGORY_COUNT:
        issues.append(f"Only {len(categories)} categories (minimum: {_MIN_CATEGORY_COUNT})")

    return {
        "total_banners": total,
        "composite_count": composite_count,
        "category_count": len(categories),
        "categories": sorted(categories),
        "issues": issues,
        "pass": len(issues) == 0,
    }


def _assess_plan_quality(plan: dict) -> dict:
    """분석 계획의 품질 지표를 평가.

    Returns:
        dict: {total_dims, composite_dims, composite_ratio, category_count, issues, pass}
    """
    dims = plan.get("banner_dimensions", [])
    total = len(dims)
    cats = plan.get("categories", [])
    cat_count = len(cats)
    composite_count = sum(1 for d in dims if d.get("is_composite"))
    composite_ratio = composite_count / total if total > 0 else 0

    issues = []
    if total < 8:
        issues.append(f"Only {total} dimensions (minimum: 8)")
    if composite_ratio < 0.25:
        issues.append(f"Only {composite_count}/{total} composite ({composite_ratio:.0%}, minimum: 25%)")
    if cat_count < 3:
        issues.append(f"Only {cat_count} categories (minimum: 3)")
    if cat_count > 8:
        issues.append(f"{cat_count} categories exceeds maximum (8)")

    return {
        "total_dims": total,
        "composite_dims": composite_count,
        "composite_ratio": composite_ratio,
        "category_count": cat_count,
        "issues": issues,
        "pass": len(issues) == 0,
    }


def suggest_banner_points(questions: List[SurveyQuestion],
                          language: str = "ko",
                          survey_context: str = "",
                          intelligence: dict | None = None) -> tuple[List[Banner], dict | None]:
    """3단계 CoT 파이프라인으로 배너 후보 제안.

    Step 1 (Analysis Plan) → Step 2 (Banner Design) → Step 3 (Validation)
    각 단계에서 품질 미달 시 1회 재시도. 실패 시 graceful degradation.

    Args:
        questions: 전체 문항 리스트
        language: 설문지 언어
        survey_context: Study Brief + Intelligence + Question Flow
        intelligence: Survey Intelligence 결과 dict

    Returns:
        tuple: (배너 리스트, 분석 계획 dict 또는 None)
    """
    if not questions:
        return [], None

    analysis_plan = None

    # ── Step 1: Analysis Plan (with quality gate) ──
    for attempt in range(_MAX_RETRY + 1):
        tag = f" (retry {attempt})" if attempt > 0 else ""
        logger.info(f"Banner pipeline Step 1: Creating analysis plan...{tag}")
        analysis_plan = _create_analysis_plan(questions, language, survey_context, intelligence)

        if not analysis_plan or not analysis_plan.get("banner_dimensions"):
            logger.warning("Step 1 failed or empty — falling back to heuristic candidate selection")
            candidates = _fallback_heuristic_candidates(questions, intelligence)
            if not candidates:
                return [], None
            banners = _fallback_direct_banner(candidates, survey_context)
            return banners, None

        plan_quality = _assess_plan_quality(analysis_plan)
        if plan_quality["pass"]:
            logger.info(f"Step 1 quality OK: {plan_quality['total_dims']} dims, "
                        f"{plan_quality['composite_dims']} composite, "
                        f"{plan_quality['category_count']} categories")
            break

        if attempt < _MAX_RETRY:
            logger.warning(f"Step 1 quality below threshold: {plan_quality['issues']} — retrying")
        else:
            logger.warning(f"Step 1 quality below threshold after retries: {plan_quality['issues']} — proceeding anyway")

    # ── Step 2: Banner Design (with quality gate) ──
    banner_spec = None
    for attempt in range(_MAX_RETRY + 1):
        tag = f" (retry {attempt})" if attempt > 0 else ""
        logger.info(f"Banner pipeline Step 2: Designing banners from plan...{tag}")
        banner_spec = _design_banners_from_plan(analysis_plan, questions, language, survey_context)

        if not banner_spec or not banner_spec.get("banners"):
            logger.warning("Step 2 failed — returning empty banners")
            return [], analysis_plan

        banner_quality = _assess_banner_quality(banner_spec)
        if banner_quality["pass"]:
            logger.info(f"Step 2 quality OK: {banner_quality['total_banners']} banners, "
                        f"{banner_quality['composite_count']} composite, "
                        f"{banner_quality['category_count']} categories")
            break

        if attempt < _MAX_RETRY:
            logger.warning(f"Step 2 quality below threshold: {banner_quality['issues']} — retrying")
        else:
            logger.warning(f"Step 2 quality below threshold after retries: {banner_quality['issues']} — proceeding anyway")

    # ── Step 2.5: Assign categories from analysis plan (robust fallback) ──
    _assign_categories_from_plan(banner_spec, analysis_plan)

    # ── Step 3: Validation ──
    logger.info("Banner pipeline Step 3: Validating banners...")
    validated_spec = _validate_banners(banner_spec, questions)

    # Validation LLM이 category 필드를 드랍하는 경우 원본에서 복원
    orig_banners = banner_spec.get("banners", [])
    orig_cat_map = {ob.get("name", ""): ob.get("category", "")
                    for ob in orig_banners if ob.get("name")}
    for i, vb in enumerate(validated_spec.get("banners", [])):
        if not vb.get("category"):
            # Try 1: index-based (same position = same banner)
            if i < len(orig_banners):
                vb["category"] = orig_banners[i].get("category", "")
            # Try 2: name-based fallback
            if not vb.get("category"):
                vb["category"] = orig_cat_map.get(vb.get("name", ""), "")

    # 검증 결과 파싱 (실패 시 Step 2 결과 사용)
    banners = _parse_banner_spec_to_models(validated_spec)

    if not banners:
        # 검증 후 모든 배너가 제거된 경우 Step 2 원본 사용
        logger.warning("Validation removed all banners — using pre-validation results")
        banners = _parse_banner_spec_to_models(banner_spec)

    # ── Final quality log ──
    composite_final = sum(1 for b in banners if b.banner_type == "composite")
    cat_final = len(set(b.category for b in banners if b.category))
    logger.info(f"Banner pipeline complete: {len(banners)} banners "
                f"({composite_final} composite, {cat_final} categories)")
    return banners, analysis_plan


# ======================================================================
# Banner-to-Question Assignment
# ======================================================================

def assign_banners_to_questions(questions: List[SurveyQuestion],
                                 banners: List[Banner]) -> dict:
    """문항 role/유형 기반 배너 자동 할당.

    할당 규칙:
    1. screening → Total only (배너 없음)
    2. demographics → Total only (배너 소스 문항이므로 자기 자신에게 배너 불필요)
    3. 나머지 본조사 문항 → All banners
    4. OE 문항 → Total only (주관식은 교차분석 불가)
    5. 배너의 source_question과 동일한 문항 → 해당 배너 제외 (자기참조 방지)

    Returns:
        dict: {question_number: "A,B,C" 형태의 배너 ID 문자열}
    """
    if not banners:
        return {q.question_number: "" for q in questions}

    # 배너별 소스 문항 수집
    banner_source_map: dict[str, set] = {}  # {banner_id: set(source_qns)}
    for b in banners:
        src_qns: set[str] = set()
        for pt in b.points:
            for sq in pt.source_question.split("&"):
                sq = sq.strip()
                if sq:
                    src_qns.add(sq)
        banner_source_map[b.banner_id] = src_qns

    all_banner_ids = [b.banner_id for b in banners]
    result = {}
    seen: set[str] = set()

    for q in questions:
        if q.question_number in seen:
            continue
        seen.add(q.question_number)

        role = (q.role or "").lower()
        qtype = (q.question_type or "").upper()

        # Fallback: role이 비어있으면 문항번호 prefix로 추정
        if not role:
            qn_upper = q.question_number.upper()
            if re.match(r'^S\d', qn_upper) or re.match(r'^SQ\d', qn_upper) or re.match(r'^SC\d', qn_upper):
                role = "screening"
            elif re.match(r'^D\d', qn_upper) or re.match(r'^DQ\d', qn_upper) or re.match(r'^F\d', qn_upper):
                role = "demographics"

        # Rule 1-2: screening/demographics → Total only
        if role in ("screening", "demographics"):
            result[q.question_number] = ""
            continue

        # Rule 4: OE → Total only
        if "OE" in qtype or "OPEN" in qtype:
            result[q.question_number] = ""
            continue

        # Rule 3+5: All banners except self-referencing
        applicable = []
        for bid in all_banner_ids:
            if q.question_number not in banner_source_map.get(bid, set()):
                applicable.append(bid)
        result[q.question_number] = ",".join(applicable)

    return result


# ======================================================================
# Phase 3: Sort Order
# ======================================================================

def generate_sort_orders(questions: List[SurveyQuestion]) -> dict:
    """문항 유형별 기본 정렬 규칙 생성 (순수 알고리즘).

    Returns:
        dict: {question_number: sort_order_string}
    """
    result = {}
    seen_qn = set()

    for q in questions:
        if q.question_number in seen_qn:
            continue
        seen_qn.add(q.question_number)

        qtype = (q.question_type or "").strip().upper()

        if "SCALE" in qtype or re.match(r'\d+\s*PT\s*X\s*\d+', qtype):
            result[q.question_number] = "by code"
        elif re.match(r'(?i)(TOP|RANK)\s*\d+', qtype):
            result[q.question_number] = "by % desc"
        elif "MA" in qtype:
            result[q.question_number] = "by % desc"
        elif "OE" in qtype or "OPEN" in qtype:
            result[q.question_number] = "by code"
        else:
            # SA 및 기타
            result[q.question_number] = "by code"

    return result


# ======================================================================
# Phase 3: SubBanner
# ======================================================================

_SUBBANNER_SYSTEM_PROMPT = """You are a DP specialist for marketing research cross-tabulation.
Identify questions that need a SubBanner (secondary analysis dimension), typically for grid/matrix questions.

## Rules
1. Grid/matrix questions (e.g., "5pt x 10" or "SCALE") may need sub-banners
   when they evaluate multiple items that could be analyzed separately.
2. The sub-banner dimension is typically the list of items being rated.
3. Only suggest sub-banners for matrix/grid questions. Return empty for others.
4. Keep the sub-banner description concise.

## JSON Output Format
{
  "results": [
    {"question_number": "Q5", "sub_banner": "Q5 rated items (Taste, Price, Quality, etc.)"},
    {"question_number": "Q6", "sub_banner": ""}
  ]
}"""


def suggest_sub_banners(questions: List[SurveyQuestion],
                        language: str = "ko",
                        survey_context: str = "") -> dict:
    """Grid/매트릭스 문항의 SubBanner 제안.

    Returns:
        dict: {question_number: sub_banner_string}
    """
    result = {}
    matrix_qs = []
    seen_qn = set()

    for q in questions:
        if q.question_number in seen_qn:
            continue
        seen_qn.add(q.question_number)

        qtype = (q.question_type or "").strip().upper()
        if re.match(r'\d+\s*PT\s*X\s*\d+', qtype) or "GRID" in qtype or "MATRIX" in qtype:
            matrix_qs.append(q)
        else:
            result[q.question_number] = ""

    if not matrix_qs:
        return result

    lines = []
    if survey_context:
        lines.append(survey_context)
        lines.append("")
    lines.append("Suggest SubBanner dimensions for these grid/matrix questions:\n")
    for q in matrix_qs:
        lines.append(f"[{q.question_number}] {q.question_text}")
        lines.append(f"  Type: {q.question_type or ''}")
        lines.append(f"  Options: {q.answer_options_compact()}")
        lines.append("")

    user_prompt = "\n".join(lines)

    try:
        raw = call_llm_json(_SUBBANNER_SYSTEM_PROMPT, user_prompt, MODEL_SUBBANNER_SUGGESTER)
        for r in raw.get("results", []):
            qn = str(r.get("question_number", "")).strip()
            sb = str(r.get("sub_banner", "")).strip()
            if qn:
                result[qn] = sb
    except Exception as e:
        logger.error(f"SubBanner suggestion failed: {e}")

    for q in matrix_qs:
        if q.question_number not in result:
            result[q.question_number] = ""

    return result


# ======================================================================
# Phase 4: Special Instructions
# ======================================================================

_SPECIAL_INSTR_SYSTEM_PROMPT = """You are a DP specialist for marketing research.
Generate Special Instructions (programming notes) for survey cross-tabulation tables.

## Rules
1. Detect patterns that need special handling:
   - Rotation/Randomization: "보기 로테이션", "randomize", "rotate"
   - Piping: "pipe from Q3", "Q3에서 가져오기"
   - Open-ended coding: OE questions need coding instructions
   - Weighting: weight variables or quota
   - Multiple response: mention if punching is needed
2. If no special instruction is needed, return empty string.
3. Keep instructions concise and actionable.
4. Write in the same language as the question text.

## JSON Output Format
{
  "results": [
    {"question_number": "Q1", "instruction": "Randomize option order"},
    {"question_number": "Q5", "instruction": "Pipe selected brands from Q3"},
    {"question_number": "Q10", "instruction": ""}
  ]
}"""


def generate_special_instructions(questions: List[SurveyQuestion],
                                  language: str = "ko",
                                  progress_callback=None,
                                  survey_context: str = "") -> dict:
    """Special Instructions 생성 — 패턴 매칭 + LLM.

    Returns:
        dict: {question_number: instruction_string}
    """
    result = {}
    needs_llm = []
    seen_qn = set()

    # 패턴 매칭 키워드
    rotation_patterns = re.compile(
        r'(로테이션|randomiz|rotat|shuffle|무작위)', re.IGNORECASE
    )
    piping_patterns = re.compile(
        r'(pipe|파이핑|가져오기|from\s+[A-Z]+\d+|에서\s+선택)', re.IGNORECASE
    )

    for q in questions:
        if q.question_number in seen_qn:
            continue
        seen_qn.add(q.question_number)

        instructions_text = (q.instructions or "") + " " + (q.question_text or "")
        auto_parts = []

        if rotation_patterns.search(instructions_text):
            auto_parts.append("Randomize option order" if language == "en"
                              else "보기 순서 로테이션")

        if piping_patterns.search(instructions_text):
            auto_parts.append("Pipe from previous question" if language == "en"
                              else "이전 문항에서 파이핑")

        qtype = (q.question_type or "").strip().upper()
        if "OE" in qtype or "OPEN" in qtype:
            auto_parts.append("Open-end coding required" if language == "en"
                              else "주관식 코딩 필요")

        if auto_parts:
            result[q.question_number] = " / ".join(auto_parts)
        else:
            needs_llm.append(q)

    if not needs_llm:
        return result

    # LLM으로 복잡한 패턴 감지
    batches = [needs_llm[i:i + BATCH_SIZE] for i in range(0, len(needs_llm), BATCH_SIZE)]
    total_batches = len(batches)

    for batch_idx, batch in enumerate(batches):
        if progress_callback:
            progress_callback("si_batch_start", {
                "batch_index": batch_idx, "total_batches": total_batches,
                "question_count": len(batch),
            })

        lines = []
        if survey_context:
            lines.append(survey_context)
            lines.append("")
        lines.append("Generate special instructions for these questions if needed:\n")
        for q in batch:
            lines.append(f"[{q.question_number}] {q.question_text}")
            lines.append(f"  Type: {q.question_type or ''}")
            if q.instructions:
                lines.append(f"  Instructions: {q.instructions}")
            if q.answer_options:
                lines.append(f"  Options: {q.answer_options_compact()}")
            lines.append("")

        user_prompt = "\n".join(lines)

        try:
            raw = call_llm_json(
                _SPECIAL_INSTR_SYSTEM_PROMPT, user_prompt, MODEL_SPECIAL_INSTRUCTIONS
            )
            for r in raw.get("results", []):
                qn = str(r.get("question_number", "")).strip()
                instr = str(r.get("instruction", "")).strip()
                if qn:
                    result[qn] = instr
        except Exception as e:
            logger.error(f"Special instructions batch {batch_idx} failed: {e}")

        for q in batch:
            if q.question_number not in result:
                result[q.question_number] = ""

        if progress_callback:
            progress_callback("si_batch_done", {
                "batch_index": batch_idx, "total_batches": total_batches,
            })

    return result


# ======================================================================
# Phase 4: Compile & Export
# ======================================================================

def compile_table_guide(doc: SurveyDocument, project_name: str = "",
                        language: str = "ko") -> TableGuideDocument:
    """전 필드 통합 Table Guide 조립.

    Returns:
        TableGuideDocument
    """
    rows = []
    for q in doc.questions:
        rows.append({
            "QuestionNumber": q.question_number,
            "TableNumber": q.table_number,
            "QuestionText": q.question_text,
            "TableTitle": q.table_title,
            "QuestionType": q.question_type or "",
            "SummaryType": q.summary_type,
            "Base": q.base,
            "NetRecode": q.net_recode,
            "Sort": q.sort_order,
            "SubBanner": q.sub_banner,
            "BannerIDs": q.banner_ids,
            "SpecialInstructions": q.special_instructions,
            "AnswerOptions": q.answer_options_compact(),
            "Filter": q.filter_condition or "",
        })

    return TableGuideDocument(
        project_name=project_name or doc.filename,
        filename=doc.filename,
        generated_at=datetime.now().isoformat(),
        banners=doc.banners,
        rows=rows,
        language=language,
    )


def export_table_guide_excel(tg_doc: TableGuideDocument,
                             survey_doc: SurveyDocument,
                             intelligence: dict | None = None) -> bytes:
    """다중시트 전문 Table Guide Excel 출력.

    Sheets:
        1. Cover — 프로젝트 정보 + Survey Intelligence
        2. Table Guide — 메인 테이블 (Filter 포함)
        3. Banner Spec — 배너 정의
        4. Net/Recode Spec — Net/Recode 상세
        5. Answer Options — 응답 보기
    """
    wb = Workbook()
    header_fill = PatternFill(start_color="0033A0", end_color="0033A0", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    wrap_align = Alignment(wrap_text=True, vertical='top')
    center_align = Alignment(horizontal='center', vertical='center')

    def _style_header(ws):
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center_align

    # ── Sheet 1: Cover ──
    ws_cover = wb.active
    ws_cover.title = "Cover"
    ws_cover.append(["Table Guide"])
    ws_cover['A1'].font = Font(size=18, bold=True)
    ws_cover.append([])
    ws_cover.append(["Project", tg_doc.project_name])
    ws_cover.append(["Source File", tg_doc.filename])
    ws_cover.append(["Generated", tg_doc.generated_at])
    ws_cover.append(["Language", tg_doc.language])
    ws_cover.append(["Total Questions", len(tg_doc.rows)])
    ws_cover.append(["Banners", len(tg_doc.banners)])

    # Survey Intelligence 요약
    intel = intelligence or (survey_doc.survey_intelligence if survey_doc else None)
    if intel:
        ws_cover.append([])
        ws_cover.append(["Survey Intelligence"])
        ws_cover[ws_cover.max_row][0].font = Font(size=14, bold=True)
        if intel.get("client_name"):
            ws_cover.append(["Client", intel["client_name"]])
        if intel.get("study_type"):
            ws_cover.append(["Study Type", intel["study_type"]])
        objectives = intel.get("research_objectives", [])
        if objectives:
            ws_cover.append(["Research Objectives", " | ".join(objectives[:5])])
        segments = intel.get("key_segments", [])
        if segments:
            seg_strs = [f"{s.get('name', '')} ({s.get('type', '')})" for s in segments]
            ws_cover.append(["Key Segments", " | ".join(seg_strs)])
        # Banner 카테고리 요약
        if tg_doc.banners:
            cats = {}
            for b in tg_doc.banners:
                cat = b.category or "Other"
                if cat not in cats:
                    cats[cat] = []
                cats[cat].append(f"{b.banner_id}({b.name})")
            cat_lines = [f"{cat}: {', '.join(names)}" for cat, names in cats.items()]
            ws_cover.append(["Banner Structure", " | ".join(cat_lines)])

    ws_cover.column_dimensions['A'].width = 22
    ws_cover.column_dimensions['B'].width = 80

    # ── Sheet 2: Table Guide ──
    ws_tg = wb.create_sheet("Table Guide")
    tg_headers = [
        "Base", "Sort", "QuestionNumber", "TableNumber", "QuestionText",
        "TableTitle", "SubBanner", "QuestionType", "SummaryType",
        "NetRecode", "BannerIDs", "SpecialInstructions", "Filter",
        "GrammarChecker",
    ]
    ws_tg.append(tg_headers)
    _style_header(ws_tg)

    # GrammarChecker 매핑
    qn_grammar = {}
    for q in survey_doc.questions:
        qn_grammar[q.question_number + "_" + q.table_number] = q.grammar_checked

    for row in tg_doc.rows:
        key = row["QuestionNumber"] + "_" + row["TableNumber"]
        gc = qn_grammar.get(key, "")
        ws_tg.append([
            row.get("Base", ""),
            row.get("Sort", ""),
            row.get("QuestionNumber", ""),
            row.get("TableNumber", ""),
            row.get("QuestionText", ""),
            row.get("TableTitle", ""),
            row.get("SubBanner", ""),
            row.get("QuestionType", ""),
            row.get("SummaryType", ""),
            row.get("NetRecode", ""),
            row.get("BannerIDs", ""),
            row.get("SpecialInstructions", ""),
            row.get("Filter", ""),
            gc,
        ])

    for row in ws_tg.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap_align

    tg_col_widths = [20, 12, 15, 12, 50, 35, 20, 12, 25, 30, 12, 35, 30, 35]
    for i, w in enumerate(tg_col_widths, 1):
        ws_tg.column_dimensions[get_column_letter(i)].width = w

    # ── Sheet 3: Banner Spec (데이터 있을 때만) ──
    if tg_doc.banners:
        ws_banner = wb.create_sheet("Banner Spec")
        ws_banner.append(["Category", "BannerID", "BannerName", "PointLabel",
                           "SourceQuestion", "Condition", "IsNet", "NetDefinition"])
        _style_header(ws_banner)

        for banner in tg_doc.banners:
            for pt in banner.points:
                ws_banner.append([
                    banner.category or "",
                    banner.banner_id,
                    banner.name,
                    pt.label,
                    pt.source_question,
                    pt.condition,
                    "Yes" if pt.is_net else "No",
                    pt.net_definition,
                ])

        banner_col_widths = {'A': 20, 'B': 12, 'C': 22, 'D': 25, 'E': 18, 'F': 30, 'G': 8, 'H': 25}
        for col_letter, w in banner_col_widths.items():
            ws_banner.column_dimensions[col_letter].width = w

    # ── Sheet 4: Net/Recode Spec (데이터 있을 때만) ──
    has_net = any(q.net_recode for q in survey_doc.questions)
    if has_net:
        ws_net = wb.create_sheet("Net Recode Spec")
        ws_net.append(["QuestionNumber", "QuestionType", "NetRecode"])
        _style_header(ws_net)

        seen_qn = set()
        for q in survey_doc.questions:
            if q.question_number in seen_qn:
                continue
            seen_qn.add(q.question_number)
            if q.net_recode:
                ws_net.append([q.question_number, q.question_type or "", q.net_recode])

        ws_net.column_dimensions['A'].width = 18
        ws_net.column_dimensions['B'].width = 15
        ws_net.column_dimensions['C'].width = 50

    # ── Sheet 5: Answer Options ──
    ws_opts = wb.create_sheet("Answer Options")
    ws_opts.append(["QuestionNumber", "OptionCode", "OptionLabel"])
    _style_header(ws_opts)

    for q in survey_doc.questions:
        for opt in q.answer_options:
            ws_opts.append([q.question_number, opt.code, opt.label])

    ws_opts.column_dimensions['A'].width = 18
    ws_opts.column_dimensions['B'].width = 12
    ws_opts.column_dimensions['C'].width = 50

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
