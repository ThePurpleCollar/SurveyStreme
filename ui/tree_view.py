"""설문 문항을 계층적 트리뷰로 표시하는 Streamlit 컴포넌트."""

import streamlit as st
import pandas as pd
from models.survey import SurveyDocument


def render_tree_view(survey_doc: SurveyDocument):
    """설문 문항을 계층적 트리뷰로 표시.

    각 문항이 expander로 표시되며, 내부에 보기, 로직, 필터 등이 포함됩니다.
    """
    if not survey_doc.questions:
        st.info("No questions extracted.")
        return

    st.markdown(f"**{len(survey_doc.questions)}** questions extracted")

    for idx, q in enumerate(survey_doc.questions):
        # 문항 헤더: 번호 | 질문 텍스트 축약 | [유형]
        type_badge = f" `{q.question_type}`" if q.question_type else ""
        question_preview = q.question_text[:80] + ("..." if len(q.question_text) > 80 else "")

        with st.expander(
            f"**{q.question_number}** | {question_preview}{type_badge}",
            expanded=False
        ):
            # 전체 질문 텍스트
            st.markdown(f"**Question:** {q.question_text}")

            # 메타 정보를 컬럼으로 표시
            meta_cols = st.columns(3)

            with meta_cols[0]:
                if q.question_type:
                    st.markdown(f"**Type:** `{q.question_type}`")
            with meta_cols[1]:
                if q.response_base:
                    st.markdown(f"**Base:** {q.response_base}")
            with meta_cols[2]:
                if q.instructions:
                    st.markdown(f"**Instructions:** _{q.instructions}_")

            # 필터
            if q.filter_condition:
                st.markdown(f"**Filter:** {q.filter_condition}")

            # 응답 보기
            if q.answer_options:
                st.markdown("**Answer Options:**")
                opts_data = [{"Code": o.code, "Label": o.label} for o in q.answer_options]
                st.dataframe(
                    pd.DataFrame(opts_data),
                    hide_index=True,
                    use_container_width=True,
                    height=min(35 * len(opts_data) + 38, 400)
                )

            # 스킵 로직
            if q.skip_logic:
                st.markdown("**Skip Logic:**")
                for sl in q.skip_logic:
                    st.markdown(f"- {sl.condition} → {sl.target}")
