"""Piping Intelligence UI 페이지.

문항 간 데이터 의존성(파이핑, 필터 체인) 시각화 및 이슈 탐지.
"""

import io
from typing import List

import pandas as pd
import streamlit as st

from services.llm_client import DEFAULT_MODEL
from services.piping_service import (
    PipingAnalysisResult,
    PipingRef,
    PipingIssue,
    FilterChain,
    analyze_piping,
    generate_piping_dot,
    _PIPE_TYPE_LABELS,
    _PIPING_EDGE_STYLES,
)


def page_piping_intelligence() -> None:
    """Piping Intelligence 메인 진입점."""
    st.title("Piping Intelligence")

    # Guard clause
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            'Please process a document in "Questionnaire Analyzer" first.'
        )
        return

    doc = st.session_state["survey_document"]
    questions = doc.questions

    if not questions:
        st.warning("No questions found in the document.")
        return

    st.info(
        f"Found **{len(questions)}** questions in **{doc.filename}**. "
        "Analyze piping dependencies, filter chains, and potential issues."
    )

    # Controls
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([2, 2, 2])
    with ctrl_col1:
        include_implicit = st.checkbox(
            "Include Implicit Piping (LLM)",
            value=False,
            help="Use LLM to detect implicit piping references. Slower but more thorough.",
            key="piping_include_implicit",
        )
    with ctrl_col3:
        analyze_clicked = st.button("Analyze", type="primary")

    # Run analysis
    if analyze_clicked:
        with st.status("Analyzing piping dependencies...", expanded=True) as status:
            progress_bar = st.progress(0)
            log_area = st.empty()

            def _progress_callback(event: str, data: dict):
                if event == "phase":
                    if data["status"] == "start":
                        if data["name"] == "text_piping":
                            log_area.text("Detecting text & code piping, filter dependencies...")
                        elif data["name"] == "implicit_piping":
                            log_area.text("Detecting implicit piping (LLM)...")
                            progress_bar.progress(0.3)
                    elif data["status"] == "done":
                        if data["name"] == "text_piping":
                            log_area.text(f"Algorithmic detection done ({data['count']} refs)")
                            progress_bar.progress(0.3 if include_implicit else 0.8)
                        elif data["name"] == "implicit_piping":
                            log_area.text(f"Implicit detection done ({data['count']} refs)")
                            progress_bar.progress(0.8)
                elif event == "batch_start":
                    total = data["total_batches"]
                    idx = data["batch_index"]
                    log_area.text(f"LLM batch {idx + 1}/{total} ({data['question_count']} questions)...")
                elif event == "batch_done":
                    total = data["total_batches"]
                    idx = data["batch_index"]
                    p = 0.3 + ((idx + 1) / total) * 0.5
                    progress_bar.progress(min(p, 0.8))

            result = analyze_piping(
                questions=questions,
                model=DEFAULT_MODEL,
                include_implicit=include_implicit,
                progress_callback=_progress_callback,
            )

            progress_bar.progress(1.0)
            st.session_state["piping_result"] = result

            total_refs = len(result.piping_refs)
            total_issues = len(result.issues)
            status.update(
                label=f"Done! {total_refs} references, {total_issues} issues found.",
                state="complete",
            )

    # Results
    if "piping_result" not in st.session_state:
        return

    result: PipingAnalysisResult = st.session_state["piping_result"]

    st.divider()

    # Dashboard metrics
    _render_dashboard(result)

    st.divider()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "Dependency Graph",
        "Filter Chains",
        "Issues",
        "All References",
    ])

    with tab1:
        _render_dependency_graph(result, questions)

    with tab2:
        _render_filter_chains(result)

    with tab3:
        _render_issues(result)

    with tab4:
        _render_all_references(result)


# ---------------------------------------------------------------------------
# 렌더링 함수
# ---------------------------------------------------------------------------


def _render_dashboard(result: PipingAnalysisResult) -> None:
    """요약 메트릭 4칸."""
    piping_count = sum(1 for r in result.piping_refs
                       if r.pipe_type in ("text_piping", "code_piping", "implicit_piping"))
    filter_count = sum(1 for r in result.piping_refs
                       if r.pipe_type == "filter_dependency")
    issue_count = len(result.issues)
    bottleneck_count = len(result.bottleneck_questions)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Piping Refs", piping_count)
    with col2:
        st.metric("Filter Deps", filter_count)
    with col3:
        error_count = sum(1 for i in result.issues if i.severity == "error")
        st.metric("Issues", issue_count, delta=f"{error_count} errors" if error_count else None,
                  delta_color="inverse" if error_count else "off")
    with col4:
        st.metric("Bottlenecks", bottleneck_count)


def _render_dependency_graph(result: PipingAnalysisResult, questions) -> None:
    """의존성 그래프 (Graphviz + 유형별 필터)."""
    if not result.piping_refs:
        st.info("No piping references detected.")
        return

    # 유형별 필터
    available_types = list(set(r.pipe_type for r in result.piping_refs))
    type_labels = [_PIPE_TYPE_LABELS.get(t, t) for t in available_types]

    selected_labels = st.multiselect(
        "Show Types",
        options=type_labels,
        default=type_labels,
        key="piping_graph_filter",
    )

    # 라벨 → 타입 역매핑
    label_to_type = {v: k for k, v in _PIPE_TYPE_LABELS.items()}
    show_types = [label_to_type.get(lbl, lbl) for lbl in selected_labels]

    if not show_types:
        st.caption("Select at least one type to display the graph.")
        return

    dot = generate_piping_dot(result.piping_refs, questions, show_types=show_types)
    st.graphviz_chart(dot, use_container_width=True)

    # 범례
    legend_cols = st.columns(len(_PIPING_EDGE_STYLES))
    for col, (ptype, style) in zip(legend_cols, _PIPING_EDGE_STYLES.items()):
        with col:
            label = _PIPE_TYPE_LABELS.get(ptype, ptype)
            color = style["color"]
            st.markdown(
                f'<span style="color:{color}; font-weight:bold;">&#9632;</span> {label}',
                unsafe_allow_html=True,
            )


def _render_filter_chains(result: PipingAnalysisResult) -> None:
    """필터 체인 트리 + 병목 문항."""
    if not result.filter_chains:
        st.info("No filter chains detected.")
        return

    st.subheader("Filter Chains")

    for chain in result.filter_chains:
        with st.expander(
            f"Root: **{chain.root_question}** — {len(chain.dependents)} dependents, "
            f"depth {chain.chain_length}",
            expanded=False,
        ):
            st.markdown(f"**Root:** {chain.root_question}")
            st.markdown(f"**Dependents:** {', '.join(chain.dependents)}")
            st.markdown(f"**Max Chain Length:** {chain.chain_length}")

    # 병목 문항
    if result.bottleneck_questions:
        st.subheader("Bottleneck Questions")
        st.caption("Questions with the most dependent questions.")

        rows = [{"Q#": qn, "Dependent Count": count}
                for qn, count in result.bottleneck_questions[:10]]
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)


def _render_issues(result: PipingAnalysisResult) -> None:
    """이슈 테이블 (severity 뱃지)."""
    if not result.issues:
        st.success("No piping issues detected.")
        return

    st.subheader(f"Issues ({len(result.issues)})")

    _SEVERITY_COLORS = {
        "error": "#FF4B4B",
        "warning": "#FFA500",
        "info": "#4B8BFF",
    }

    for issue in result.issues:
        color = _SEVERITY_COLORS.get(issue.severity, "#999")
        badge = f'<span style="background-color:{color}; color:white; padding:2px 8px; border-radius:4px; font-size:12px;">{issue.severity.upper()}</span>'

        st.markdown(
            f"{badge} **{issue.issue_type.replace('_', ' ').title()}** — {issue.description}",
            unsafe_allow_html=True,
        )
        if issue.involved_questions:
            st.caption(f"Involved: {', '.join(issue.involved_questions)}")


def _render_all_references(result: PipingAnalysisResult) -> None:
    """전체 참조 테이블 + Excel 다운로드."""
    if not result.piping_refs:
        st.info("No piping references detected.")
        return

    st.subheader(f"All References ({len(result.piping_refs)})")

    rows = []
    for ref in result.piping_refs:
        rows.append({
            "Source": ref.source_qn,
            "Target": ref.target_qn,
            "Type": _PIPE_TYPE_LABELS.get(ref.pipe_type, ref.pipe_type),
            "Context": ref.context[:100],
            "Severity": ref.severity,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Source": st.column_config.TextColumn("Source Q#", width="small"),
            "Target": st.column_config.TextColumn("Target Q#", width="small"),
            "Type": st.column_config.TextColumn("Type", width="medium"),
            "Context": st.column_config.TextColumn("Context", width="large"),
            "Severity": st.column_config.TextColumn("Severity", width="small"),
        },
    )

    # Excel 다운로드
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name="Piping References")
    buffer.seek(0)

    st.download_button(
        label="Download References (Excel)",
        data=buffer,
        file_name="piping_references.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
