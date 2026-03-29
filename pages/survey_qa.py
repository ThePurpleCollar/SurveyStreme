"""Survey QA — 설문 로직 시각화 + 테스트 시나리오 + 체크리스트 통합.

3개 메뉴(Skip Logic, Path Simulator, Checklist)와
Quality Checker의 알고리즘 검출을 하나로 통합한다.
"""

import io
import pandas as pd
import streamlit as st
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from services.path_simulator import (
    simulate_paths,
    generate_persona_scenarios,
    SimulationResult,
    PersonaScenario,
)
from services.skip_logic_service import build_skip_logic_graph
from services.checklist_generator import generate_checklist
from services.prescripting_checker import (
    run_algorithmic_checks,
    ReviewReport,
    CATEGORY_LABELS,
    SEVERITY_LABELS,
)


def page_survey_qa():
    st.title("Survey QA")

    # Guard
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning("먼저 Questionnaire Analyzer에서 문서를 처리해주세요.", icon="⚠️")
        return

    survey_doc = st.session_state["survey_document"]
    questions = survey_doc.questions
    if not questions:
        st.warning("문서에서 문항을 찾을 수 없습니다.", icon="⚠️")
        return

    st.info(f"**{survey_doc.filename}** — **{len(questions)}**개 문항", icon="🔍")

    # ── 분석 실행 버튼 ──
    run_clicked = st.button("QA 분석 실행", type="primary", use_container_width=True)

    if run_clicked:
        with st.status("QA 분석 중...", expanded=True) as status:
            # 1. 경로 시뮬레이션
            status.write("경로 시뮬레이션 중...")
            result = simulate_paths(questions)
            st.session_state["qa_simulation"] = result

            # 2. 페르소나 생성
            status.write("페르소나 시나리오 생성 중...")
            personas = generate_persona_scenarios(questions)
            st.session_state["qa_personas"] = personas

            # 3. 알고리즘 검출 (Quality Checker 통합)
            status.write("설문 구조 검증 중...")
            review = run_algorithmic_checks(questions)
            st.session_state["qa_review"] = review

            # 4. 체크리스트 생성 (알고리즘만, LLM 없이)
            status.write("체크리스트 생성 중...")
            checklist = generate_checklist(questions, language="ko", use_llm=False)
            st.session_state["qa_checklist"] = checklist

            total_issues = review.critical_count + review.warning_count + len(checklist.items)
            status.update(
                label=f"QA 분석 완료! 시나리오 {len(result.test_scenarios)}건, "
                      f"페르소나 {len(personas)}건, 체크항목 {total_issues}건",
                state="complete",
            )

    # ── 결과 표시 ──
    if "qa_simulation" not in st.session_state:
        st.caption("**QA 분석 실행** 버튼을 눌러 시작하세요.")
        return

    result = st.session_state["qa_simulation"]
    personas = st.session_state.get("qa_personas", [])
    review = st.session_state.get("qa_review", ReviewReport())
    checklist = st.session_state.get("qa_checklist")

    # ── 요약 메트릭 ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("전체 경로", result.total_paths)
    with col2:
        st.metric("분기 커버리지", f"{result.branch_coverage_percent:.0f}%")
    with col3:
        st.metric("이슈", review.critical_count + review.warning_count,
                  delta=f"심각 {review.critical_count}" if review.critical_count else None,
                  delta_color="inverse")
    with col4:
        st.metric("페르소나", len(personas))

    st.divider()

    # ── 탭 ──
    tab_logic, tab_persona, tab_branch, tab_checklist = st.tabs([
        "로직 시각화", "페르소나 시나리오", "분기 테스트", "체크리스트"
    ])

    with tab_logic:
        _render_logic_visualization(questions, result)

    with tab_persona:
        _render_personas(personas)

    with tab_branch:
        _render_branch_tests(result)

    with tab_checklist:
        _render_checklist(review, checklist, questions)

    # ── 통합 다운로드 ──
    st.divider()
    excel_data = _build_qa_excel(result, personas, review, checklist)
    st.download_button(
        label="Survey QA 가이드 다운로드 (Excel)",
        data=excel_data,
        file_name="survey_qa_guide.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ══════════════════════════════════════════════════════════════
# 탭 1: 로직 시각화
# ══════════════════════════════════════════════════════════════

def _render_logic_visualization(questions, result: SimulationResult):
    """스킵 로직 Graphviz 시각화."""
    from services.skip_logic_service import build_skip_logic_graph, render_skip_logic_dot

    graph = build_skip_logic_graph(questions)

    if not graph.edges:
        st.info("스킵 로직이 없습니다. 모든 문항이 순차 진행됩니다.")
        return

    col1, col2 = st.columns(2)
    with col1:
        view_mode = st.radio("보기 모드", ["스킵만", "전체 흐름"],
                             horizontal=True, key="qa_view_mode")
    with col2:
        orientation = st.radio("방향", ["위 → 아래", "왼쪽 → 오른쪽"],
                               horizontal=True, key="qa_orientation")

    skip_only = view_mode == "스킵만"
    rankdir = "TB" if orientation == "위 → 아래" else "LR"

    dot_str = render_skip_logic_dot(graph, questions, skip_only=skip_only, rankdir=rankdir)
    st.graphviz_chart(dot_str)

    # 경고
    analysis = result.graph_analysis
    if analysis.unreachable_questions:
        st.warning(f"**도달 불가 문항:** {', '.join(analysis.unreachable_questions)}")
    if analysis.loop_detected:
        for loop in analysis.loop_details[:3]:
            st.warning(f"**루프 감지:** {' → '.join(loop)}")
    if result.unparsed_conditions:
        with st.expander(f"파싱 불가 조건 ({len(result.unparsed_conditions)}건)"):
            for qn, cond in result.unparsed_conditions[:10]:
                st.markdown(f"- **{qn}**: `{cond}`")


# ══════════════════════════════════════════════════════════════
# 탭 2: 페르소나 시나리오
# ══════════════════════════════════════════════════════════════

def _render_personas(personas):
    """페르소나 기반 테스트 시나리오."""
    if not personas:
        st.info("스크리닝/인구통계 문항이 없어 페르소나를 생성할 수 없습니다.")
        return

    st.subheader(f"페르소나 시나리오 ({len(personas)}건)")
    st.caption("인구통계/스크리닝 문항의 보기 조합으로 자동 생성된 대표 응답자 경로입니다.")

    for p in personas:
        icon = "🚫" if p.is_termination else "👤"
        with st.expander(
            f"{icon} 시나리오 {p.persona_id}: {p.persona_label} ({p.path_length}문항)",
            expanded=(p.persona_id <= 2),
        ):
            sel_parts = [f"**{qn}**: {p.answer_labels.get(qn, '')} ({code})"
                         for qn, code in p.answer_selections.items()]
            st.markdown("**응답 선택:** " + " | ".join(sel_parts))

            path_str = " → ".join(p.expected_path[:15])
            if len(p.expected_path) > 15:
                path_str += f" ... (총 {len(p.expected_path)}문항)"
            st.markdown(f"**경로:** {path_str}")

            if p.is_termination:
                st.warning("이 페르소나는 스크리닝에서 탈락합니다. 탈락 처리가 올바른지 확인하세요.")


# ══════════════════════════════════════════════════════════════
# 탭 3: 분기 테스트
# ══════════════════════════════════════════════════════════════

def _render_branch_tests(result: SimulationResult):
    """분기 커버리지 테스트 시나리오."""
    scenarios = result.test_scenarios
    if not scenarios:
        st.info("스킵 로직이 없어 분기 테스트가 필요하지 않습니다.")
        return

    st.subheader(f"분기 테스트 ({len(scenarios)}건)")
    st.caption(f"분기 커버리지: **{result.branch_coverage_percent:.0f}%**")

    rows = []
    for ts in scenarios:
        answer_parts = []
        for k, v in ts.answer_selections.items():
            label = ts.answer_labels.get(k, "")
            if label and not label.startswith("코드"):
                answer_parts.append(f"{k}: {label}({v})")
            else:
                answer_parts.append(f"{k}={v}")

        rows.append({
            "#": ts.scenario_id,
            "우선순위": ts.priority,
            "응답 선택": ", ".join(answer_parts),
            "예상 경로": " → ".join(ts.expected_path[:10]),
            "검증 분기": ", ".join(ts.verified_branches[:5]),
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
# 탭 4: 체크리스트
# ══════════════════════════════════════════════════════════════

def _render_checklist(review: ReviewReport, checklist, questions):
    """알고리즘 검출 + 체크리스트 통합."""
    all_items = []

    # Quality Checker 알고리즘 검출 결과
    for item in review.items:
        all_items.append({
            "severity": item.severity,
            "category": CATEGORY_LABELS.get(item.category, item.category),
            "question": item.question_number,
            "title": item.title,
            "detail": item.detail,
            "source": "구조 검증",
        })

    # Checklist Generator 결과
    pri_to_sev = {"HIGH": "critical", "MEDIUM": "warning", "LOW": "info"}
    if checklist:
        for item in checklist.items:
            all_items.append({
                "severity": pri_to_sev.get(item.priority, "info"),
                "category": item.category,
                "question": item.question_number,
                "title": item.title,
                "detail": item.detail,
                "source": item.source,
            })

    if not all_items:
        st.success("이슈가 발견되지 않았습니다! 스크립팅을 진행해도 좋습니다.", icon="✅")
        return

    # 심각도별 카운트
    sev_count = {"critical": 0, "warning": 0, "info": 0}
    for item in all_items:
        sev_count[item["severity"]] = sev_count.get(item["severity"], 0) + 1

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("심각", sev_count["critical"])
    with col2:
        st.metric("경고", sev_count["warning"])
    with col3:
        st.metric("참고", sev_count["info"])

    # 필터
    severity_filter = st.radio(
        "필터",
        options=["all", "critical", "warning", "info"],
        format_func=lambda x: {"all": "전체", "critical": "심각만", "warning": "경고만", "info": "참고만"}[x],
        horizontal=True,
        key="qa_checklist_filter",
    )

    filtered = all_items if severity_filter == "all" else [i for i in all_items if i["severity"] == severity_filter]

    severity_icon = {"critical": "🔴", "warning": "⚠️", "info": "ℹ️"}

    for item in filtered:
        icon = severity_icon.get(item["severity"], "")
        sev_label = SEVERITY_LABELS.get(item["severity"], item["severity"])
        with st.expander(f"{icon} [{sev_label}] {item['title']}", expanded=(item["severity"] == "critical")):
            st.markdown(f"**카테고리:** {item['category']}  |  **문항:** {item['question']}  |  **출처:** {item['source']}")
            st.markdown(item["detail"])


# ══════════════════════════════════════════════════════════════
# 통합 엑셀
# ══════════════════════════════════════════════════════════════

def _build_qa_excel(result, personas, review, checklist) -> bytes:
    """Survey QA 통합 엑셀."""
    wb = Workbook()
    hdr_fill = PatternFill(start_color="0033A0", end_color="0033A0", fill_type="solid")
    hdr_font = Font(color="FFFFFF", bold=True, size=10)
    center = Alignment(horizontal="center", vertical="center")
    wrap = Alignment(wrap_text=True, vertical="top")

    def _style_header(ws):
        for cell in ws[1]:
            cell.fill = hdr_fill
            cell.font = hdr_font
            cell.alignment = center

    # ── Sheet 1: 페르소나 시나리오 ──
    ws1 = wb.active
    ws1.title = "페르소나 시나리오"
    ws1.append(["#", "페르소나", "응답 선택", "예상 경로", "경로 길이", "탈락"])
    _style_header(ws1)

    for p in (personas or []):
        sel = ", ".join(f"{qn}: {p.answer_labels.get(qn, '')}({code})"
                        for qn, code in p.answer_selections.items())
        ws1.append([p.persona_id, p.persona_label, sel,
                    " → ".join(p.expected_path[:15]), p.path_length,
                    "탈락" if p.is_termination else ""])

    for row in ws1.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    for col, w in zip('ABCDEF', [5, 35, 45, 50, 10, 8]):
        ws1.column_dimensions[col].width = w

    # ── Sheet 2: 분기 테스트 ──
    ws2 = wb.create_sheet("분기 테스트")
    ws2.append(["#", "우선순위", "응답 선택", "예상 경로", "검증 분기"])
    _style_header(ws2)

    for ts in (result.test_scenarios if result else []):
        answer_parts = []
        for k, v in ts.answer_selections.items():
            label = ts.answer_labels.get(k, "")
            if label and not label.startswith("코드"):
                answer_parts.append(f"{k}: {label}({v})")
            else:
                answer_parts.append(f"{k}={v}")
        ws2.append([ts.scenario_id, ts.priority, ", ".join(answer_parts),
                    " → ".join(ts.expected_path[:15]),
                    ", ".join(ts.verified_branches[:8])])

    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    for col, w in zip('ABCDE', [5, 12, 45, 50, 35]):
        ws2.column_dimensions[col].width = w

    # ── Sheet 3: 체크리스트 ──
    ws3 = wb.create_sheet("체크리스트")
    ws3.append(["확인", "심각도", "카테고리", "문항", "제목", "상세"])
    _style_header(ws3)

    critical_fill = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")
    warning_fill = PatternFill(start_color="FFF9C4", end_color="FFF9C4", fill_type="solid")

    # Quality Checker 검출
    for item in (review.items if review else []):
        row_num = ws3.max_row + 1
        ws3.append(["☐", SEVERITY_LABELS.get(item.severity, ""),
                    CATEGORY_LABELS.get(item.category, item.category),
                    item.question_number, item.title, item.detail])
        if item.severity == "critical":
            for cell in ws3[row_num]:
                cell.fill = critical_fill
        elif item.severity == "warning":
            for cell in ws3[row_num]:
                cell.fill = warning_fill

    # Checklist Generator 검출
    pri_map = {"HIGH": "심각", "MEDIUM": "경고", "LOW": "참고"}
    for item in (checklist.items if checklist else []):
        row_num = ws3.max_row + 1
        ws3.append(["☐", pri_map.get(item.priority, ""),
                    item.category, item.question_number, item.title, item.detail])
        if item.priority == "HIGH":
            for cell in ws3[row_num]:
                cell.fill = critical_fill
        elif item.priority == "MEDIUM":
            for cell in ws3[row_num]:
                cell.fill = warning_fill

    for row in ws3.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    for col, w in zip('ABCDEF', [5, 8, 14, 10, 40, 55]):
        ws3.column_dimensions[col].width = w

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
