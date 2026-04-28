"""Skip Logic Visualizer UI 페이지.

Questionnaire Analyzer에서 추출된 SurveyDocument의 문항 스킵 로직을
파싱하여 시각적 흐름 그래프 + 상세 테이블로 표시한다.
LLM 불필요 — 페이지 로드 시 즉시 렌더링.
"""

import streamlit as st

from services.skip_logic_service import (
    build_skip_logic_graph,
    generate_dot,
    build_detail_table,
    SkipLogicGraph,
)


def page_skip_logic_visualizer():
    st.title("Skip Logic Visualizer")

    # Guard clause: survey_document 없으면 안내
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            '먼저 Questionnaire Analyzer에서 문서를 처리해주세요.',
            icon="⚠️",
        )
        return

    survey_doc = st.session_state["survey_document"]
    questions = survey_doc.questions
    if not questions:
        st.warning("문서에서 문항을 찾을 수 없습니다.", icon="⚠️")
        return

    # 그래프 빌드 (즉시, LLM 없음)
    graph = build_skip_logic_graph(questions)

    # 스킵 로직이 전혀 없는 경우
    if graph.questions_with_skip == 0:
        st.info(
            f"**{survey_doc.filename}**에서 **{len(questions)}**개 문항을 발견했지만, "
            "스킵 로직이 정의된 문항이 없습니다.",
            icon="ℹ️",
        )
        return

    # ── 요약 대시보드 ──
    _render_dashboard(graph, len(questions))

    st.divider()

    # ── 컨트롤 영역 ──
    ctrl_col1, ctrl_col2 = st.columns(2)
    with ctrl_col1:
        view_mode = st.radio(
            "보기 모드",
            ["skip_only", "full_flow"],
            format_func=lambda x: "스킵만" if x == "skip_only" else "전체 흐름",
            horizontal=True,
            key="skip_logic_view_mode",
        )
    with ctrl_col2:
        orientation = st.radio(
            "방향",
            ["TB", "LR"],
            format_func=lambda x: "위 → 아래" if x == "TB" else "왼쪽 → 오른쪽",
            horizontal=True,
            key="skip_logic_orientation",
        )

    # ── 그래프 시각화 ──
    dot_string = generate_dot(graph, view_mode=view_mode, orientation=orientation)
    st.graphviz_chart(dot_string, use_container_width=True)

    # ── 파싱 불가 타겟 경고 ──
    _render_unparsed_warning(graph)

    st.divider()

    # ── 상세 테이블 ──
    _render_detail_table(questions, graph)


def _render_dashboard(graph: SkipLogicGraph, total_questions: int):
    """요약 메트릭 4칸."""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 문항", total_questions)
    with col2:
        st.metric("스킵 로직 보유", graph.questions_with_skip)
    with col3:
        st.metric("전체 스킵 규칙", graph.total_skip_rules)
    with col4:
        st.metric("고유 타겟", graph.unique_targets)


def _render_unparsed_warning(graph: SkipLogicGraph):
    """파싱 불가 타겟 경고."""
    if not graph.unparsed_targets:
        return

    items = [f"- **{src}**: `{tgt}`" for src, tgt in graph.unparsed_targets]
    st.warning(
        f"**{len(graph.unparsed_targets)}**건의 스킵 타겟을 파싱할 수 없습니다:\n\n"
        + "\n".join(items),
        icon="⚠️",
    )


def _render_detail_table(questions, graph: SkipLogicGraph):
    """스킵 로직 상세 테이블."""
    st.subheader("스킵 로직 상세")

    df = build_detail_table(questions, graph)
    if df.empty:
        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "From Q#": st.column_config.TextColumn("From Q#", width="small"),
            "Condition": st.column_config.TextColumn("Condition", width="large"),
            "Target Text": st.column_config.TextColumn("Target Text", width="medium"),
            "Parsed Target": st.column_config.TextColumn("Parsed Target", width="small"),
            "Status": st.column_config.TextColumn("Status", width="small"),
        },
    )
