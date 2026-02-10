"""설문 데이터를 편집 가능한 스프레드시트로 표시하는 Streamlit 컴포넌트."""

import streamlit as st
import pandas as pd
from models.survey import SurveyDocument


def render_spreadsheet_view(survey_doc: SurveyDocument) -> pd.DataFrame:
    """설문 데이터를 편집 가능한 스프레드시트로 표시.

    Args:
        survey_doc: 추출된 설문 문서

    Returns:
        편집된 DataFrame
    """
    df = survey_doc.to_dataframe()

    if df.empty:
        st.info("No data to display.")
        return df

    # 표시할 컬럼 순서
    display_columns = [
        "QuestionNumber", "TableNumber", "QuestionText", "QuestionType",
        "AnswerOptions", "SkipLogic", "Filter", "ResponseBase",
        "Instructions", "SummaryType"
    ]

    # 존재하는 컬럼만 표시
    display_columns = [c for c in display_columns if c in df.columns]

    column_config = {
        "QuestionNumber": st.column_config.TextColumn("Q#", width="small"),
        "TableNumber": st.column_config.TextColumn("Table#", width="small"),
        "QuestionText": st.column_config.TextColumn("Question Text", width="large"),
        "QuestionType": st.column_config.TextColumn("Type", width="small"),
        "AnswerOptions": st.column_config.TextColumn("Answer Options", width="large"),
        "SkipLogic": st.column_config.TextColumn("Skip Logic", width="medium"),
        "Filter": st.column_config.TextColumn("Filter", width="medium"),
        "ResponseBase": st.column_config.TextColumn("Response Base", width="small"),
        "Instructions": st.column_config.TextColumn("Instructions", width="medium"),
        "SummaryType": st.column_config.TextColumn("Summary Type", width="medium"),
    }

    edited_df = st.data_editor(
        df[display_columns],
        column_config=column_config,
        height=800,
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        key='docx_spreadsheet_editor'
    )

    return edited_df
