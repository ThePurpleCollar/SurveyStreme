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
    SimulationResult,
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
    st.title("Logic Checker")

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

            # 2. 알고리즘 검출 (Quality Checker 통합)
            status.write("설문 구조 검증 중...")
            review = run_algorithmic_checks(questions)
            st.session_state["qa_review"] = review

            # 3. 체크리스트 생성 (알고리즘만, LLM 없이)
            status.write("체크리스트 생성 중...")
            checklist = generate_checklist(questions, language="ko", use_llm=False)
            st.session_state["qa_checklist"] = checklist

            total_issues = review.critical_count + review.warning_count + len(checklist.items)
            status.update(
                label=f"QA 분석 완료! 시나리오 {len(result.test_scenarios)}건, "
                      f"체크항목 {total_issues}건",
                state="complete",
            )

    # ── 결과 표시 ──
    if "qa_simulation" not in st.session_state:
        st.caption("**QA 분석 실행** 버튼을 눌러 시작하세요.")
        return

    result = st.session_state["qa_simulation"]
    review = st.session_state.get("qa_review", ReviewReport())
    checklist = st.session_state.get("qa_checklist")

    # ── 요약 메트릭 ──
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("전체 경로", result.total_paths)
    with col2:
        st.metric("분기 커버리지", f"{result.branch_coverage_percent:.0f}%")
    with col3:
        st.metric("이슈", review.critical_count + review.warning_count,
                  delta=f"심각 {review.critical_count}" if review.critical_count else None,
                  delta_color="inverse")

    st.divider()

    # ── 탭 ──
    tab_logic, tab_branch, tab_checklist = st.tabs([
        "로직 시각화", "분기 테스트", "체크리스트"
    ])

    with tab_logic:
        _render_logic_visualization(questions, result)

    with tab_branch:
        _render_branch_tests(result)

    with tab_checklist:
        _render_checklist(review, checklist, questions)

    # ── 통합 다운로드 ──
    st.divider()
    excel_data = _build_qa_excel(result, review, checklist)
    st.download_button(
        label="Logic Checker 결과 다운로드 (Excel)",
        data=excel_data,
        file_name="logic_checker.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ══════════════════════════════════════════════════════════════
# 탭 1: 로직 시각화
# ══════════════════════════════════════════════════════════════

def _render_logic_visualization(questions, result: SimulationResult):
    """스킵 로직 Graphviz 시각화."""
    from services.skip_logic_service import build_skip_logic_graph, generate_dot

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

    mode = "skip_only" if view_mode == "스킵만" else "full_flow"
    rankdir = "TB" if orientation == "위 → 아래" else "LR"

    dot_str = generate_dot(graph, view_mode=mode, orientation=rankdir)
    st.graphviz_chart(dot_str)

    # 범례
    st.caption(
        "━━ 파란 실선: 스킵 로직 (조건부 이동)  |  "
        "┅┅ 주황 점선: 필터 조건 (조건부 표시)  |  "
        "── 회색 실선: 순차 진행"
    )

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
# 탭 2: 분기 테스트
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
# 탭 3: 체크리스트
# ══════════════════════════════════════════════════════════════

def _render_checklist(review: ReviewReport, checklist, questions):
    """알고리즘 검출 + 체크리스트 + 파싱 실패 수동 확인 통합."""
    all_items = []

    # 파싱 실패 조건 → 수동 확인 항목으로 추가
    result = st.session_state.get("qa_simulation")
    if result and result.unparsed_conditions:
        for qn, cond in result.unparsed_conditions:
            all_items.append({
                "severity": "warning",
                "category": "수동 확인 필요",
                "question": qn,
                "title": f"{qn} 스킵 조건 수동 확인 필요",
                "detail": (
                    f"조건 '{cond}'를 자동 파싱할 수 없습니다.\n"
                    f"1. 원본 설문지에서 {qn}의 스킵 조건을 직접 확인\n"
                    f"2. 해당 조건 충족 시 올바른 문항으로 이동하는지 수동 테스트"
                ),
                "source": "파싱 실패",
            })

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

def _build_qa_excel(result, review, checklist) -> bytes:
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

    # ── Sheet 1: 분기 테스트 ──
    ws2 = wb.active
    ws2.title = "분기 테스트"
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
    ws3.append(["순서", "확인", "심각도", "카테고리", "문항", "제목", "상세"])
    _style_header(ws3)

    critical_fill = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")
    warning_fill = PatternFill(start_color="FFF9C4", end_color="FFF9C4", fill_type="solid")

    seq = [0]  # 실행 순서 카운터

    def _add_check_row(sev_label, category, qn, title, detail, fill=None):
        seq[0] += 1
        row_num = ws3.max_row + 1
        ws3.append([seq[0], "☐", sev_label, category, qn, title, detail])
        if fill:
            for cell in ws3[row_num]:
                cell.fill = fill

    # 파싱 실패 조건 → 수동 확인 항목
    if result and result.unparsed_conditions:
        for qn, cond in result.unparsed_conditions:
            _add_check_row("경고", "수동 확인", qn,
                           f"{qn} 스킵 조건 수동 확인",
                           f"조건 '{cond}' 자동 파싱 불가. 원본 확인 후 수동 테스트 필요.",
                           warning_fill)

    # Quality Checker 검출
    for item in (review.items if review else []):
        fill = critical_fill if item.severity == "critical" else (warning_fill if item.severity == "warning" else None)
        _add_check_row(SEVERITY_LABELS.get(item.severity, ""),
                       CATEGORY_LABELS.get(item.category, item.category),
                       item.question_number, item.title, item.detail, fill)

    # Checklist Generator 검출
    pri_map = {"HIGH": "심각", "MEDIUM": "경고", "LOW": "참고"}
    for item in (checklist.items if checklist else []):
        fill = critical_fill if item.priority == "HIGH" else (warning_fill if item.priority == "MEDIUM" else None)
        _add_check_row(pri_map.get(item.priority, ""),
                       item.category, item.question_number, item.title, item.detail, fill)

    for row in ws3.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = wrap
    for col, w in zip('ABCDEFG', [5, 5, 8, 14, 10, 40, 55]):
        ws3.column_dimensions[col].width = w

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
