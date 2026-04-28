"""설문 데이터를 편집 가능한 스프레드시트로 표시하는 Streamlit 컴포넌트."""

import streamlit as st
import pandas as pd
from models.survey import AnswerOption, SkipLogic, SurveyDocument, SurveyQuestion


def _parse_answer_options(value: str) -> list[AnswerOption]:
    """Parse compact answer option text: '1. Male | 2. Female'."""
    options = []
    text = str(value or "").strip()
    if not text:
        return options
    for part in text.split("|"):
        item = part.strip()
        if not item:
            continue
        if ". " in item:
            code, label = item.split(". ", 1)
        elif "." in item:
            code, label = item.split(".", 1)
        else:
            code, label = "", item
        options.append(AnswerOption(code=code.strip(), label=label.strip()))
    return options


def _parse_skip_logic(value: str) -> list[SkipLogic]:
    """Parse compact skip logic text: 'Q1=1 -> Q2 | Q1=2 -> Q3'."""
    logic = []
    text = str(value or "").strip()
    if not text:
        return logic
    for part in text.split("|"):
        item = part.strip()
        if not item:
            continue
        if "->" in item:
            condition, target = item.split("->", 1)
        elif "→" in item:
            condition, target = item.split("→", 1)
        else:
            condition, target = item, ""
        logic.append(SkipLogic(condition=condition.strip(), target=target.strip()))
    return logic


def _question_key_from_values(question_number: str, table_number: str) -> tuple[str, str]:
    qn = str(question_number or "").strip()
    tn = str(table_number or "").strip()
    return qn, tn or qn


def apply_spreadsheet_edits_to_document(
    survey_doc: SurveyDocument,
    edited_df: pd.DataFrame,
) -> SurveyDocument:
    """Apply spreadsheet edits back to SurveyDocument.

    The data editor is the main human review surface. This sync keeps session
    JSON, Ground Truth candidates, and downstream tools aligned with edits.
    """
    existing = {
        _question_key_from_values(q.question_number, q.table_number): q
        for q in survey_doc.questions
    }

    updated_questions = []
    for _, row in edited_df.iterrows():
        qn = str(row.get("QuestionNumber", "") or "").strip()
        if not qn:
            continue
        tn = str(row.get("TableNumber", "") or "").strip()
        key = _question_key_from_values(qn, tn)
        q = existing.get(key)
        if q is None:
            q = SurveyQuestion(
                question_number=qn,
                question_text=str(row.get("QuestionText", "") or "").strip(),
            )

        q.question_number = qn
        q.source_variable = str(row.get("SourceVariable", q.source_variable or qn) or "").strip()
        q.table_number = tn or qn
        q.question_text = str(row.get("QuestionText", q.question_text) or "")
        q.question_type = str(row.get("QuestionType", q.question_type or "") or "") or None
        q.filter_condition = str(row.get("Filter", q.filter_condition or "") or "") or None
        q.instructions = str(row.get("Instructions", q.instructions or "") or "") or None
        q.summary_type = str(row.get("SummaryType", q.summary_type) or "")

        if "AnswerOptions" in row:
            q.answer_options = _parse_answer_options(row.get("AnswerOptions", ""))
        if "SkipLogic" in row:
            q.skip_logic = _parse_skip_logic(row.get("SkipLogic", ""))
        if "ReviewStatus" in row:
            status = str(row.get("ReviewStatus", "") or "").strip()
            q.review_status = status or "needs_review"
        if "ReviewNotes" in row:
            q.review_notes = str(row.get("ReviewNotes", "") or "")

        updated_questions.append(q)

    survey_doc.questions = updated_questions
    return survey_doc


def render_spreadsheet_view(survey_doc: SurveyDocument) -> pd.DataFrame:
    """설문 데이터를 편집 가능한 스프레드시트로 표시.

    Args:
        survey_doc: 추출된 설문 문서

    Returns:
        편집된 DataFrame
    """
    existing_df = st.session_state.get("edited_df")
    if isinstance(existing_df, pd.DataFrame) and not existing_df.empty:
        df = existing_df.copy()
    else:
        df = survey_doc.to_dataframe()

    if df.empty:
        st.info("표시할 데이터가 없습니다.")
        return df

    # 표시할 컬럼 순서
    view_mode = st.radio(
        "Review table view",
        options=["Core", "Logic", "Review", "All"],
        horizontal=True,
        key="docx_spreadsheet_view_mode",
    )
    status_filter = st.selectbox(
        "Review status filter",
        options=["All", "needs_review", "verified", "rejected"],
        key="docx_spreadsheet_status_filter",
    )

    core_columns = [
        "ReviewStatus", "QuestionNumber", "SourceVariable", "TableNumber", "QuestionText",
        "QuestionType", "SummaryType",
    ]
    logic_columns = [
        "ReviewStatus", "QuestionNumber", "SourceVariable", "AnswerOptions", "SkipLogic",
        "Filter", "Instructions",
    ]
    review_columns = [
        "ReviewStatus", "QuestionNumber", "SourceVariable", "QuestionText", "ReviewNotes",
    ]
    all_columns = [
        "ReviewStatus",
        "QuestionNumber", "SourceVariable", "TableNumber", "QuestionText", "QuestionType",
        "AnswerOptions", "SkipLogic", "Filter",
        "Instructions", "SummaryType", "ReviewNotes",
    ]
    display_columns = {
        "Core": core_columns,
        "Logic": logic_columns,
        "Review": review_columns,
        "All": all_columns,
    }[view_mode]

    # 존재하는 컬럼만 표시
    display_columns = [c for c in display_columns if c in df.columns]
    if not display_columns:
        display_columns = [c for c in all_columns if c in df.columns]

    column_config = {
        "ReviewStatus": st.column_config.SelectboxColumn(
            "Review",
            options=["needs_review", "verified", "rejected"],
            width="small",
        ),
        "QuestionNumber": st.column_config.TextColumn("Q#", width="small"),
        "SourceVariable": st.column_config.TextColumn("Source Variable", width="small"),
        "TableNumber": st.column_config.TextColumn("Table#", width="small"),
        "QuestionText": st.column_config.TextColumn("Question Text", width="large"),
        "QuestionType": st.column_config.TextColumn("Type", width="small"),
        "AnswerOptions": st.column_config.TextColumn("Answer Options", width="large"),
        "SkipLogic": st.column_config.TextColumn("Skip Logic", width="medium"),
        "Filter": st.column_config.TextColumn("Filter", width="medium"),
        "Instructions": st.column_config.TextColumn("Instructions", width="medium"),
        "SummaryType": st.column_config.TextColumn("Summary Type", width="medium"),
        "ReviewNotes": st.column_config.TextColumn("Review Notes", width="medium"),
    }

    if status_filter != "All" and "ReviewStatus" in df.columns:
        mask = df["ReviewStatus"].fillna("needs_review").astype(str) == status_filter
    else:
        mask = pd.Series(True, index=df.index)
    filtered_df = df.loc[mask, display_columns].copy()
    num_rows_mode = "dynamic" if status_filter == "All" else "fixed"

    edited_df = st.data_editor(
        filtered_df,
        column_config=column_config,
        height=800,
        hide_index=True,
        num_rows=num_rows_mode,
        use_container_width=True,
        key=f"docx_spreadsheet_editor_{view_mode}_{status_filter}",
    )

    for idx, row in edited_df.iterrows():
        if idx not in df.index:
            df.loc[idx, display_columns] = row
            continue
        for col in display_columns:
            df.at[idx, col] = row.get(col, "")

    return df
