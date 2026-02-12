"""Table Guide Builder 페이지.

Phase 1: Table Title 생성 (LLM 배치 + 접미사 알고리즘)
Phase 2: Net/Recode
Phase 3: Banner Management
Phase 4: Review & Export
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import streamlit as st

from models.survey import Banner, BannerPoint
from services.llm_client import call_llm_json, MODEL_TITLE_GENERATOR
from services.survey_context import build_survey_context
from services.table_guide_service import (
    _banner_id_from_index,
    analyze_survey_intelligence,
    assign_banners_to_questions,
    compile_table_guide, expand_banner_ids, export_table_guide_excel,
    generate_net_recodes,
    generate_sort_orders, generate_special_instructions,
    suggest_banner_points, suggest_sub_banners,
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 20


def _get_survey_context(df=None) -> str:
    """session_state의 SurveyDocument에서 survey context 생성."""
    doc = st.session_state.get("survey_document")
    if doc:
        return build_survey_context(doc, df=df)
    # doc이 없으면 빈 문자열
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
7. **설문 전체 맥락 활용**: Survey Context가 제공되면, 해당 문항이 설문 전체에서 어떤 역할(인지→경험→평가→의향 등)을 하는지 파악하여 더 정확하고 구체적인 제목을 생성하세요.

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
7. **Use survey context**: When Survey Context is provided, understand each question's role in the overall study flow (e.g., awareness → usage → evaluation → intent) to generate more precise and contextually appropriate titles.

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

    for _, row in df.iterrows():
        qn = str(row.get("QuestionNumber", "")).strip()
        if not qn:
            continue

        if qn not in seen:
            text = str(row.get("QuestionText", "")).strip()
            qtype = str(row.get("QuestionType", "")).strip()
            options = str(row.get("AnswerOptions", "")).strip() if "AnswerOptions" in df.columns else ""
            filt = str(row.get("Filter", "")).strip() if "Filter" in df.columns else ""

            seen[qn] = len(groups)
            groups.append({
                "qn": qn,
                "text": text,
                "qtype": qtype,
                "options": options,
                "filter": filt,
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
    parts.append(f"Text: {item['text']}")
    if item["qtype"]:
        parts.append(f"Type: {item['qtype']}")
    if item["options"]:
        parts.append(f"Options: {item['options']}")
    unique_st = list(dict.fromkeys(s for s in item["summary_types"] if s))
    if unique_st:
        parts.append(f"SummaryTypes: {', '.join(unique_st)}")
    parts.append(f"Split Rows: {item['row_count']}")
    if item["filter"]:
        parts.append(f"Filter: {item['filter']}")
    return "\n".join(parts)


def _build_batch_prompt(batch: list, survey_context: str = "") -> str:
    parts = []
    if survey_context:
        parts.append(survey_context)
        parts.append("")
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
        base_title = info["title"]
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

    for batch_idx, batch in enumerate(batches):
        progress_callback("batch_start", {
            "batch_index": batch_idx, "total_batches": total_batches,
            "question_count": len(batch),
        })
        user_prompt = _build_batch_prompt(batch, survey_context)
        try:
            raw = call_llm_json(system_prompt, user_prompt, MODEL_TITLE_GENERATOR)
            parsed = _parse_batch_result(raw, batch)
        except Exception as e:
            logger.error(f"Title batch {batch_idx} failed: {e}")
            parsed = {item["qn"]: {"title": "", "reasoning": f"Error: {e}"} for item in batch}
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
        st.info("No questions match the selected filter.")
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

    if st.button("Apply Edits", type="primary", key="apply_title_edits"):
        for col in display_cols:
            st.session_state["edited_df"][col] = edited[col]
        if "survey_document" in st.session_state and st.session_state["survey_document"]:
            tn_to_title = dict(zip(edited["TableNumber"], edited["TableTitle"]))
            for q in st.session_state["survey_document"].questions:
                if q.table_number in tn_to_title:
                    q.table_title = str(tn_to_title[q.table_number])
        st.success("Edits applied successfully!")
        st.rerun()


def _tab_table_titles(df: pd.DataFrame, language: str):
    """Tab 1: Table Titles."""
    groups = _group_rows_by_question(df)
    total_unique = len(groups)
    total_rows = len(df)
    split_count = sum(1 for g in groups if g["row_count"] > 1)
    split_rows = sum(g["row_count"] for g in groups if g["row_count"] > 1)

    st.info(
        f"Found **{total_unique}** unique questions "
        f"(**{total_rows}** rows, **{split_rows}** split rows in **{split_count}** questions). "
        "Click **Generate Titles** to create table titles.",
        icon="\u2139\ufe0f",
    )

    generate_clicked = st.button("Generate Titles", type="primary", key="generate_titles_btn")

    if generate_clicked:
        with st.status("Generating titles...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()
            batch_done_count = [0]
            total_batches_ref = [1]

            def _progress_callback(event, data):
                if event == "batch_start":
                    total_batches_ref[0] = data["total_batches"]
                    log_area.text(
                        f"Processing batch {data['batch_index'] + 1}/{data['total_batches']} "
                        f"({data['question_count']} questions)..."
                    )
                elif event == "batch_done":
                    batch_done_count[0] += 1
                    progress_bar.progress(batch_done_count[0] / total_batches_ref[0])
                    log_area.text(
                        f"Batch {data['batch_index'] + 1}/{data['total_batches']} done "
                        f"({data['generated_count']} generated)"
                    )

            questions = _get_questions()
            survey_ctx = _get_survey_context(df=df)
            results = _run_title_generation(df, language, _progress_callback,
                                            survey_context=survey_ctx)
            st.session_state["title_results"] = results
            _apply_results_to_df(results)
            generated_count = sum(1 for r in results if not r["error"])
            status.update(
                label=f"Title generation complete! {generated_count}/{len(results)} titles generated.",
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

    filter_mode = st.radio(
        "Filter", options=["All", "Split Only", "Non-Split Only", "Errors Only"],
        horizontal=True, key="title_filter_radio",
    )
    _render_title_comparison(results, filter_mode)

    st.divider()
    st.subheader("Editable Table")
    _render_title_editable_table()


# ======================================================================
# Tab 2: Net/Recode
# ======================================================================

def _tab_net_recode(df: pd.DataFrame, language: str):
    """Tab 2: Net/Recode."""
    questions = _get_questions()
    if not questions:
        st.warning("No questions available. Please run Questionnaire Analyzer first.")
        return

    generate_clicked = st.button("Generate Net/Recode", type="primary",
                                 key="generate_net_btn")

    if generate_clicked:
        with st.status("Generating Net/Recode...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()

            def _progress_cb(event, data):
                if "batch_start" in event:
                    log_area.text(f"[{event}] Batch {data['batch_index']+1}/{data['total_batches']}...")
                elif "batch_done" in event:
                    progress_bar.progress(1.0)

            survey_ctx = _get_survey_context(df=df)

            log_area.text("Generating Net/Recode suggestions...")
            net_map = generate_net_recodes(questions, language, _progress_cb,
                                           survey_context=survey_ctx)
            _sync_field_to_df_and_doc(net_map, "NetRecode", "net_recode")

            progress_bar.progress(1.0)
            st.session_state["net_generated"] = True
            status.update(label="Net/Recode generation complete!", state="complete")

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
                st.metric("With Net/Recode", net_count)
            with c2:
                st.metric("No Net/Recode", no_net_count)

        # Filter radio
        bn_filter = st.radio(
            "Filter", options=["All", "Scale Only", "Custom Net"],
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
    st.subheader("Editable Table")

    display_cols = ["QuestionNumber", "TableNumber", "NetRecode", "SummaryType"]
    display_cols = [c for c in display_cols if c in df.columns]

    if display_cols:
        edited = st.data_editor(
            df[display_cols], height=600, hide_index=True,
            num_rows="dynamic", key="bn_editor", use_container_width=True,
        )

        if st.button("Apply Edits", type="primary", key="apply_bn_edits"):
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
            st.success("Edits applied successfully!")
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
        st.warning("No questions available. Please run Questionnaire Analyzer first.")
        return

    # ── 개별 생성 버튼 ──
    btn_col1, btn_col2, btn_col3 = st.columns(3)
    with btn_col1:
        sort_clicked = st.button("Generate Sort Orders", key="gen_sort_btn")
    with btn_col2:
        sub_clicked = st.button("Generate SubBanners", key="gen_sub_btn")
    with btn_col3:
        si_clicked = st.button("Generate Special Inst.", key="gen_si_btn")

    survey_ctx = _get_survey_context(df=df)

    if sort_clicked:
        with st.spinner("Generating sort orders..."):
            sort_map = generate_sort_orders(questions)
            _sync_field_to_df_and_doc(sort_map, "Sort", "sort_order")
            st.session_state["sort_generated"] = True
            st.rerun()

    if sub_clicked:
        with st.spinner("Generating sub-banners..."):
            sub_map = suggest_sub_banners(questions, language,
                                           survey_context=survey_ctx)
            _sync_field_to_df_and_doc(sub_map, "SubBanner", "sub_banner")
            st.session_state["subbanner_generated"] = True
            st.rerun()

    if si_clicked:
        with st.spinner("Generating special instructions..."):
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
        "Filter", options=["All", "With SubBanner", "With Special Inst.", "No Banners"],
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
    st.subheader("Editable Table")

    display_cols = ["QuestionNumber", "QuestionType", "Sort", "SubBanner",
                    "BannerIDs", "SpecialInstructions"]
    display_cols = [c for c in display_cols if c in df.columns]

    if display_cols:
        edited = st.data_editor(
            df[display_cols], height=600, hide_index=True,
            num_rows="dynamic", key="detail_editor", use_container_width=True,
        )

        if st.button("Apply Edits", type="primary", key="apply_detail_edits"):
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
            st.success("Edits applied successfully!")
            st.rerun()


# ======================================================================
# Tab 4: Banner Setup
# ======================================================================

def _tab_banner_setup(df: pd.DataFrame, language: str):
    """Tab 3: Banner Management."""
    questions = _get_questions()
    if not questions:
        st.warning("No questions available. Please run Questionnaire Analyzer first.")
        return

    suggest_clicked = st.button("Auto-Suggest Banner Points", type="primary",
                                key="suggest_banners_btn")

    if suggest_clicked:
        with st.status("Generating banners with expert consensus...", expanded=True) as status:
            status_text = st.empty()
            expert_area = st.empty()

            def _progress_cb(event, data):
                if event == "phase":
                    name = data.get("name", "")
                    phase_status = data.get("status", "")
                    _PHASE_LABELS = {
                        "research_plan": "Creating research plan",
                        "expert_panel": "Expert panel analyzing",
                        "synthesis": "Building expert consensus",
                        "banner_design": "Designing banners from consensus plan",
                        "validation": "Validating banner codes",
                    }
                    label = _PHASE_LABELS.get(name, name)
                    if phase_status == "start":
                        extra = ""
                        if name == "expert_panel":
                            extra = f" ({data.get('count', 3)} experts in parallel)"
                        status_text.markdown(f"**{label}{extra}...**")
                    elif phase_status == "done":
                        extra = ""
                        if name == "synthesis":
                            score = data.get("agreement_score", 0)
                            extra = f" (agreement: {score:.0%})"
                        status_text.markdown(f":white_check_mark: {label}{extra}")
                elif event == "expert_done":
                    expert_area.markdown(
                        f"  :white_check_mark: {data.get('name', '')} complete "
                        f"({data.get('index', 0)}/{data.get('total', 3)})"
                    )

            doc = st.session_state.get("survey_document")
            intel = doc.survey_intelligence if doc else None
            survey_ctx = _get_survey_context()
            suggested, plan = suggest_banner_points(
                questions, language,
                survey_context=survey_ctx,
                intelligence=intel,
                progress_callback=_progress_cb,
            )

            if suggested:
                doc = st.session_state.get("survey_document")
                if doc:
                    doc.banners = suggested
                st.session_state["banners_suggested"] = True
                if plan:
                    st.session_state["banner_analysis_plan"] = plan
                    # 연구 기획서 및 전문가 출력 세션 저장
                    rp = plan.get("_research_plan")
                    if rp:
                        st.session_state["banner_research_plan"] = rp
                    eo = plan.get("_expert_outputs")
                    if eo:
                        st.session_state["banner_expert_outputs"] = eo
                    st.session_state["banner_consensus_score"] = plan.get("agreement_score", 0)

                n_banners = len(suggested)
                n_cats = len(set(b.category for b in suggested if b.category))
                agreement = plan.get("agreement_score", 0) if plan else 0
                summary = f"Done! {n_banners} banners in {n_cats} categories"
                if agreement > 0:
                    summary += f" (agreement: {agreement:.0%})"
                status.update(label=summary, state="complete")
            else:
                status.update(label="No suitable banner candidates found.", state="error")

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
        st.info("No banners defined yet. Click **Auto-Suggest Banner Points** or add manually below.")

    # ── Banner Summary 테이블 (체크박스 제거 UI) ──
    if banners:
        st.subheader("Banner Summary")
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
                if st.button(f"Remove Unchecked ({len(excluded)})", type="primary",
                             key="remove_unchecked_banners"):
                    for idx in sorted(excluded, reverse=True):
                        doc.banners.pop(idx)
                    st.rerun()
        with btn_col_add:
            if st.button("Add New Banner", key="add_banner_btn"):
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
        if st.button("Add New Banner", key="add_banner_btn_empty"):
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
                    st.caption(f"Rationale: {banner.rationale}")

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
                    if st.button("Apply Edits", type="primary",
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
        st.subheader("Banner Preview (Cross-Tab Layout)")

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
        with st.expander("Banner Details (individual editing)", expanded=False):
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
        st.warning("No survey document available.")
        return

    # Project name 입력
    project_name = st.text_input(
        "Project Name",
        value=st.session_state.get("tg_project_name", doc.filename),
        key="tg_project_name_input",
    )
    st.session_state["tg_project_name"] = project_name

    # Completeness Checklist (상단 진행률과 동일 데이터, 여기서는 상세 체크리스트)
    stats = _compute_completeness()
    total = stats["total"]

    st.subheader("Completeness Checklist")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.checkbox(f"Table Titles: {stats['titles']}/{total}", value=stats['titles'] > 0, disabled=True)
        st.checkbox(f"Net/Recode: {stats['nets']}/{total}", value=stats['nets'] > 0, disabled=True)
    with c2:
        st.checkbox(f"Sort: {stats['sorts']}/{total}", value=stats['sorts'] > 0, disabled=True)
        st.checkbox(f"Banners: {stats['banners']} defined", value=stats['banners'] > 0, disabled=True)
    with c3:
        st.checkbox(f"Banner Assigned: {stats['banner_assigned']}/{total}", value=stats['banner_assigned'] > 0, disabled=True)
        st.checkbox(f"Special Instr: {stats['special_instructions']}/{total}", value=stats['special_instructions'] > 0, disabled=True)

    st.divider()

    compile_clicked = st.button("Compile Table Guide", type="primary", key="compile_tg_btn")

    if compile_clicked:
        tg_doc = compile_table_guide(doc, project_name, language)
        st.session_state["compiled_table_guide"] = tg_doc
        st.success("Table Guide compiled successfully!")

    # Preview
    tg_doc = st.session_state.get("compiled_table_guide")
    if tg_doc:
        st.subheader("Preview")
        preview_df = pd.DataFrame(tg_doc.rows)

        # BannerIDs를 readable 형태로 확장한 컬럼 추가
        if "BannerIDs" in preview_df.columns:
            preview_df["BannerNames"] = preview_df["BannerIDs"].apply(_expand_banner_ids)

        # 섹션별 보기 모드 선택
        preview_mode = st.radio(
            "View",
            options=["Full Table", "Identity & Titles", "Analysis Fields", "Banner & Instructions"],
            horizontal=True, key="preview_mode_radio",
        )

        if preview_mode == "Full Table":
            cols = [
                "QuestionNumber", "TableNumber", "TableTitle", "QuestionType",
                "Sort", "NetRecode", "BannerNames", "SubBanner",
                "SpecialInstructions",
            ]
        elif preview_mode == "Identity & Titles":
            cols = ["QuestionNumber", "TableNumber", "QuestionText",
                    "TableTitle", "QuestionType", "SummaryType"]
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
        st.subheader("Download")
        dl_col1, dl_col2, dl_col3 = st.columns(3)

        with dl_col1:
            intel = doc.survey_intelligence if doc else None
            excel_data = export_table_guide_excel(tg_doc, doc, intelligence=intel)
            st.download_button(
                label="Download Full Table Guide (Excel)",
                data=excel_data,
                file_name=f"{project_name}_table_guide.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with dl_col2:
            csv_cols = [
                "QuestionNumber", "TableNumber", "QuestionText", "TableTitle",
                "QuestionType", "SummaryType", "Sort", "NetRecode",
                "BannerIDs", "SubBanner", "SpecialInstructions", "Filter",
            ]
            csv_cols = [c for c in csv_cols if c in preview_df.columns]
            csv_bytes = preview_df[csv_cols].to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="Download CSV (flat)",
                data=csv_bytes,
                file_name=f"{project_name}_table_guide.csv",
                mime="text/csv",
            )

        with dl_col3:
            session_bytes = doc.to_json_bytes()
            st.download_button(
                label="Download Session (JSON)",
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

    total_tasks = 3 if has_questions else 1

    with st.status("Generating all Table Guide fields...", expanded=True) as status:
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
            suggested, plan = suggest_banner_points(questions, language,
                                                    survey_context=survey_ctx,
                                                    intelligence=intelligence)
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
            if suggested and doc:
                # 기존 배너가 더 풍부하면 fallback 결과로 덮어쓰지 않음
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

        # ── 배너 할당 (배너 생성 후 순차) ──
        if "banner" in results and doc and doc.banners:
            log_area.text("Assigning banners to questions...")
            t_assign = time.time()
            banner_assign_map = assign_banners_to_questions(questions, doc.banners)
            _sync_field_to_df_and_doc(banner_assign_map, "BannerIDs", "banner_ids")
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
# Main Page Entry Point
# ======================================================================

def page_table_guide_builder():
    st.title("Table Guide Builder")

    # Guard: edited_df 필요
    if "edited_df" not in st.session_state or st.session_state["edited_df"] is None or st.session_state["edited_df"].empty:
        st.warning('Please process a document in "Questionnaire Analyzer" first.', icon="\u26a0\ufe0f")
        return

    df = st.session_state["edited_df"]

    # 새 컬럼 초기화
    for col in ["NetRecode", "Sort", "SubBanner", "BannerIDs", "SpecialInstructions"]:
        if col not in df.columns:
            df[col] = ""
    st.session_state["edited_df"] = df

    doc = st.session_state.get("survey_document")

    # ── Study Brief 입력 (doc에서 읽기, 변경 시 doc에 반영) ──
    with st.expander("Study Brief (optional — improves generation quality)", expanded=False):
        brief_col1, brief_col2 = st.columns(2)
        with brief_col1:
            client_brand = st.text_input(
                "Client Brand",
                value=doc.client_brand if doc else "",
                placeholder="e.g. Hyundai, Samsung, LG",
                help="The brand commissioning the study. Enables client-specific banner segments.",
                key="tg_client_brand_input",
            )
            if doc:
                doc.client_brand = client_brand
        with brief_col2:
            study_objective = st.text_input(
                "Study Objective",
                value=doc.study_objective if doc else "",
                placeholder="e.g. Brand health tracking, Customer satisfaction measurement",
                help="Research purpose. Helps prioritize meaningful analytical dimensions.",
                key="tg_study_objective_input",
            )
            if doc:
                doc.study_objective = study_objective

    # ── 공통 Language 선택 + Generate All 버튼 ──
    col_lang, col_gen = st.columns([1, 3])
    with col_lang:
        language = st.selectbox(
            "Language",
            options=["ko", "en"],
            format_func=lambda x: "\ud55c\uad6d\uc5b4" if x == "ko" else "English",
            key="tg_language",
        )
    with col_gen:
        st.write("")  # spacing
        st.write("")
        generate_all_clicked = st.button(
            "Generate All",
            type="secondary",
            help="Run all generation steps in parallel (Titles, Net, Banner)",
        )

    if generate_all_clicked:
        _run_generate_all(df, language)
        st.rerun()

    # ── Generate All 타이밍 표시 ──
    timing = st.session_state.get("generate_all_timing")
    if timing:
        st.success(
            f"Generate All completed in **{timing['total']:.1f}s** — {timing['summary']}"
        )
        st.caption(f"Per-worker: {timing['details']}")

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

    # ── Completeness 진행률 ──
    stats = _compute_completeness()
    total = stats["total"]
    if total > 0:
        items = [
            ("Titles", stats["titles"], total),
            ("Net", stats["nets"], total),
            ("Banner", stats["banners"], None),
            ("Assigned", stats["banner_assigned"], total),
            ("Sort", stats["sorts"], total),
        ]
        parts = []
        for label, count, t in items:
            parts.append(f"**{label}** {count}/{t}" if t else f"**{label}** {count}")
        st.caption(" \u00b7 ".join(parts))

    # ── 동적 탭 라벨 ──
    tab_labels = [
        _tab_label("Table Titles", stats["titles"], total),
        _tab_label("Net/Recode", stats["nets"], total),
        _tab_label("Sort & Details", stats["sorts"], total),
        "Banner \u2713" if stats["banners"] > 0 else "Banner",
        "Review & Export",
    ]

    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_labels)

    with tab1:
        _tab_table_titles(df, language)

    with tab2:
        _tab_net_recode(df, language)

    with tab3:
        _tab_sort_details(df, language)

    with tab4:
        _tab_banner_setup(df, language)

    with tab5:
        _tab_review_export(df, language)
