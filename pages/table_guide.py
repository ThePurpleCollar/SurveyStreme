"""Table Guide Builder 페이지.

Phase 1: Table Title 생성 (LLM 배치 + 접미사 알고리즘)
Phase 2: Net/Recode
Phase 3: Banner Management
Phase 4: Review & Export
"""

import logging
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import streamlit as st

from models.survey import Banner, BannerPoint, SurveyDocument, TableGuideDocument
from services.llm_client import call_llm_json, MODEL_TITLE_GENERATOR
from services.survey_context import build_survey_context, enrich_document
from services.table_guide_service import (
    _banner_id_from_index,
    analyze_survey_intelligence,
    assign_banners_to_questions,
    build_dp_handoff_validation_summary,
    compile_table_guide, expand_banner_ids, export_dp_handoff_excel,
    export_table_guide_excel,
    generate_net_recodes,
    generate_sort_orders, generate_special_instructions,
    suggest_banner_points, suggest_sub_banners,
)
from services.table_title_service import (
    build_title_domain_vocabulary as _title_domain_vocabulary,
    normalize_title_by_intent as _normalize_title_by_intent,
    polish_generated_title as _polish_generated_title,
    standard_title_for_question as _standard_title_for_question,
    title_case_mr as _title_case_mr,
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 20
TITLE_BATCH_WORKERS = 3
TABLE_GUIDE_EXPORT_CACHE_VERSION = "table-guide-excel-v1"
DP_HANDOFF_EXPORT_CACHE_VERSION = "dp-handoff-excel-v1"


def _json_dumps_stable(data) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _table_guide_to_json(tg_doc: TableGuideDocument) -> str:
    data = {
        "project_name": tg_doc.project_name,
        "filename": tg_doc.filename,
        "generated_at": tg_doc.generated_at,
        "banners": [b.to_json_dict() for b in tg_doc.banners],
        "rows": tg_doc.rows,
        "language": tg_doc.language,
    }
    return _json_dumps_stable(data)


@st.cache_data(show_spinner=False)
def _export_table_guide_excel_from_json(
    tg_doc_json: str,
    survey_doc_json: str,
    intelligence_json: str,
    cache_version: str,
) -> bytes:
    tg_data = json.loads(tg_doc_json)
    tg_doc = TableGuideDocument(
        project_name=tg_data.get("project_name", ""),
        filename=tg_data.get("filename", ""),
        generated_at=tg_data.get("generated_at", ""),
        banners=[Banner.from_json_dict(b) for b in tg_data.get("banners", [])],
        rows=tg_data.get("rows", []),
        language=tg_data.get("language", "ko"),
    )
    survey_doc = SurveyDocument.from_json_dict(json.loads(survey_doc_json))
    intelligence = json.loads(intelligence_json) if intelligence_json else None
    return export_table_guide_excel(tg_doc, survey_doc, intelligence=intelligence)


def _export_table_guide_excel_cached(tg_doc, survey_doc, intelligence=None) -> bytes:
    return _export_table_guide_excel_from_json(
        _table_guide_to_json(tg_doc),
        _json_dumps_stable(survey_doc.to_json_dict()),
        _json_dumps_stable(intelligence or {}),
        TABLE_GUIDE_EXPORT_CACHE_VERSION,
    )


@st.cache_data(show_spinner=False)
def _export_dp_handoff_excel_from_json(
    tg_doc_json: str,
    survey_doc_json: str,
    intelligence_json: str,
    cache_version: str,
) -> bytes:
    tg_data = json.loads(tg_doc_json)
    tg_doc = TableGuideDocument(
        project_name=tg_data.get("project_name", ""),
        filename=tg_data.get("filename", ""),
        generated_at=tg_data.get("generated_at", ""),
        banners=[Banner.from_json_dict(b) for b in tg_data.get("banners", [])],
        rows=tg_data.get("rows", []),
        language=tg_data.get("language", "ko"),
    )
    survey_doc = SurveyDocument.from_json_dict(json.loads(survey_doc_json))
    intelligence = json.loads(intelligence_json) if intelligence_json else None
    return export_dp_handoff_excel(tg_doc, survey_doc, intelligence=intelligence)


def _export_dp_handoff_excel_cached(tg_doc, survey_doc, intelligence=None) -> bytes:
    return _export_dp_handoff_excel_from_json(
        _table_guide_to_json(tg_doc),
        _json_dumps_stable(survey_doc.to_json_dict()),
        _json_dumps_stable(intelligence or {}),
        DP_HANDOFF_EXPORT_CACHE_VERSION,
    )


def _get_survey_context(df=None) -> str:
    """session_state의 SurveyDocument에서 survey context 생성."""
    doc = st.session_state.get("survey_document")
    if doc:
        brief = st.session_state.get("study_brief")
        return build_survey_context(doc, df=df, confirmed_brief=brief)
    return ""


# ── 시스템 프롬프트 (Phase 1: Title) ─────────────────────────────

_SYSTEM_PROMPT_KO = """당신은 마케팅 리서치 교차분석표(Cross-Table) 제목을 작성하는 DP 전문가입니다.
SPSS 교차분석표에서 사용하는 Table Title을 생성합니다.

## 규칙

1. **핵심 주제 명사구** (2~6단어)만 출력. 설명문·문장형 금지.
2. **표준 MR 용어 사용**:
   - 브랜드 인지: TOM(최초상기), 보조 인지(Aided Awareness)
   - 구매 요인: 핵심 구매 요인(Key Buying Factors)
   - 만족도: 전반적 만족도(Overall Satisfaction), [항목] 만족도
   - 추천 의향: 추천 의향(NPS/Recommendation Intent)
   - 사용 빈도: 사용 빈도(Usage Frequency)
   - 정보 탐색: 정보 탐색 채널(Information Sources)
   - 구매/이용 의향: 향후 구매 의향(Purchase Intent)
3. **QuestionType 활용**:
   - SA/MA → 일반 명사구
   - SCALE, 5pt x N, 7pt x N → "~평가", "~만족도"
   - TopN, RankN → "핵심 ~요인", "~순위"
4. **금지 단어**: '조사', '응답자', '분포', '확인', '~에 대한', '~별'
5. **접미사 금지**: 순위, Summary, Mean 등의 접미사는 시스템이 자동 추가하므로 base title에 포함하지 마세요.
6. **base title만 생성**: 분할 행(TopN 순위, 매트릭스 Summary 등)의 접미사는 시스템이 추가합니다. 순수한 주제 명사구만 생성하세요.
7. **질문 요약 금지**: 질문 문구를 그대로 줄이지 말고, 조사 유형/도메인에서 쓰는 Table Title 용어로 변환하세요.
8. **설문 전체 맥락 활용**: Survey Context가 제공되면, 해당 문항이 설문 전체에서 어떤 역할(인지→경험→평가→의향 등)을 하는지 파악하여 더 정확하고 구체적인 제목을 생성하세요.
9. **의도 기반 명명**:
   - "important when buying/choosing/considering" → 핵심 구매 요인(Key Buying Factors)
   - "why choose/purchase/use" → 선택 이유/구매 이유
   - "aware/know/heard of" → 보조 인지(Aided Awareness)
   - "consider/willing/likely to buy" → 구매 의향(Purchase Intent) 또는 브랜드 고려
   - "satisfied/recommend" → 만족도/NPS

## JSON 출력 형식

{
  "results": [
    {
      "question_number": "Q1",
      "title": "보조 인지 브랜드",
      "reasoning": "보조 인지를 측정하는 MA 문항"
    }
  ]
}"""

_SYSTEM_PROMPT_EN = """You are a DP specialist who writes Cross-Table titles for marketing research.
You generate Table Titles used in SPSS cross-tabulation tables.

## Rules

1. **Core topic noun phrase** (2-6 words) only. No sentences or descriptions.
2. **Use standard MR terminology**:
   - Brand awareness: TOM (Top of Mind), Aided Awareness
   - Purchase drivers: Key Buying Factors
   - Satisfaction: Overall Satisfaction, [Aspect] Satisfaction
   - Recommendation: Likelihood to Recommend / NPS
   - Usage frequency: Usage Frequency
   - Information sources: Information Sources
   - Purchase intent: Purchase Intent / Future Usage Intent
3. **Use QuestionType**:
   - SA/MA → general noun phrase
   - SCALE, 5pt x N, 7pt x N → "~ Rating", "~ Satisfaction"
   - TopN, RankN → "Key ~ Factors", "~ Ranking"
4. **Forbidden words**: 'survey', 'respondent', 'distribution', 'check', 'about', 'by'
5. **No suffixes**: Ranking, Summary, Mean suffixes are added by the system automatically. Do NOT include them in the base title.
6. **Base title only**: Split-row suffixes (TopN ranks, matrix Summary, etc.) are added by the system. Generate only the pure topic noun phrase.
7. **Do not summarize question wording literally**: Convert the question intent into a standard domain/MR table-title term.
8. **Use survey context**: When Survey Context is provided, understand each question's role in the overall study flow (e.g., awareness → usage → evaluation → intent) to generate more precise and contextually appropriate titles.
9. **Intent-based naming**:
   - "important when buying/choosing/considering" → Key Buying Factors
   - "why choose/purchase/use" → Choice Reasons / Purchase Reasons
   - "aware/know/heard of" → Aided Awareness
   - "consider/willing/likely to buy" → Purchase Intent or Brand Consideration
   - "satisfied/recommend" → Satisfaction / NPS

## JSON Output Format

{
  "results": [
    {
      "question_number": "Q1",
      "title": "Aided Brand Awareness",
      "reasoning": "MA question measuring aided awareness"
    }
  ]
}"""


# ======================================================================
# Phase 1: Title Generation Helpers (기존 로직 유지)
# ======================================================================

def _group_rows_by_question(df: pd.DataFrame) -> list:
    """DataFrame 행을 QuestionNumber 기준으로 그룹화."""
    groups = []
    seen = {}
    doc_questions = {
        q.question_number: q
        for q in _get_questions()
    }

    for _, row in df.iterrows():
        qn = str(row.get("QuestionNumber", "")).strip()
        if not qn:
            continue

        if qn not in seen:
            q = doc_questions.get(qn)
            text = str(row.get("QuestionText", "")).strip()
            qtype = str(row.get("QuestionType", "")).strip()
            options = str(row.get("AnswerOptions", "")).strip() if "AnswerOptions" in df.columns else ""
            filt = str(row.get("Filter", "")).strip() if "Filter" in df.columns else ""
            instructions = str(row.get("Instructions", "")).strip() if "Instructions" in df.columns else ""
            source_var = str(row.get("SourceVariable", "")).strip() if "SourceVariable" in df.columns else ""
            if q:
                instructions = instructions or (q.instructions or "")
                source_var = source_var or (getattr(q, "source_variable", "") or "")
                role = q.role or ""
                variable_type = q.variable_type or ""
                analytical_value = q.analytical_value or ""
                skip_logic = q.skip_logic_display()
            else:
                role = variable_type = analytical_value = skip_logic = ""

            seen[qn] = len(groups)
            groups.append({
                "qn": qn,
                "source_variable": source_var,
                "text": text,
                "qtype": qtype,
                "options": options,
                "filter": filt,
                "instructions": instructions,
                "skip_logic": skip_logic,
                "role": role,
                "variable_type": variable_type,
                "analytical_value": analytical_value,
                "summary_types": [],
                "table_numbers": [],
            })

        idx = seen[qn]
        st_val = str(row.get("SummaryType", "")).strip()
        tn_val = str(row.get("TableNumber", "")).strip()
        groups[idx]["summary_types"].append(st_val)
        groups[idx]["table_numbers"].append(tn_val)

    for g in groups:
        g["row_count"] = len(g["table_numbers"])

    return groups


def _format_question_for_prompt(item: dict) -> str:
    parts = [f"[{item['qn']}]"]
    if item.get("source_variable"):
        parts.append(f"SourceVariable: {item['source_variable']}")
    parts.append(f"Text: {item['text']}")
    if item["qtype"]:
        parts.append(f"Type: {item['qtype']}")
    if item.get("role"):
        parts.append(f"Role: {item['role']}")
    if item.get("variable_type"):
        parts.append(f"VariableType: {item['variable_type']}")
    if item.get("analytical_value"):
        parts.append(f"AnalyticalValue: {item['analytical_value']}")
    if item["options"]:
        parts.append(f"Options: {item['options']}")
    unique_st = list(dict.fromkeys(s for s in item["summary_types"] if s))
    if unique_st:
        parts.append(f"SummaryTypes: {', '.join(unique_st)}")
    parts.append(f"Split Rows: {item['row_count']}")
    if item["filter"]:
        parts.append(f"Filter: {item['filter']}")
    if item.get("instructions"):
        parts.append(f"Instructions: {item['instructions']}")
    if item.get("skip_logic"):
        parts.append(f"SkipLogic: {item['skip_logic']}")
    return "\n".join(parts)


def _build_batch_prompt(batch: list, survey_context: str = "", language: str = "en") -> str:
    parts = []
    if survey_context:
        parts.append(survey_context)
        parts.append("")
    parts.append(_title_domain_vocabulary(survey_context, language))
    parts.append("Generate cross-table titles for the following survey questions:")
    parts.append("")
    sections = [_format_question_for_prompt(item) for item in batch]
    parts.append("\n\n---\n\n".join(sections))
    return "\n".join(parts)


def _parse_batch_result(raw: dict, batch: list) -> dict:
    results_raw = raw.get("results", [])
    parsed = {}
    for r in results_raw:
        qn = str(r.get("question_number", "")).strip()
        if not qn:
            continue
        title = str(r.get("title", "")).strip()
        reasoning = str(r.get("reasoning", "")).strip()
        parsed[qn] = {"title": title, "reasoning": reasoning}
    for item in batch:
        if item["qn"] not in parsed:
            parsed[item["qn"]] = {"title": "", "reasoning": ""}
    return parsed


def _ordinal_cumulative(n: int, language: str) -> str:
    if language == "ko":
        if n == 1:
            return "1순위"
        return "+".join(str(i) for i in range(1, n + 1)) + "순위"
    else:
        ordinals = {1: "1st", 2: "2nd", 3: "3rd"}
        parts = []
        for i in range(1, n + 1):
            parts.append(ordinals.get(i, f"{i}th"))
        return "+".join(parts)


def _is_topn_type(qtype: str) -> bool:
    if not qtype:
        return False
    return bool(re.match(r'(?i)(top|rank)\s*\d+', qtype))


def _is_matrix_type(qtype: str) -> bool:
    if not qtype:
        return False
    return bool(re.match(r'(?i)\d+\s*pt\s*x\s*\d+', qtype))


def _apply_suffixes(base_title: str, qtype: str, summary_types: list,
                    table_numbers: list, language: str) -> list:
    row_count = len(table_numbers)
    results = []

    if row_count == 1:
        return [{"table_number": table_numbers[0], "suffix": "", "final_title": base_title}]

    if _is_topn_type(qtype):
        for i, (tn, st) in enumerate(zip(table_numbers, summary_types)):
            if st:
                suffix = f" - {st}"
            else:
                suffix = f" - {_ordinal_cumulative(i + 1, language)}"
            results.append({"table_number": tn, "suffix": suffix, "final_title": f"{base_title}{suffix}"})
        return results

    for i, (tn, st) in enumerate(zip(table_numbers, summary_types)):
        if st:
            suffix = f" - {st}"
        else:
            suffix = f" - ({i + 1})"
        results.append({"table_number": tn, "suffix": suffix, "final_title": f"{base_title}{suffix}"})
    return results


def _expand_results_to_rows(base_titles: dict, groups: list, language: str) -> list:
    all_results = []
    for g in groups:
        qn = g["qn"]
        info = base_titles.get(qn, {"title": "", "reasoning": ""})
        base_title = _normalize_title_by_intent(info["title"], g, language)
        reasoning = info["reasoning"]
        error = not bool(base_title)
        rows = _apply_suffixes(base_title, g["qtype"], g["summary_types"], g["table_numbers"], language)
        all_results.append({
            "question_number": qn, "base_title": base_title, "reasoning": reasoning,
            "qtype": g["qtype"], "rows": rows, "is_split": g["row_count"] > 1,
            "row_count": g["row_count"], "error": error,
        })
    return all_results


def _run_title_generation(df: pd.DataFrame, language: str, progress_callback,
                          survey_context: str = "") -> list:
    groups = _group_rows_by_question(df)
    if not groups:
        return []

    system_prompt = _SYSTEM_PROMPT_KO if language == "ko" else _SYSTEM_PROMPT_EN
    batches = [groups[i:i + BATCH_SIZE] for i in range(0, len(groups), BATCH_SIZE)]
    total_batches = len(batches)
    all_base_titles = {}

    def _generate_batch(batch_idx: int, batch: list) -> tuple[int, dict]:
        user_prompt = _build_batch_prompt(batch, survey_context, language)
        try:
            raw = call_llm_json(system_prompt, user_prompt, MODEL_TITLE_GENERATOR)
            parsed = _parse_batch_result(raw, batch)
        except Exception as e:
            logger.error(f"Title batch {batch_idx} failed: {e}")
            parsed = {item["qn"]: {"title": "", "reasoning": f"Error: {e}"} for item in batch}
        return batch_idx, parsed

    max_workers = min(total_batches, TITLE_BATCH_WORKERS)
    progress_callback("run_start", {
        "total_batches": total_batches,
        "question_count": len(groups),
        "workers": max_workers,
    })
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_generate_batch, batch_idx, batch): batch_idx
            for batch_idx, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            batch_idx, parsed = future.result()
            all_base_titles.update(parsed)
            progress_callback("batch_done", {
                "batch_index": batch_idx, "total_batches": total_batches,
                "generated_count": sum(1 for v in parsed.values() if v["title"]),
            })

    return _expand_results_to_rows(all_base_titles, groups, language)


def _apply_results_to_df(results: list):
    if "edited_df" not in st.session_state:
        return
    df = st.session_state["edited_df"]
    tn_to_title = {}
    for r in results:
        for row in r["rows"]:
            tn_to_title[row["table_number"]] = row["final_title"]
    qn_to_title = {}
    for r in results:
        qn_to_title[r["question_number"]] = r["base_title"]

    if "TableTitle" not in df.columns:
        df["TableTitle"] = ""
    for idx, row in df.iterrows():
        tn = str(row.get("TableNumber", "")).strip()
        qn = str(row.get("QuestionNumber", "")).strip()
        if tn and tn in tn_to_title:
            df.at[idx, "TableTitle"] = tn_to_title[tn]
        elif qn and qn in qn_to_title:
            df.at[idx, "TableTitle"] = qn_to_title[qn]
    st.session_state["edited_df"] = df

    if "survey_document" in st.session_state and st.session_state["survey_document"]:
        for q in st.session_state["survey_document"].questions:
            tn = q.table_number
            qn = q.question_number
            if tn and tn in tn_to_title:
                q.table_title = tn_to_title[tn]
            elif qn and qn in qn_to_title:
                q.table_title = qn_to_title[qn]


# ======================================================================
# Shared Helpers
# ======================================================================

def _get_questions():
    """session_state에서 SurveyQuestion 리스트를 가져온다."""
    doc = st.session_state.get("survey_document")
    if doc and doc.questions:
        return doc.questions
    return []


def _sync_field_to_df_and_doc(field_map: dict, df_col: str, doc_attr: str):
    """field_map {question_number: value}를 edited_df와 survey_document에 반영.

    같은 question_number를 가진 모든 행에 동일 값 적용.
    """
    if "edited_df" in st.session_state:
        df = st.session_state["edited_df"]
        if df_col not in df.columns:
            df[df_col] = ""
        for idx, row in df.iterrows():
            qn = str(row.get("QuestionNumber", "")).strip()
            if qn in field_map:
                df.at[idx, df_col] = field_map[qn]
        st.session_state["edited_df"] = df

    if "survey_document" in st.session_state and st.session_state["survey_document"]:
        for q in st.session_state["survey_document"].questions:
            if q.question_number in field_map:
                setattr(q, doc_attr, field_map[q.question_number])


def _apply_banner_generation_result(questions: list, doc, suggested: list, plan: dict | None) -> dict:
    """Persist generated banners and assign them to questions."""
    suggested_count = len(suggested or [])
    logger.info(
        "Applying banner generation result: suggested=%s, has_doc=%s, has_plan=%s",
        suggested_count,
        bool(doc),
        bool(plan),
    )

    if suggested and doc:
        existing = doc.banners or []
        existing_pts = sum(len(b.points) for b in existing)
        new_pts = sum(len(b.points) for b in suggested)
        if existing_pts > 0 and new_pts < existing_pts and len(suggested) < len(existing):
            logger.warning(
                f"Keeping existing banners ({len(existing)} banners, {existing_pts} pts) "
                f"over new result ({len(suggested)} banners, {new_pts} pts)"
            )
        else:
            doc.banners = suggested

    if plan:
        st.session_state["banner_analysis_plan"] = plan
        rp = plan.get("_research_plan")
        if rp:
            st.session_state["banner_research_plan"] = rp
        eo = plan.get("_expert_outputs")
        if eo:
            st.session_state["banner_expert_outputs"] = eo
        st.session_state["banner_consensus_score"] = plan.get("agreement_score", 0)

    if suggested:
        st.session_state["banners_suggested"] = True

    assigned_count = 0
    if doc and doc.banners:
        banner_assign_map = assign_banners_to_questions(questions, doc.banners)
        _sync_field_to_df_and_doc(banner_assign_map, "BannerIDs", "banner_ids")
        assigned_count = sum(1 for v in banner_assign_map.values() if str(v).strip())

    stats = {
        "banners": len(doc.banners) if doc and doc.banners else 0,
        "assigned": assigned_count,
    }
    logger.info(
        "Banner apply complete: banners=%s, assigned_questions=%s",
        stats["banners"],
        stats["assigned"],
    )
    return stats


def _run_banner_generation_only(df: pd.DataFrame, language: str):
    """Generate banners from the selected-item workflow."""
    questions = _get_questions()
    doc = st.session_state.get("survey_document")
    logger.info(
        "Banner generation requested: questions=%s, has_doc=%s, language=%s",
        len(questions or []),
        bool(doc),
        language,
    )
    if not questions or not doc:
        logger.warning("Banner generation skipped: missing questions or survey_document")
        st.warning("배너 생성을 위해서는 먼저 Questionnaire Analyzer에서 DOCX를 추출해야 합니다.")
        return False

    phase_labels = {
        "intelligence": "Survey Intelligence 분석",
        "research_plan": "Research Plan 작성",
        "expert_panel": "전문가 패널 분석",
        "synthesis": "전문가 의견 종합",
        "banner_design": "배너 설계",
        "validation": "배너 검증",
        "assign": "문항별 배너 할당",
    }
    phase_progress = {
        "intelligence": 0.08,
        "research_plan": 0.18,
        "expert_panel": 0.38,
        "synthesis": 0.56,
        "banner_design": 0.74,
        "validation": 0.90,
        "assign": 0.96,
    }

    with st.status("Banner 생성 중...", expanded=True) as status:
        progress_bar = st.progress(0.0)
        phase_line = st.empty()
        detail_line = st.empty()
        start_time = time.time()

        def _format_elapsed() -> str:
            elapsed = int(time.time() - start_time)
            m, s = divmod(elapsed, 60)
            return f"{m}:{s:02d}"

        def _banner_progress(event, data):
            if event == "phase":
                name = data.get("name", "")
                label = phase_labels.get(name, name or "처리")
                state = data.get("status", "")
                progress = phase_progress.get(name, 0.1)
                if state == "done":
                    progress = min(progress + 0.06, 0.98)
                progress_bar.progress(progress)
                phase_line.write(f"{label} {state or 'running'}")
                detail_line.write(f"경과 {_format_elapsed()} | 배너 생성을 진행 중입니다.")
            elif event == "expert_done":
                name = data.get("name", "Expert")
                status_text = "완료" if data.get("success") else "실패"
                detail_line.write(f"{name} {status_text} | 경과 {_format_elapsed()}")

        try:
            intelligence = doc.survey_intelligence if doc else {}
            if not intelligence:
                _banner_progress("phase", {"name": "intelligence", "status": "start"})
                intelligence = analyze_survey_intelligence(
                    questions,
                    language,
                    client_brand=doc.client_brand if doc else "",
                    study_objective=doc.study_objective if doc else "",
                )
                enrich_document(doc, intelligence)
                _banner_progress("phase", {"name": "intelligence", "status": "done"})

            brief = st.session_state.get("study_brief")
            survey_ctx = build_survey_context(doc, df=df, confirmed_brief=brief)

            suggested, plan = suggest_banner_points(
                questions,
                language,
                survey_context=survey_ctx,
                intelligence=intelligence,
                progress_callback=_banner_progress,
            )
            logger.info(
                "Banner suggestion returned: suggested=%s, has_plan=%s",
                len(suggested or []),
                bool(plan),
            )

            _banner_progress("phase", {"name": "assign", "status": "start"})
            stats = _apply_banner_generation_result(questions, doc, suggested, plan)
            _banner_progress("phase", {"name": "assign", "status": "done"})

            progress_bar.progress(1.0)
            if stats["banners"] > 0:
                status.update(
                    label=(
                        f"Banner 생성 완료 — {stats['banners']}개 배너, "
                        f"{stats['assigned']}개 문항 할당"
                    ),
                    state="complete",
                )
                st.success(
                    f"배너 {stats['banners']}개를 생성했고 "
                    f"{stats['assigned']}개 문항에 할당했습니다."
                )
                st.session_state["banner_generation_notice"] = (
                    f"배너 {stats['banners']}개 생성, {stats['assigned']}개 문항 할당"
                )
                return True
            else:
                status.update(label="Banner 생성 결과 없음", state="error")
                st.warning(
                    "배너 생성이 완료되었지만 적용 가능한 배너가 없었습니다. "
                    "Study Brief와 추출 문항을 확인한 뒤 다시 시도해주세요."
                )
                return False
        except Exception as e:
            status.update(label="Banner 생성 실패", state="error")
            logger.error(f"Banner generation failed: {e}", exc_info=True)
            st.error(f"Banner 생성 실패: {e}")
            return False


def _compute_completeness():
    """탭 라벨 및 상단 진행률 표시를 위한 완성도 계산."""
    doc = st.session_state.get("survey_document")
    df = st.session_state.get("edited_df")
    stats = {"total": 0, "titles": 0, "nets": 0,
             "banners": 0, "banner_assigned": 0, "sorts": 0,
             "special_instructions": 0}

    if doc and doc.questions:
        seen = set()
        unique_qs = []
        for q in doc.questions:
            if q.question_number not in seen:
                seen.add(q.question_number)
                unique_qs.append(q)
        stats["total"] = len(unique_qs)
        stats["titles"] = sum(1 for q in unique_qs if q.table_title)
        stats["nets"] = sum(1 for q in unique_qs if q.net_recode)
        stats["banners"] = len(doc.banners)
        stats["banner_assigned"] = sum(1 for q in unique_qs if q.banner_ids)
        stats["sorts"] = sum(1 for q in unique_qs if q.sort_order)
        stats["special_instructions"] = sum(1 for q in unique_qs if q.special_instructions)
    elif df is not None and not df.empty:
        stats["total"] = df["QuestionNumber"].nunique()
        for col, key in [("TableTitle", "titles"), ("NetRecode", "nets")]:
            if col in df.columns:
                filled = df[df[col].astype(str).str.strip() != ""]
                stats[key] = filled["QuestionNumber"].nunique()

    return stats


def _tab_label(name: str, count: int, total: int) -> str:
    """완성도 기반 탭 라벨 생성."""
    if total == 0 or count == 0:
        return name
    if count >= total:
        return f"{name} \u2713"
    return f"{name} ({count}/{total})"


# ======================================================================
# Tab 1: Table Titles UI
# ======================================================================

def _render_title_dashboard(results: list):
    unique_q = len(results)
    generated = sum(1 for r in results if not r["error"])
    split_rows = sum(r["row_count"] for r in results if r["is_split"])
    errors = sum(1 for r in results if r["error"])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Unique Questions", unique_q)
    with col2:
        st.metric("Titles Generated", generated)
    with col3:
        st.metric("Split Rows", split_rows)
    with col4:
        st.metric("Errors", errors)


def _render_title_comparison(results: list, filter_mode: str):
    filtered = results
    if filter_mode == "Split Only":
        filtered = [r for r in results if r["is_split"]]
    elif filter_mode == "Non-Split Only":
        filtered = [r for r in results if not r["is_split"]]
    elif filter_mode == "Errors Only":
        filtered = [r for r in results if r["error"]]

    if not filtered:
        st.info("선택한 필터에 해당하는 문항이 없습니다.")
        return

    for r in filtered:
        qn = r["question_number"]
        base = r["base_title"]
        is_split = r["is_split"]
        row_count = r["row_count"]

        if r["error"]:
            label = f'\U0001f534 {qn}: Error'
        elif is_split:
            label = f'\U0001f517 {qn}: "{base}" ({row_count} rows)'
        else:
            label = f'\u2705 {qn}: "{base}"'

        with st.expander(label, expanded=is_split and not r["error"]):
            if r["error"]:
                st.error(f"Failed to generate title: {r['reasoning']}")
                continue
            st.markdown(f"**Base Title:** {base}")
            if r["reasoning"]:
                st.caption(f"Reasoning: {r['reasoning']}")
            if is_split:
                st.markdown("---")
                row_data = [
                    {"TableNumber": row["table_number"],
                     "Suffix": row["suffix"] if row["suffix"] else "(none)",
                     "Final Title": row["final_title"]}
                    for row in r["rows"]
                ]
                st.dataframe(pd.DataFrame(row_data), hide_index=True, use_container_width=True)


def _render_title_editable_table():
    if "edited_df" not in st.session_state:
        return
    df = st.session_state["edited_df"]
    display_cols = ["QuestionNumber", "TableNumber", "QuestionText",
                    "TableTitle", "QuestionType", "SummaryType"]
    display_cols = [c for c in display_cols if c in df.columns]

    edited = st.data_editor(
        df[display_cols], height=600, hide_index=True,
        num_rows="dynamic", key="title_editor", use_container_width=True,
    )

    if st.button("수정사항 적용", type="primary", key="apply_title_edits"):
        for col in display_cols:
            st.session_state["edited_df"][col] = edited[col]
        if "survey_document" in st.session_state and st.session_state["survey_document"]:
            tn_to_title = dict(zip(edited["TableNumber"], edited["TableTitle"]))
            for q in st.session_state["survey_document"].questions:
                if q.table_number in tn_to_title:
                    q.table_title = str(tn_to_title[q.table_number])
        st.success("수정사항이 적용되었습니다!")
        st.rerun()


def _tab_table_titles(df: pd.DataFrame, language: str):
    """Tab 1: Table Titles."""
    groups = _group_rows_by_question(df)
    total_unique = len(groups)
    total_rows = len(df)
    split_count = sum(1 for g in groups if g["row_count"] > 1)
    split_rows = sum(g["row_count"] for g in groups if g["row_count"] > 1)

    st.info(
        f"고유 문항 **{total_unique}**개 "
        f"(총 **{total_rows}**행, **{split_count}**개 문항에서 **{split_rows}**행 분할). "
        "**Table Title 생성** 버튼을 눌러 제목을 생성하세요.",
        icon="\u2139\ufe0f",
    )

    generate_clicked = st.button("Table Title 생성", type="primary", key="generate_titles_btn")

    if generate_clicked:
        with st.status("Table Title 생성 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()
            batch_done_count = [0]
            total_batches_ref = [1]

            def _progress_callback(event, data):
                if event == "run_start":
                    total_batches_ref[0] = data["total_batches"]
                    log_area.text(
                        f"{data['total_batches']}개 배치를 병렬 처리 중 "
                        f"({data['question_count']}개 문항, worker {data['workers']}개)..."
                    )
                elif event == "batch_done":
                    total_batches_ref[0] = data["total_batches"]
                    batch_done_count[0] += 1
                    progress_bar.progress(batch_done_count[0] / total_batches_ref[0])
                    log_area.text(
                        f"배치 {data['batch_index'] + 1}/{data['total_batches']} 완료 "
                        f"({data['generated_count']}개 생성) · "
                        f"{batch_done_count[0]}/{data['total_batches']} 완료"
                    )

            questions = _get_questions()
            survey_ctx = _get_survey_context(df=df)
            results = _run_title_generation(df, language, _progress_callback,
                                            survey_context=survey_ctx)
            st.session_state["title_results"] = results
            _apply_results_to_df(results)
            generated_count = sum(1 for r in results if not r["error"])
            status.update(
                label=f"Title 생성 완료! {generated_count}/{len(results)}개 생성됨.",
                state="complete",
            )

    if "title_results" not in st.session_state:
        if "TableTitle" not in df.columns:
            df["TableTitle"] = ""
            st.session_state["edited_df"] = df
        _render_title_editable_table()
        return

    results = st.session_state["title_results"]
    if not results:
        return

    st.divider()
    _render_title_dashboard(results)
    _render_title_editable_table()


# ======================================================================
# Tab 2: Net/Recode
# ======================================================================

def _tab_net_recode(df: pd.DataFrame, language: str):
    """Tab 2: Net/Recode."""
    questions = _get_questions()
    if not questions:
        st.warning("문항 데이터가 없습니다. Questionnaire Analyzer에서 먼저 문서를 처리해주세요.")
        return

    generate_clicked = st.button("Net/Recode 생성", type="primary",
                                 key="generate_net_btn")

    if generate_clicked:
        with st.status("Net/Recode 생성 중...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()

            def _progress_cb(event, data):
                if "batch_start" in event:
                    log_area.text(f"[{event}] Batch {data['batch_index']+1}/{data['total_batches']}...")
                elif "batch_done" in event:
                    progress_bar.progress(1.0)

            survey_ctx = _get_survey_context(df=df)

            log_area.text("Net/Recode 제안 생성 중...")
            net_map = generate_net_recodes(questions, language, _progress_cb,
                                           survey_context=survey_ctx)
            _sync_field_to_df_and_doc(net_map, "NetRecode", "net_recode")

            progress_bar.progress(1.0)
            st.session_state["net_generated"] = True
            status.update(label="Net/Recode 생성 완료!", state="complete")

    # Dashboard 메트릭
    if st.session_state.get("net_generated") or st.session_state.get("base_net_generated"):
        st.divider()

        doc = st.session_state.get("survey_document")
        if doc:
            seen = set()
            net_count = 0
            no_net_count = 0
            for q in doc.questions:
                if q.question_number in seen:
                    continue
                seen.add(q.question_number)
                if q.net_recode:
                    net_count += 1
                else:
                    no_net_count += 1

            c1, c2 = st.columns(2)
            with c1:
                st.metric("Net/Recode 있음", net_count)
            with c2:
                st.metric("Net/Recode 없음", no_net_count)

        bn_filter = st.radio(
            "필터", options=["All", "Scale Only", "Custom Net"],
            format_func=lambda x: {"All": "전체", "Scale Only": "척도만", "Custom Net": "커스텀 Net"}[x],
            horizontal=True, key="bn_filter_radio",
        )

        # Expander 비교 뷰
        doc = st.session_state.get("survey_document")
        if doc:
            seen = set()
            for q in doc.questions:
                if q.question_number in seen:
                    continue
                seen.add(q.question_number)

                if bn_filter == "Scale Only":
                    qtype_upper = (q.question_type or "").upper()
                    if "SCALE" not in qtype_upper and not re.match(r'\d+\s*PT\s*X\s*\d+', qtype_upper):
                        continue
                if bn_filter == "Custom Net" and not q.net_recode:
                    continue

                label = f"{q.question_number}"
                if q.net_recode:
                    label += f": Net={q.net_recode}"

                with st.expander(label, expanded=False):
                    st.markdown(f"**Question:** {q.question_text}")
                    st.markdown(f"**Type:** {q.question_type or 'N/A'}")
                    if q.filter_condition:
                        st.caption(f"Filter: {q.filter_condition}")
                    st.markdown(f"**Net/Recode:** {q.net_recode or '(none)'}")

    # Editable Table
    st.divider()
    st.subheader("편집 테이블")

    display_cols = ["QuestionNumber", "TableNumber", "NetRecode", "SummaryType"]
    display_cols = [c for c in display_cols if c in df.columns]

    if display_cols:
        edited = st.data_editor(
            df[display_cols], height=600, hide_index=True,
            num_rows="dynamic", key="bn_editor", use_container_width=True,
        )

        if st.button("수정사항 적용", type="primary", key="apply_bn_edits"):
            for col in display_cols:
                st.session_state["edited_df"][col] = edited[col]
            if "survey_document" in st.session_state and st.session_state["survey_document"]:
                qn_net = {}
                for _, row in edited.iterrows():
                    qn = str(row.get("QuestionNumber", "")).strip()
                    if qn:
                        qn_net[qn] = str(row.get("NetRecode", ""))
                for q in st.session_state["survey_document"].questions:
                    if q.question_number in qn_net:
                        q.net_recode = qn_net[q.question_number]
            st.success("수정사항이 적용되었습니다!")
            st.rerun()


# ======================================================================
# Shared: BannerIDs readable display
# ======================================================================

def _expand_banner_ids(banner_ids_str: str) -> str:
    """'A,B,C' → 'A(Gender), B(Age), C(Ownership)' 변환.

    doc.banners에서 배너 이름을 조회하여 사람이 읽을 수 있는 형태로 변환.
    서비스 레이어의 expand_banner_ids()에 위임.
    """
    doc = st.session_state.get("survey_document")
    if not doc or not doc.banners:
        return banner_ids_str or ""
    return expand_banner_ids(banner_ids_str, doc.banners)


def _banner_id_name_map() -> dict:
    """현재 session의 배너 ID→이름 맵 반환."""
    doc = st.session_state.get("survey_document")
    if not doc or not doc.banners:
        return {}
    return {b.banner_id: b.name for b in doc.banners}


# ======================================================================
# Tab 3: Sort & Details
# ======================================================================

def _tab_sort_details(df: pd.DataFrame, language: str):
    """Tab 3: Sort Order, SubBanner, BannerIDs, Special Instructions 편집."""
    questions = _get_questions()
    if not questions:
        st.warning("문항 데이터가 없습니다. Questionnaire Analyzer에서 먼저 문서를 처리해주세요.")
        return

    # ── 개별 생성 버튼 ──
    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        sort_clicked = st.button("Sort 생성", key="gen_sort_btn")
    with btn_col2:
        sub_clicked = st.button("SubBanner 생성", key="gen_sub_btn")
    with btn_col3:
        si_clicked = st.button("Special Inst. 생성", key="gen_si_btn")

    survey_ctx = _get_survey_context(df=df)

    if sort_clicked:
        with st.spinner("Sort 순서 생성 중..."):
            sort_map = generate_sort_orders(questions)
            _sync_field_to_df_and_doc(sort_map, "Sort", "sort_order")
            st.session_state["sort_generated"] = True
            st.rerun()

    if sub_clicked:
        with st.spinner("SubBanner 생성 중..."):
            sub_map = suggest_sub_banners(questions, language,
                                           survey_context=survey_ctx)
            _sync_field_to_df_and_doc(sub_map, "SubBanner", "sub_banner")
            st.session_state["subbanner_generated"] = True
            st.rerun()

    if si_clicked:
        with st.spinner("Special Instructions 생성 중..."):
            si_map = generate_special_instructions(questions, language,
                                                    survey_context=survey_ctx)
            _sync_field_to_df_and_doc(si_map, "SpecialInstructions", "special_instructions")
            st.session_state["si_generated"] = True
            st.rerun()

    # ── Dashboard ──
    doc = st.session_state.get("survey_document")
    if doc:
        seen = set()
        sort_count = sub_count = si_count = banner_count = 0
        unique_total = 0
        for q in doc.questions:
            if q.question_number in seen:
                continue
            seen.add(q.question_number)
            unique_total += 1
            if q.sort_order:
                sort_count += 1
            if q.sub_banner:
                sub_count += 1
            if q.special_instructions:
                si_count += 1
            if q.banner_ids:
                banner_count += 1

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Sort", f"{sort_count}/{unique_total}")
        with c2:
            st.metric("SubBanner", f"{sub_count}/{unique_total}")
        with c3:
            st.metric("Banner Assigned", f"{banner_count}/{unique_total}")
        with c4:
            st.metric("Special Instr.", f"{si_count}/{unique_total}")

    # ── Filter radio ──
    detail_filter = st.radio(
        "필터", options=["All", "With SubBanner", "With Special Inst.", "No Banners"],
        format_func=lambda x: {"All": "전체", "With SubBanner": "SubBanner 있음", "With Special Inst.": "Special Inst. 있음", "No Banners": "배너 미할당"}[x],
        horizontal=True, key="detail_filter_radio",
    )

    # ── Expander 비교 뷰 ──
    bid_name_map = _banner_id_name_map()
    if doc:
        seen = set()
        for q in doc.questions:
            if q.question_number in seen:
                continue
            seen.add(q.question_number)

            # 필터
            if detail_filter == "With SubBanner" and not q.sub_banner:
                continue
            if detail_filter == "With Special Inst." and not q.special_instructions:
                continue
            if detail_filter == "No Banners" and q.banner_ids:
                continue

            # 라벨 구성
            parts = [q.question_number]
            if q.sort_order:
                parts.append(f"Sort={q.sort_order}")
            if q.banner_ids:
                parts.append(f"Banners={q.banner_ids}")
            label = " | ".join(parts)

            with st.expander(label, expanded=False):
                st.markdown(f"**Question:** {(q.question_text or '')[:120]}")
                st.markdown(f"**Type:** {q.question_type or 'N/A'}")
                st.markdown(f"**Sort:** {q.sort_order or '(none)'}")
                st.markdown(f"**SubBanner:** {q.sub_banner or '(none)'}")
                # BannerIDs readable
                if q.banner_ids:
                    expanded = _expand_banner_ids(q.banner_ids)
                    st.markdown(f"**Banner IDs:** {expanded}")
                else:
                    st.markdown("**Banner IDs:** (Total only)")
                st.markdown(f"**Special Instructions:** {q.special_instructions or '(none)'}")

    # ── Editable Table ──
    st.divider()
    st.subheader("편집 테이블")

    display_cols = ["QuestionNumber", "QuestionType", "Sort", "SubBanner",
                    "BannerIDs", "SpecialInstructions"]
    display_cols = [c for c in display_cols if c in df.columns]

    if display_cols:
        edited = st.data_editor(
            df[display_cols], height=600, hide_index=True,
            num_rows="dynamic", key="detail_editor", use_container_width=True,
        )

        if st.button("수정사항 적용", type="primary", key="apply_detail_edits"):
            for col in display_cols:
                st.session_state["edited_df"][col] = edited[col]
            # survey_document에 반영
            if doc:
                field_map = {
                    "Sort": "sort_order", "SubBanner": "sub_banner",
                    "BannerIDs": "banner_ids", "SpecialInstructions": "special_instructions",
                }
                for _, row in edited.iterrows():
                    qn = str(row.get("QuestionNumber", "")).strip()
                    if not qn:
                        continue
                    for df_col, attr in field_map.items():
                        if df_col in edited.columns:
                            val = str(row.get(df_col, ""))
                            for dq in doc.questions:
                                if dq.question_number == qn:
                                    setattr(dq, attr, val)
            st.success("수정사항이 적용되었습니다!")
            st.rerun()


# ======================================================================
# Tab 4: Banner Setup
# ======================================================================

def _tab_banner_setup(df: pd.DataFrame, language: str):
    """Tab 3: Banner Management."""
    questions = _get_questions()
    if not questions:
        st.warning("문항 데이터가 없습니다. Questionnaire Analyzer에서 먼저 문서를 처리해주세요.")
        return

    action_col, note_col = st.columns([1, 3])
    with action_col:
        generate_from_tab = st.button(
            "배너 생성/재생성",
            type="primary",
            key="generate_banners_from_tab",
            use_container_width=True,
        )
    with note_col:
        st.caption(
            "현재 문항, Study Brief, Survey Intelligence를 사용해 분석용 배너를 생성하고 "
            "문항별 BannerIDs까지 다시 할당합니다."
        )

    if generate_from_tab:
        if _run_banner_generation_only(df, language):
            st.rerun()

    # ── Analysis Plan & Consensus 표시 ──
    plan = st.session_state.get("banner_analysis_plan")
    if plan:
        # ── Research Plan 섹션 ──
        research_plan = st.session_state.get("banner_research_plan") or plan.get("_research_plan")
        if research_plan:
            with st.expander("Research Plan", expanded=False):
                brief = research_plan.get("study_brief", "")
                if brief:
                    st.markdown(f"**Study Brief:** {brief}")

                objectives = research_plan.get("research_objectives", [])
                if objectives:
                    st.markdown("**Research Objectives:**")
                    _OBJ_ICON = {"primary": ":red_circle:", "secondary": ":yellow_circle:"}
                    for obj in objectives:
                        icon = _OBJ_ICON.get(obj.get("priority", ""), ":white_circle:")
                        related = ", ".join(obj.get("related_questions", []))
                        st.markdown(f"- {icon} **{obj.get('id', '')}**: {obj.get('description', '')}")
                        if related:
                            st.caption(f"  Questions: {related}")
                        need = obj.get("analytical_need", "")
                        if need:
                            st.caption(f"  Need: {need}")

                dim_map = research_plan.get("objective_dimension_map", [])
                if dim_map:
                    st.markdown("---")
                    st.markdown("**Objective-Dimension Mapping:**")
                    rows = []
                    for mapping in dim_map:
                        obj_id = mapping.get("objective_id", "")
                        for dim in mapping.get("dimensions", []):
                            rows.append({
                                "Objective": obj_id,
                                "Dimension": dim.get("name", ""),
                                "Type": dim.get("type", ""),
                                "Questions": ", ".join(dim.get("candidate_questions", [])),
                            })
                    if rows:
                        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        # ── Expert Consensus 섹션 ──
        consensus_notes = plan.get("consensus_notes", "")
        agreement_score = plan.get("agreement_score", 0)
        expert_contribs = plan.get("expert_contributions", {})
        if consensus_notes or agreement_score or expert_contribs:
            with st.expander("Expert Consensus", expanded=False):
                if agreement_score:
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        st.metric("Agreement", f"{agreement_score:.0%}")
                    with col2:
                        st.progress(min(agreement_score, 1.0))

                if consensus_notes:
                    st.markdown(f"**Consensus Notes:** {consensus_notes}")

                if expert_contribs:
                    st.markdown("**Expert Contributions:**")
                    _EXPERT_ICON = {
                        "research_director": ":blue_book:",
                        "dp_manager": ":wrench:",
                        "client_insights": ":bar_chart:",
                    }
                    for expert_name, contribs in expert_contribs.items():
                        icon = _EXPERT_ICON.get(expert_name, ":bust_in_silhouette:")
                        label = expert_name.replace("_", " ").title()
                        items = ", ".join(contribs) if isinstance(contribs, list) else str(contribs)
                        st.markdown(f"- {icon} **{label}**: {items}")

        # ── 기존 Categories/Dimensions 표시 ──
        with st.expander("Analysis Plan", expanded=False):
            cot = plan.get("cot_reasoning", {})
            if cot:
                study_type = cot.get("study_type", "")
                if study_type:
                    st.markdown(f"**Study Type:** {study_type}")
                client_brand = cot.get("client_brand", "")
                if client_brand:
                    st.markdown(f"**Client Brand:** {client_brand}")
                questions_list = cot.get("core_research_questions", [])
                if questions_list:
                    st.markdown("**Core Research Questions:**")
                    for rq in questions_list:
                        st.markdown(f"- {rq}")
                rationale = cot.get("perspective_rationale", "")
                if rationale:
                    st.caption(f"Perspective rationale: {rationale}")
                st.markdown("---")

            strategy = plan.get("analysis_strategy", "") or plan.get("analysis_reasoning", "")
            if strategy:
                st.markdown(f"**Strategy:** {strategy}")

            _PRIORITY_ICON = {"critical": "\U0001f534", "important": "\U0001f7e0", "supplementary": "\U0001f7e1"}
            categories = plan.get("categories", [])
            if categories:
                for cat in categories:
                    cat_name = cat.get("category_name", "")
                    rationale = cat.get("business_rationale", "")
                    dims = cat.get("banner_dimensions", [])
                    priority_icon = _PRIORITY_ICON.get(cat.get("priority", ""), "")
                    st.markdown(f"**{priority_icon} {cat_name}** — {rationale}")
                    for dim in dims:
                        composite_tag = " \U0001f517" if dim.get("is_composite") else ""
                        st.markdown(
                            f"- **{dim.get('dimension_name', '')}**{composite_tag} — "
                            f"{', '.join(dim.get('candidate_questions', []))}"
                        )
                        st.caption(f"  {dim.get('analytical_question', '')}")
                    st.markdown("")
            else:
                dims = plan.get("banner_dimensions", [])
                if dims:
                    st.markdown("**Banner Dimensions:**")
                    for dim in dims:
                        priority = dim.get("priority", "medium")
                        icon = "\U0001f534" if priority == "high" else "\U0001f7e1"
                        st.markdown(
                            f"- {icon} **{dim.get('dimension_name', '')}** "
                            f"({dim.get('variable_type', '')}) — "
                            f"{', '.join(dim.get('candidate_questions', []))}"
                        )
                        st.caption(f"  {dim.get('analytical_question', '')}")

            composites = plan.get("composite_opportunities", [])
            if composites:
                st.markdown("**Composite Opportunities:**")
                for comp in composites:
                    st.markdown(
                        f"- **{comp.get('name', '')}**: "
                        f"`{comp.get('logic', '')}` — {comp.get('analytical_value', '')}"
                    )

    # 배너 목록 표시 및 편집
    doc = st.session_state.get("survey_document")
    banners = doc.banners if doc else []

    if not banners:
        st.info("배너가 아직 없습니다. 위의 **배너 생성/재생성** 버튼을 눌러 생성해주세요.")

    # ── Banner Summary 테이블 (체크박스 제거 UI) ──
    if banners:
        st.subheader("배너 요약")
        summary_data = []
        for b in banners:
            summary_data.append({
                "Include": True,
                "ID": b.banner_id,
                "Name": b.name,
                "Category": b.category or "Other",
                "Type": b.banner_type or "simple",
                "Values": len(b.points),
            })

        edited_summary = st.data_editor(
            pd.DataFrame(summary_data),
            column_config={
                "Include": st.column_config.CheckboxColumn("Include", default=True),
                "ID": st.column_config.TextColumn("ID", disabled=True, width="small"),
                "Name": st.column_config.TextColumn("Name", disabled=True),
                "Category": st.column_config.TextColumn("Category", disabled=True),
                "Type": st.column_config.TextColumn("Type", disabled=True, width="small"),
                "Values": st.column_config.NumberColumn("Values", disabled=True, width="small"),
            },
            hide_index=True,
            use_container_width=True,
            key="banner_summary_editor",
        )

        excluded = [i for i, row in edited_summary.iterrows() if not row["Include"]]
        btn_col_rm, btn_col_add = st.columns(2)
        with btn_col_rm:
            if excluded:
                if st.button(f"미선택 항목 제거 ({len(excluded)})", type="primary",
                             key="remove_unchecked_banners"):
                    for idx in sorted(excluded, reverse=True):
                        doc.banners.pop(idx)
                    st.rerun()
        with btn_col_add:
            if st.button("배너 추가", key="add_banner_btn"):
                next_id = _banner_id_from_index(len(banners))
                doc.banners.append(Banner(
                    banner_id=next_id,
                    name=f"Banner {next_id}",
                    points=[BannerPoint(
                        point_id=f"BP_{next_id}_1",
                        label="", source_question="", condition="",
                    )],
                ))
                st.rerun()
    else:
        # 배너 없을 때도 Add 버튼 제공
        if st.button("배너 추가", key="add_banner_btn_empty"):
            if doc:
                next_id = _banner_id_from_index(0)
                doc.banners.append(Banner(
                    banner_id=next_id,
                    name=f"Banner {next_id}",
                    points=[BannerPoint(
                        point_id=f"BP_{next_id}_1",
                        label="", source_question="", condition="",
                    )],
                ))
                st.rerun()

    # 카테고리별 그룹핑
    from collections import OrderedDict
    cat_groups = OrderedDict()
    for b_idx, banner in enumerate(banners):
        cat = banner.category or "Other"
        if cat not in cat_groups:
            cat_groups[cat] = []
        cat_groups[cat].append((b_idx, banner))

    # 배너별 편집 UI — 카테고리별 그룹
    for cat_name, cat_banners in cat_groups.items():
        cat_count = len(cat_banners)
        cat_points = sum(len(b.points) for _, b in cat_banners)
        with st.expander(f"{cat_name} ({cat_count} banners, {cat_points} values)",
                        expanded=True):
            for b_idx, banner in cat_banners:
                # composite 배너 태그 표시
                type_tag = " \U0001f517" if banner.banner_type == "composite" else ""
                st.markdown(f"##### Banner {banner.banner_id}: {banner.name}{type_tag}")

                new_name = st.text_input(
                    "Banner Name", value=banner.name,
                    key=f"banner_name_{banner.banner_id}",
                )
                if new_name != banner.name:
                    banner.name = new_name

                # Rationale 표시
                if banner.rationale:
                    st.caption(f"선정 이유: {banner.rationale}")

                # Banner Points 편집 가능 테이블
                bp_data = []
                for pt in banner.points:
                    bp_data.append({
                        "Label": pt.label,
                        "Condition": pt.condition,
                    })
                if not bp_data:
                    bp_data.append({"Label": "", "Condition": ""})

                edited_bp = st.data_editor(
                    pd.DataFrame(bp_data),
                    hide_index=True,
                    use_container_width=True,
                    num_rows="dynamic",
                    key=f"bp_editor_{banner.banner_id}",
                    column_config={
                        "Label": st.column_config.TextColumn(
                            "Banner Value", help="e.g. Male, 18-29, Korean Brand Owner",
                            width="medium",
                        ),
                        "Condition": st.column_config.TextColumn(
                            "Condition", help="e.g. SQ1=1, SQ2=1,2, SQ6=1,2,3&SQ5=1",
                            width="large",
                        ),
                    },
                )

                # Apply Edits / Remove 버튼
                btn_col1, btn_col2 = st.columns([3, 1])
                with btn_col1:
                    if st.button("수정사항 적용", type="primary",
                                 key=f"apply_bp_{banner.banner_id}"):
                        new_points = []
                        for j, row in edited_bp.iterrows():
                            label = str(row.get("Label", "")).strip()
                            condition = str(row.get("Condition", "")).strip()
                            if not label and not condition:
                                continue
                            # condition에서 source_question 자동 추출
                            if condition:
                                parts = condition.split("&")
                                sq = "&".join(p.split("=")[0].strip() for p in parts)
                            else:
                                sq = ""
                            new_points.append(BannerPoint(
                                point_id=f"BP_{banner.banner_id}_{j + 1}",
                                label=label,
                                source_question=sq,
                                condition=condition,
                            ))
                        banner.points = new_points
                        st.success(f"Banner {banner.banner_id} updated ({len(new_points)} values)")
                        st.rerun()
                with btn_col2:
                    if st.button(f"Remove {banner.banner_id}",
                                 key=f"del_banner_{banner.banner_id}"):
                        doc.banners.pop(b_idx)
                        st.rerun()
                st.markdown("---")

    # Banner Preview — 합산 Cross-Tab 형태
    if banners:
        st.divider()
        st.subheader("배너 프리뷰 (Cross-Tab 레이아웃)")

        # 전체 배너를 하나의 교차분석표 헤더로 합산
        header_row_1 = [""]  # 카테고리/배너명 행
        header_row_2 = ["Total"]  # 포인트 라벨 행
        condition_row = [""]  # 조건 행

        for cat_name, cat_banners in cat_groups.items():
            for _, banner in cat_banners:
                for pt in banner.points:
                    header_row_1.append(f"{banner.banner_id}: {banner.name}")
                    header_row_2.append(pt.label)
                    condition_row.append(pt.condition)

        # DataFrame 구성 (첫 열 = Row Label, 나머지 = 배너 포인트)
        cross_tab_data = {
            "Banner": header_row_1[1:],
            "Value": header_row_2[1:],
            "Condition": condition_row[1:],
        }
        cross_df = pd.DataFrame(cross_tab_data)

        # 카테고리별 색상 태깅을 위한 요약 표시
        for cat_name, cat_banners in cat_groups.items():
            total_pts = sum(len(b.points) for _, b in cat_banners)
            banner_names = [f"{b.banner_id}({b.name})" for _, b in cat_banners]
            st.markdown(f"**{cat_name}** — {', '.join(banner_names)} ({total_pts} values)")

        st.dataframe(cross_df, height=min(300, 50 + len(cross_df) * 35),
                     hide_index=True, use_container_width=True)

        # 카테고리별 상세 뷰 (접을 수 있는 개별 배너)
        with st.expander("배너 상세 편집", expanded=False):
            for cat_name, cat_banners in cat_groups.items():
                st.markdown(f"#### {cat_name}")
                for _, banner in cat_banners:
                    if banner.points:
                        labels = [pt.label for pt in banner.points]
                        conditions = [pt.condition for pt in banner.points]
                        detail_df = pd.DataFrame(
                            [conditions],
                            columns=labels,
                            index=[f"Banner {banner.banner_id}: {banner.name}"],
                        )
                        st.dataframe(detail_df, use_container_width=True)


# ======================================================================
# Tab 4: Review & Export
# ======================================================================

def _tab_review_export(df: pd.DataFrame, language: str):
    """Tab 6: Review & Export."""
    doc = st.session_state.get("survey_document")
    if not doc:
        st.warning("설문 문서가 없습니다.")
        return

    project_name = st.text_input(
        "프로젝트명",
        value=st.session_state.get("tg_project_name", doc.filename),
        key="tg_project_name_input",
    )
    st.session_state["tg_project_name"] = project_name

    # Completeness Checklist (상단 진행률과 동일 데이터, 여기서는 상세 체크리스트)
    stats = _compute_completeness()
    total = stats["total"]

    st.subheader("완성도 체크리스트")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.checkbox(f"Table Title: {stats['titles']}/{total}", value=stats['titles'] > 0, disabled=True)
        st.checkbox(f"Net/Recode: {stats['nets']}/{total}", value=stats['nets'] > 0, disabled=True)
    with c2:
        st.checkbox(f"Sort: {stats['sorts']}/{total}", value=stats['sorts'] > 0, disabled=True)
        st.checkbox(f"배너: {stats['banners']}개 정의됨", value=stats['banners'] > 0, disabled=True)
    with c3:
        st.checkbox(f"배너 할당: {stats['banner_assigned']}/{total}", value=stats['banner_assigned'] > 0, disabled=True)
        st.checkbox(f"Special Inst.: {stats['special_instructions']}/{total}", value=stats['special_instructions'] > 0, disabled=True)

    st.divider()

    compile_clicked = st.button("Table Guide 컴파일", type="primary", key="compile_tg_btn")

    if compile_clicked:
        tg_doc = compile_table_guide(doc, project_name, language)
        st.session_state["compiled_table_guide"] = tg_doc
        st.success("Table Guide 컴파일이 완료되었습니다!")

    # Preview
    tg_doc = st.session_state.get("compiled_table_guide")
    if tg_doc:
        # Keep downloads and preview aligned with the latest in-session edits.
        tg_doc = compile_table_guide(doc, project_name, language)
        st.session_state["compiled_table_guide"] = tg_doc

        st.subheader("미리보기")
        preview_df = pd.DataFrame(tg_doc.rows)

        # BannerIDs를 readable 형태로 확장한 컬럼 추가
        if "BannerIDs" in preview_df.columns:
            preview_df["BannerNames"] = preview_df["BannerIDs"].apply(_expand_banner_ids)

        # 섹션별 보기 모드 선택
        preview_mode = st.radio(
            "보기",
            options=["Full Table", "Identity & Titles", "Analysis Fields", "Banner & Instructions"],
            format_func=lambda x: {"Full Table": "전체", "Identity & Titles": "문항 & Title", "Analysis Fields": "분석 필드", "Banner & Instructions": "배너 & 지시사항"}[x],
            horizontal=True, key="preview_mode_radio",
        )

        if preview_mode == "Full Table":
            cols = [
                "QuestionNumber", "SourceVariable", "TableNumber", "TableTitle", "QuestionType",
                "Sort", "NetRecode", "BannerNames", "SubBanner",
                "SpecialInstructions",
            ]
        elif preview_mode == "Identity & Titles":
            cols = ["QuestionNumber", "TableNumber", "QuestionText",
                    "SourceVariable", "TableTitle", "QuestionType", "SummaryType"]
        elif preview_mode == "Analysis Fields":
            cols = ["QuestionNumber", "Sort", "NetRecode",
                    "SummaryType", "Filter"]
        else:  # Banner & Instructions
            cols = ["QuestionNumber", "QuestionType", "BannerNames",
                    "SubBanner", "SpecialInstructions"]

        cols = [c for c in cols if c in preview_df.columns]
        st.dataframe(preview_df[cols], height=450, hide_index=True, use_container_width=True)

        st.divider()

        # Download buttons
        st.subheader("다운로드")
        dp_summary = build_dp_handoff_validation_summary(tg_doc, doc)
        if dp_summary["total_review"]:
            st.warning(
                "DP Handoff 검증에서 확인 필요 항목이 있습니다. "
                f"Table Guide {dp_summary['table_review']}건, "
                f"Banner Spec {dp_summary['banner_review']}건을 확인해주세요.",
                icon="⚠️",
            )
            with st.expander("DP Handoff 확인 필요 항목", expanded=False):
                for warning in dp_summary["warnings"]:
                    st.markdown(f"- {warning}")
        else:
            st.success(
                f"DP Handoff 검증 완료 — Table Guide {dp_summary['table_ready']}행, "
                f"Banner Spec {dp_summary['banner_ready']}개 값이 Ready for DP 상태입니다.",
                icon="✅",
            )
        dl_col1, dl_col2, dl_col3, dl_col4 = st.columns(4)

        with dl_col1:
            intel = doc.survey_intelligence if doc else None
            excel_data = _export_table_guide_excel_cached(tg_doc, doc, intelligence=intel)
            st.download_button(
                label="내부 검토용 Excel",
                data=excel_data,
                file_name=f"{project_name}_table_guide.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with dl_col2:
            intel = doc.survey_intelligence if doc else None
            dp_excel_data = _export_dp_handoff_excel_cached(tg_doc, doc, intelligence=intel)
            st.download_button(
                label="DP Handoff Excel",
                data=dp_excel_data,
                file_name=f"{project_name}_dp_handoff.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="DP팀 전달용 2-sheet 파일입니다: Table Guide, Banner Spec",
            )

        with dl_col3:
            csv_cols = [
                "QuestionNumber", "SourceVariable", "TableNumber", "QuestionText", "TableTitle",
                "QuestionType", "SummaryType", "Sort", "NetRecode",
                "BannerIDs", "SubBanner", "SpecialInstructions", "Filter",
            ]
            csv_cols = [c for c in csv_cols if c in preview_df.columns]
            csv_bytes = preview_df[csv_cols].to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="CSV 다운로드",
                data=csv_bytes,
                file_name=f"{project_name}_table_guide.csv",
                mime="text/csv",
            )

        with dl_col4:
            session_bytes = doc.to_json_bytes()
            st.download_button(
                label="세션 다운로드 (JSON)",
                data=session_bytes,
                file_name=f"{project_name}_session.json",
                mime="application/json",
            )


# ======================================================================
# Generate All
# ======================================================================

def _run_generate_all(df: pd.DataFrame, language: str):
    """Intelligence 사전 분석 → 4개 생성 단계 병렬 실행 → 결과 순차 적용."""
    t_start = time.time()
    questions = _get_questions()
    has_questions = bool(questions)
    doc = st.session_state.get("survey_document")
    logger.info(
        "Generate All requested: rows=%s, questions=%s, has_doc=%s, language=%s",
        len(df),
        len(questions or []),
        bool(doc),
        language,
    )

    total_tasks = 3 if has_questions else 1

    with st.status("Table Guide 전체 필드 생성 중...", expanded=True) as status:
        progress_bar = st.progress(0)
        log_area = st.empty()

        # ── Step 1: Survey Intelligence (reuse from Analyzer or run fresh) ──
        intelligence = {}
        intel_elapsed = 0.0
        if has_questions:
            if doc and doc.survey_intelligence:
                intelligence = doc.survey_intelligence
                log_area.text("Reusing survey intelligence from Analyzer...")
            else:
                log_area.text("Analyzing survey intelligence...")
                client_brand = doc.client_brand if doc else ""
                study_objective = doc.study_objective if doc else ""
                t_intel = time.time()
                intelligence = analyze_survey_intelligence(
                    questions, language,
                    client_brand=client_brand,
                    study_objective=study_objective,
                )
                intel_elapsed = time.time() - t_intel
                if doc:
                    from services.survey_context import enrich_document
                    enrich_document(doc, intelligence)
                client = intelligence.get("client_name", "")
                study = intelligence.get("study_type", "")
                intel_label = f"{client} — {study}" if client else study or "Analysis complete"
                log_area.text(f"Intelligence: {intel_label} ({intel_elapsed:.1f}s)")

        # ── Step 2: survey_context 생성 (intelligence + question flow) ──
        survey_ctx = _get_survey_context(df=df)

        # ── Worker 함수 (순수 계산, st.session_state 접근 없음) ──
        # 각 워커는 (key, *data, elapsed_seconds) 튜플을 반환

        def _worker_titles():
            t0 = time.time()
            noop = lambda event, data: None
            result = _run_title_generation(df, language, noop, survey_context=survey_ctx)
            return ("titles", result, time.time() - t0)

        def _worker_net():
            t0 = time.time()
            net_map = generate_net_recodes(questions, language, survey_context=survey_ctx)
            return ("net", net_map, time.time() - t0)

        def _worker_banner():
            t0 = time.time()
            logger.info("Generate All banner worker started")
            suggested, plan = suggest_banner_points(questions, language,
                                                    survey_context=survey_ctx,
                                                    intelligence=intelligence)
            logger.info(
                "Generate All banner worker finished: suggested=%s, has_plan=%s",
                len(suggested or []),
                bool(plan),
            )
            return ("banner", (suggested, plan), time.time() - t0)

        # ── Step 3: 병렬 실행 ──
        log_area.text("Launching parallel generation...")

        with ThreadPoolExecutor(max_workers=total_tasks) as executor:
            futures = {}
            futures[executor.submit(_worker_titles)] = "Titles"

            if has_questions:
                futures[executor.submit(_worker_net)] = "Net/Recode"
                futures[executor.submit(_worker_banner)] = "Banner"

            results = {}
            worker_times = {}
            done_count = 0
            for future in as_completed(futures):
                name = futures[future]
                done_count += 1
                try:
                    result = future.result()
                    results[result[0]] = result
                    elapsed = result[-1]
                    worker_times[name] = elapsed
                    log_area.text(
                        f"[{done_count}/{total_tasks}] {name} complete ({elapsed:.1f}s)"
                    )
                except Exception as e:
                    log_area.text(f"[{done_count}/{total_tasks}] {name} failed: {e}")
                    logger.error(f"Generate All - {name} failed: {e}")
                progress_bar.progress(done_count / total_tasks)

        # ── 순차 적용 (메인 스레드) ──
        log_area.text("Applying results...")

        if "titles" in results:
            _, title_results, _ = results["titles"]
            st.session_state["title_results"] = title_results
            _apply_results_to_df(title_results)

        if not has_questions:
            elapsed_total = time.time() - t_start
            status.update(
                label=f"Title generation complete in {elapsed_total:.1f}s! "
                      f"(Net/Banner require DOCX extraction)",
                state="complete",
            )
            return

        if "net" in results:
            _, net_map, _ = results["net"]
            _sync_field_to_df_and_doc(net_map, "NetRecode", "net_recode")

        if "net" in results:
            st.session_state["net_generated"] = True

        if "banner" in results:
            _, banner_result, _ = results["banner"]
            suggested, plan = banner_result
            t_assign = time.time()
            log_area.text("Applying and assigning banners...")
            _apply_banner_generation_result(questions, doc, suggested, plan)
            worker_times["BannerAssign"] = time.time() - t_assign

        # ── Sort Order (알고리즘, 빠름) ──
        log_area.text("Generating sort orders...")
        t_sort = time.time()
        sort_map = generate_sort_orders(questions)
        _sync_field_to_df_and_doc(sort_map, "Sort", "sort_order")
        worker_times["Sort"] = time.time() - t_sort

        # ── SubBanner (매트릭스만 LLM) ──
        log_area.text("Suggesting sub-banners...")
        t_sub = time.time()
        sub_map = suggest_sub_banners(questions, language,
                                       survey_context=survey_ctx)
        _sync_field_to_df_and_doc(sub_map, "SubBanner", "sub_banner")
        worker_times["SubBanner"] = time.time() - t_sub

        # ── Special Instructions (패턴 + LLM) ──
        log_area.text("Generating special instructions...")
        t_si = time.time()
        si_map = generate_special_instructions(questions, language,
                                                survey_context=survey_ctx)
        _sync_field_to_df_and_doc(si_map, "SpecialInstructions", "special_instructions")
        worker_times["SpecialInst"] = time.time() - t_si

        # ── 최종 상태 + 소요시간 ──
        elapsed_total = time.time() - t_start
        stats = _compute_completeness()
        t = stats["total"]
        summary = (
            f"Titles {stats['titles']}/{t} · Net {stats['nets']}/{t} · "
            f"Banner {stats['banners']} · Assigned {stats['banner_assigned']}/{t} · "
            f"Sort {stats['sorts']}/{t}"
        )

        # Intelligence 소요시간 포함
        if has_questions and intelligence:
            worker_times["Intelligence"] = intel_elapsed

        # 워커별 소요시간 로그 + session_state 저장
        time_details = " | ".join(
            f"{name} {secs:.1f}s" for name, secs in
            sorted(worker_times.items(), key=lambda x: -x[1])
        )
        logger.info(f"Generate All completed in {elapsed_total:.1f}s — {time_details}")

        st.session_state["generate_all_timing"] = {
            "total": elapsed_total,
            "details": time_details,
            "summary": summary,
        }

        status.update(
            label=f"All steps complete in {elapsed_total:.1f}s! ({summary})",
            state="complete",
        )


# ======================================================================
# Study Brief — AI 추정 → 사용자 확인/수정
# ======================================================================

def _render_study_brief(doc):
    """Enrichment 결과를 프리필하여 Study Brief를 표시하고 사용자 확인을 받는다."""
    intel = doc.survey_intelligence if doc else {}
    brief_confirmed = st.session_state.get("study_brief_confirmed", False)

    # Enrichment 결과에서 기본값 추출
    default_client = (intel.get("client_name", "") or
                      (doc.client_brand if doc else ""))
    default_study_type = intel.get("study_type", "") or (doc.study_type if doc else "")
    default_objectives = intel.get("research_objectives", [])
    default_segments = intel.get("key_segments", [])
    default_objective_text = (doc.study_objective if doc else "") or ""

    # 확정된 brief가 있으면 요약만 표시
    if brief_confirmed:
        brief = st.session_state.get("study_brief", {})
        with st.expander("Study Brief (confirmed)", expanded=False):
            st.markdown(
                f"**{brief.get('client_brand', '')}** — {brief.get('study_type', '')}  \n"
                f"Objective: {brief.get('study_objective', '')}  \n"
                f"Objectives: {' | '.join(brief.get('research_objectives', [])[:3])}  \n"
                f"Segments: {' · '.join(brief.get('key_segment_names', []))}"
            )
            if st.button("Edit Brief", key="edit_brief_btn"):
                st.session_state["study_brief_confirmed"] = False
                st.rerun()
        return

    # 미확정: 에디터블 폼 표시
    expanded = not brief_confirmed
    has_intel = bool(intel and intel.get("study_type"))

    with st.expander(
        "Study Brief — AI가 설문지에서 추정한 내용을 확인하세요"
        if has_intel else "Study Brief — 프로젝트 정보를 입력하세요",
        expanded=expanded,
    ):
        if has_intel:
            st.caption("아래 내용은 설문지 분석에서 자동 추정되었습니다. 수정 후 확정해주세요.")

        col1, col2 = st.columns(2)
        with col1:
            client_brand = st.text_input(
                "Client Brand",
                value=default_client,
                placeholder="e.g. Hyundai, Samsung, LG",
                key="tg_client_brand_input",
            )
        with col2:
            study_type = st.text_input(
                "Study Type",
                value=default_study_type,
                placeholder="e.g. Brand Tracking, U&A, Satisfaction",
                key="tg_study_type_input",
            )

        study_objective = st.text_input(
            "Study Objective",
            value=default_objective_text,
            placeholder="e.g. 브랜드 건강성 추적 및 경쟁 포지셔닝 분석",
            key="tg_study_objective_input",
        )

        # Research Objectives (추정값 프리필)
        default_obj_text = "\n".join(default_objectives) if default_objectives else ""
        objectives_text = st.text_area(
            "Research Objectives (한 줄에 하나씩)",
            value=default_obj_text,
            height=100,
            placeholder="e.g.\n브랜드 인지도 변화 추적\n경쟁사 대비 포지셔닝 파악\n핵심 구매 요인 식별",
            key="tg_objectives_input",
        )

        # Key Segments (추정값 프리필)
        default_seg_names = [s.get("name", "") for s in default_segments if s.get("name")]
        default_seg_text = ", ".join(default_seg_names) if default_seg_names else ""
        segments_text = st.text_input(
            "Key Analysis Segments (쉼표로 구분)",
            value=default_seg_text,
            placeholder="e.g. Gender, Age, Brand Users, Heavy/Light Users",
            key="tg_segments_input",
        )

        # 확정 버튼
        if st.button("Confirm Study Brief", type="primary", key="confirm_brief_btn",
                      use_container_width=True):
            parsed_objectives = [
                line.strip() for line in objectives_text.split("\n")
                if line.strip()
            ]
            parsed_segments = [
                s.strip() for s in segments_text.split(",")
                if s.strip()
            ]

            brief = {
                "client_brand": client_brand,
                "study_type": study_type,
                "study_objective": study_objective,
                "research_objectives": parsed_objectives,
                "key_segment_names": parsed_segments,
            }
            st.session_state["study_brief"] = brief
            st.session_state["study_brief_confirmed"] = True

            # doc에도 반영
            if doc:
                doc.client_brand = client_brand
                doc.study_objective = study_objective
                doc.study_type = study_type

            st.rerun()


# ======================================================================
# Main Page Entry Point
# ======================================================================

def page_table_guide_builder():
    st.title("Table Guide Builder")

    # Guard: edited_df 필요
    if "edited_df" not in st.session_state or st.session_state["edited_df"] is None or st.session_state["edited_df"].empty:
        st.warning('먼저 Questionnaire Analyzer에서 문서를 처리해주세요.', icon="\u26a0\ufe0f")
        return

    df = st.session_state["edited_df"]

    # 새 컬럼 초기화
    for col in ["NetRecode", "Sort", "SubBanner", "BannerIDs", "SpecialInstructions"]:
        if col not in df.columns:
            df[col] = ""
    st.session_state["edited_df"] = df

    doc = st.session_state.get("survey_document")

    # ── Study Brief (AI 추정 → 사용자 확인/수정) ──
    _render_study_brief(doc)

    # ── 공통 Language 선택 + Generate All 버튼 ──
    col_lang, col_gen = st.columns([1, 3])
    with col_lang:
        language = st.selectbox(
            "출력 언어",
            options=["ko", "en"],
            format_func=lambda x: "한국어" if x == "ko" else "English",
            key="tg_language",
        )
    with col_gen:
        st.write("")
        st.write("")
        generate_all_clicked = st.button(
            "전체 생성",
            type="secondary",
            help="모든 생성 단계를 병렬로 실행합니다 (Title, Net, Banner)",
        )

    if generate_all_clicked:
        _run_generate_all(df, language)
        st.rerun()

    # ── Generate All 타이밍 표시 ──
    timing = st.session_state.get("generate_all_timing")
    if timing:
        st.success(
            f"전체 생성 완료 — **{timing['total']:.1f}초** 소요 — {timing['summary']}"
        )
        st.caption(f"단계별: {timing['details']}")

    banner_notice = st.session_state.pop("banner_generation_notice", None)
    if banner_notice:
        st.success(banner_notice)

    # ── Survey Intelligence 요약 표시 ──
    intel = doc.survey_intelligence if doc else {}
    if intel and intel.get("study_type"):
        client = intel.get("client_name", "") or (doc.client_brand if doc else "")
        study = intel.get("study_type", "")
        header = f"{client} — {study}" if client else study
        objectives = intel.get("research_objectives", [])
        obj_str = " | ".join(objectives[:3]) if objectives else ""
        segments = intel.get("key_segments", [])
        seg_str = " · ".join(s.get("name", "") for s in segments) if segments else ""
        intel_lines = [f"**{header}**"]
        if obj_str:
            intel_lines.append(f"Objectives: {obj_str}")
        if seg_str:
            intel_lines.append(f"Segments: {seg_str}")
        st.info("\n\n".join(intel_lines), icon="\U0001f4cb")

    # ── 생성 항목 선택 + 원버튼 ──
    st.markdown("#### 생성할 항목을 선택하세요")
    col_chk1, col_chk2 = st.columns(2)
    with col_chk1:
        gen_titles = st.checkbox("Table Titles", value=True, key="gen_titles_chk")
    with col_chk2:
        gen_banners = st.checkbox("Banner (Beta)", value=False, key="gen_banners_chk")

    generate_clicked = st.button(
        "선택 항목 생성",
        type="primary",
        use_container_width=True,
        disabled=not (gen_titles or gen_banners),
    )

    if generate_clicked:
        logger.info(
            "Selected generation clicked: titles=%s, banners=%s, rows=%s, questions=%s",
            gen_titles,
            gen_banners,
            len(df),
            len(_get_questions() or []),
        )
        rerun_needed = False
        if gen_titles:
            with st.status("Table Title 생성 중...", expanded=True) as title_status:
                progress_bar = st.progress(0)
                log_area = st.empty()
                batch_done_count = [0]
                total_batches_ref = [1]

                def _title_cb(event, data):
                    if event == "run_start":
                        total_batches_ref[0] = data["total_batches"]
                        log_area.text(
                            f"{data['total_batches']}개 배치를 병렬 처리 중 "
                            f"({data['question_count']}개 문항, worker {data['workers']}개)..."
                        )
                    elif event == "batch_done":
                        total_batches_ref[0] = data["total_batches"]
                        batch_done_count[0] += 1
                        progress_bar.progress(batch_done_count[0] / total_batches_ref[0])
                        log_area.text(
                            f"배치 {data['batch_index'] + 1}/{data['total_batches']} 완료 "
                            f"({data['generated_count']}개 생성) · "
                            f"{batch_done_count[0]}/{data['total_batches']} 완료"
                        )

                survey_ctx = _get_survey_context(df=df)
                results = _run_title_generation(df, language, _title_cb, survey_context=survey_ctx)
                st.session_state["title_results"] = results
                _apply_results_to_df(results)
                generated_count = sum(1 for r in results if not r["error"])
                title_status.update(label=f"Title 생성 완료! {generated_count}개", state="complete")
                rerun_needed = True

        if gen_banners:
            df = st.session_state.get("edited_df", df)
            rerun_needed = _run_banner_generation_only(df, language) or rerun_needed

        if rerun_needed:
            st.rerun()

    # ── 진행률 요약 ──
    stats = _compute_completeness()
    total = stats["total"]
    if total > 0:
        items = [
            ("Titles", stats["titles"], total),
            ("Banner", stats["banners"], None),
        ]
        parts = []
        for label, count, t in items:
            parts.append(f"**{label}** {count}/{t}" if t else f"**{label}** {count}")
        st.caption(" · ".join(parts))

    # ── 결과 탭: Titles + Banner + Export ──
    tab_labels = ["Table Titles", "Banner (Beta)", "다운로드"]
    tab1, tab2, tab3 = st.tabs(tab_labels)

    with tab1:
        _tab_table_titles(df, language)

    with tab2:
        _tab_banner_setup(df, language)

    with tab3:
        _tab_review_export(df, language)
