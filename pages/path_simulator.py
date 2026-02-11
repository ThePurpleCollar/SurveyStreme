"""Path Simulator UI 페이지.

SurveyDocument의 스킵 로직 그래프를 분석하여
테스트 경로 시뮬레이션 + 테스트 시나리오를 표시한다.
LLM 불필요 — 버튼 클릭 시 즉시 계산.
"""

import io
import pandas as pd
import streamlit as st

from services.path_simulator import (
    parse_condition,
    simulate_paths,
    trace_path,
    SimulationResult,
    SimulatedPath,
)
from services.skip_logic_service import build_skip_logic_graph


def page_path_simulator():
    st.title("Path Simulator")

    # Guard clause
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            'Please process a DOCX document in "Questionnaire Analyzer" first.',
        )
        return

    survey_doc = st.session_state["survey_document"]
    questions = survey_doc.questions
    if not questions:
        st.warning("No questions found in the document.")
        return

    st.info(
        f"Found **{len(questions)}** questions in **{survey_doc.filename}**. "
        "Click **Analyze Paths** to simulate all possible survey paths.",
    )

    # Analyze button
    if st.button("Analyze Paths", type="primary"):
        st.session_state.pop("traced_path", None)
        with st.spinner("Analyzing paths..."):
            result = simulate_paths(questions)
            st.session_state["path_simulator_result"] = result

    # Results
    if "path_simulator_result" not in st.session_state:
        return

    result: SimulationResult = st.session_state["path_simulator_result"]

    st.divider()

    # Dashboard metrics
    _render_dashboard(result)

    # Graph analysis warnings
    _render_graph_warnings(result)

    st.divider()

    # Tabs
    tab_scenarios, tab_tracer, tab_paths = st.tabs(
        ["Test Scenarios", "Interactive Tracer", "All Paths"]
    )

    with tab_scenarios:
        _render_test_scenarios(result)

    with tab_tracer:
        _render_interactive_tracer(questions)

    with tab_paths:
        _render_all_paths(result)


def _render_dashboard(result: SimulationResult):
    """요약 메트릭 4칸."""
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Paths", result.total_paths)
    with col2:
        st.metric("Longest Path", result.max_path_length)
    with col3:
        st.metric("Shortest Path", result.min_path_length)
    with col4:
        st.metric("Branch Coverage", f"{result.branch_coverage_percent:.0f}%")


def _render_graph_warnings(result: SimulationResult):
    """그래프 분석 경고 표시."""
    analysis = result.graph_analysis

    if analysis.unreachable_questions:
        qns = ", ".join(analysis.unreachable_questions)
        st.warning(
            f"**Unreachable questions detected:** {qns}\n\n"
            "These questions cannot be reached from the first question through any path.",
        )

    if analysis.loop_detected:
        for loop in analysis.loop_details[:3]:
            cycle = " -> ".join(loop)
            st.warning(f"**Loop detected:** {cycle}")

    if result.unparsed_conditions:
        items = [f"- **{qn}**: `{cond}`" for qn, cond in result.unparsed_conditions[:10]]
        st.info(
            f"**{len(result.unparsed_conditions)}** skip condition(s) could not be parsed:\n\n"
            + "\n".join(items),
        )


def _render_test_scenarios(result: SimulationResult):
    """테스트 시나리오 테이블 + Excel 다운로드."""
    scenarios = result.test_scenarios

    if not scenarios:
        st.info("No test scenarios generated (no skip logic found).")
        return

    st.subheader(f"Test Scenarios ({len(scenarios)})")

    rows = []
    for ts in scenarios:
        answers_str = ", ".join(f"{k}={v}" for k, v in ts.answer_selections.items())
        path_str = " -> ".join(ts.expected_path[:10])
        if len(ts.expected_path) > 10:
            path_str += f" ... ({len(ts.expected_path)} total)"
        branches_str = ", ".join(ts.verified_branches[:5])
        if len(ts.verified_branches) > 5:
            branches_str += f" ... ({len(ts.verified_branches)} total)"

        rows.append({
            "#": ts.scenario_id,
            "Priority": ts.priority,
            "Description": ts.description,
            "Answers": answers_str,
            "Expected Path": path_str,
            "Branches Verified": branches_str,
        })

    df = pd.DataFrame(rows)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "#": st.column_config.NumberColumn("#", width="small"),
            "Priority": st.column_config.TextColumn("Priority", width="small"),
            "Description": st.column_config.TextColumn("Description", width="medium"),
            "Answers": st.column_config.TextColumn("Answers", width="medium"),
            "Expected Path": st.column_config.TextColumn("Expected Path", width="large"),
            "Branches Verified": st.column_config.TextColumn("Branches", width="medium"),
        },
    )

    # Excel download
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name="Test Scenarios")
    buffer.seek(0)
    st.download_button(
        label="Download Scenarios (Excel)",
        data=buffer,
        file_name="test_scenarios.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _render_interactive_tracer(questions):
    """인터랙티브 경로 추적기."""
    st.subheader("Interactive Tracer")
    st.caption("Select answers for questions with skip logic, then click 'Trace Path'.")

    graph = build_skip_logic_graph(questions)

    # 스킵 로직이 있는 문항만 selectbox 표시
    questions_with_skip = [q for q in questions if q.skip_logic]

    if not questions_with_skip:
        st.info("No questions with skip logic found. The path is purely sequential.")
        if st.button("Show Sequential Path", key="trace_sequential"):
            path = trace_path(questions, graph, {})
            _render_traced_path(path)
        return

    answer_selections: dict = {}

    for q in questions_with_skip:
        options = ["(No selection)"]
        if q.answer_options:
            options += [f"{o.code}. {o.label}" for o in q.answer_options]
        else:
            # 스킵 조건에서 코드 추출
            codes = set()
            for sl in q.skip_logic:
                cond = parse_condition(sl.condition)
                if cond.is_parsed:
                    codes.update(cond.answer_codes)
            if codes:
                options += sorted(codes)

        q_label = f"{q.question_number}: {q.question_text[:60]}"
        if len(q.question_text) > 60:
            q_label += "..."

        selected = st.selectbox(
            q_label,
            options=options,
            key=f"tracer_{q.question_number}",
        )

        if selected and selected != "(No selection)":
            # 코드만 추출 ("1. 매우 그렇다" → "1")
            code = selected.split(".")[0].strip()
            answer_selections[q.question_number] = code

    if st.button("Trace Path", type="primary", key="trace_btn"):
        path = trace_path(questions, graph, answer_selections)
        st.session_state["traced_path"] = path

    if "traced_path" in st.session_state:
        _render_traced_path(st.session_state["traced_path"])


def _render_traced_path(path: SimulatedPath):
    """추적 결과 경로 표시."""
    st.divider()
    st.subheader(f"Traced Path ({path.length} steps)")

    # 경로 요약
    qn_display = " -> ".join(path.question_numbers[:15])
    if len(path.question_numbers) > 15:
        qn_display += f" ... ({path.length} total)"
    st.code(qn_display, language=None)

    # 상세 스텝
    for step in path.steps:
        skip_info = f" **SKIP -> {step.skip_triggered}**" if step.skip_triggered else ""
        answer_info = f" [Answer: {step.selected_answer}]" if step.selected_answer else ""
        terminal_info = " (TERMINAL)" if step.is_terminal and not step.skip_triggered else ""

        st.markdown(
            f"`{step.question_number}` ({step.question_type}) "
            f"{step.question_text[:80]}{answer_info}{skip_info}{terminal_info}"
        )


def _render_all_paths(result: SimulationResult):
    """모든 경로 expander 표시."""
    paths = result.all_paths

    if not paths:
        st.info("No paths found.")
        return

    st.subheader(f"All Paths ({len(paths)})")

    if len(paths) > 50:
        st.caption(f"Showing first 50 of {len(paths)} paths.")
        paths_to_show = paths[:50]
    else:
        paths_to_show = paths

    for path in paths_to_show:
        qn_summary = " -> ".join(path.question_numbers[:10])
        if len(path.question_numbers) > 10:
            qn_summary += " ..."

        label = f"Path #{path.path_id} ({path.length} steps): {qn_summary}"

        with st.expander(label):
            for step in path.steps:
                skip_info = f" **-> {step.skip_triggered}**" if step.skip_triggered else ""
                terminal = " (END)" if step.is_terminal else ""
                st.markdown(
                    f"- `{step.question_number}` ({step.question_type}) "
                    f"{step.question_text[:80]}{skip_info}{terminal}"
                )
