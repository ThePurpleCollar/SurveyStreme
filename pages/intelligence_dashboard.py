"""Intelligence Dashboard UI 페이지.

추출 완료 후 설문지 전체를 한눈에 파악할 수 있는 요약 대시보드.
LLM 호출 없음 — 순수 계산 기반.
"""

import re
from collections import Counter
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

from models.survey import SurveyDocument, SurveyQuestion
from services.skip_logic_service import build_skip_logic_graph, generate_dot

# ---------------------------------------------------------------------------
# LOI 추정 상수 (초 단위)
# ---------------------------------------------------------------------------

_TYPE_SECONDS: Dict[str, int] = {
    "SA": 10,
    "MA": 20,
    "OE": 30,
    "NUMERIC": 8,
    "Scale": 15,
}

_DEFAULT_SECONDS = 12          # 유형 미상 문항 기본 응답 시간
_GRID_DEFAULT_ROWS = 5         # Grid/Matrix 기본 행 수
_GRID_SECONDS_PER_CELL = 8     # Grid 셀당 응답 시간
_TOPN_SECONDS = 25             # TopN 유형 응답 시간

_GRID_ROW_RE = re.compile(r'(\d+)\s*(?:pt|point|항목|row)', re.IGNORECASE)
_GRID_COL_RE = re.compile(r'x\s*(\d+)', re.IGNORECASE)

# ---------------------------------------------------------------------------
# 핵심 함수
# ---------------------------------------------------------------------------


def _estimate_loi_quick(questions: List[SurveyQuestion]) -> int:
    """유형별 가중치를 적용한 빠른 LOI 추정 (분 단위 반환)."""
    total_seconds = 0
    for q in questions:
        qtype = (q.question_type or "").strip().upper()
        if not qtype:
            total_seconds += _DEFAULT_SECONDS
            continue

        # Grid/Matrix: "Npt x M" 형태 처리
        if "X" in qtype or "GRID" in qtype or "MATRIX" in qtype or "NPT" in qtype:
            rows = _GRID_DEFAULT_ROWS
            row_match = _GRID_ROW_RE.search(q.question_type or "")
            if row_match:
                rows = int(row_match.group(1))
            col_match = _GRID_COL_RE.search(q.question_type or "")
            cols = int(col_match.group(1)) if col_match else 1
            total_seconds += rows * _GRID_SECONDS_PER_CELL * cols
            continue

        # Scale 계열
        if "SCALE" in qtype or "PT" in qtype:
            total_seconds += _TYPE_SECONDS.get("Scale", 15)
            continue

        # TopN
        if "TOPN" in qtype or "TOP" in qtype:
            total_seconds += _TOPN_SECONDS
            continue

        # 일반 유형 매칭
        matched = False
        for key, secs in _TYPE_SECONDS.items():
            if key in qtype:
                total_seconds += secs
                matched = True
                break
        if not matched:
            total_seconds += _DEFAULT_SECONDS

    return max(1, round(total_seconds / 60))


def _skip_complexity(questions: List[SurveyQuestion]) -> str:
    """스킵 로직 복잡도를 Low/Medium/High로 반환."""
    skip_count = sum(1 for q in questions if q.skip_logic)
    ratio = skip_count / len(questions) if questions else 0

    if ratio < 0.1:
        return "Low"
    elif ratio < 0.3:
        return "Medium"
    else:
        return "High"


def _normalize_type(raw_type: str) -> str:
    """문항 유형을 정규화하여 분류 가능한 카테고리로 반환."""
    if not raw_type:
        return "Unknown"
    t = raw_type.strip().upper()
    if "X" in t or "GRID" in t or "MATRIX" in t:
        return "Grid/Matrix"
    if "NPT" in t and "X" not in t:
        return "Scale"
    if "SCALE" in t or "PT" in t:
        return "Scale"
    if "TOPN" in t or "TOP" in t:
        return "TopN"
    if t == "SA":
        return "SA"
    if t == "MA":
        return "MA"
    if t == "OE":
        return "OE"
    if t == "NUMERIC":
        return "Numeric"
    # 부분 매칭
    if "SA" in t:
        return "SA"
    if "MA" in t:
        return "MA"
    if "OE" in t:
        return "OE"
    return raw_type.strip() if raw_type.strip() else "Unknown"


# ---------------------------------------------------------------------------
# 렌더링 함수
# ---------------------------------------------------------------------------


def _render_summary_metrics(doc: SurveyDocument, questions: List[SurveyQuestion]) -> None:
    """Row 1: 핵심 지표 4칸."""
    type_set = set(_normalize_type(q.question_type) for q in questions)
    type_set.discard("Unknown")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Questions", len(questions))
    with col2:
        st.metric("Question Types", len(type_set) if type_set else "-")
    with col3:
        loi = _estimate_loi_quick(questions)
        st.metric("Est. LOI", f"{loi} min")
    with col4:
        complexity = _skip_complexity(questions)
        st.metric("Skip Complexity", complexity)


def _render_section_flow(questions: List[SurveyQuestion]) -> None:
    """Phase 5 role 기반 섹션 흐름도 (Graphviz)."""
    st.subheader("Survey Structure Flow")

    # role 필드가 있는 문항만 처리
    roles = [q.role for q in questions if q.role]
    if not roles:
        st.caption("No role metadata available. Run Questionnaire Analyzer with enrichment first.")
        return

    # 연속 동일 role을 그룹으로 묶기
    sections: List[Tuple[str, int]] = []
    current_role = None
    current_count = 0
    for role in roles:
        if role == current_role:
            current_count += 1
        else:
            if current_role is not None:
                sections.append((current_role, current_count))
            current_role = role
            current_count = 1
    if current_role is not None:
        sections.append((current_role, current_count))

    if not sections:
        st.caption("No sections detected.")
        return

    # Graphviz DOT 생성
    _ROLE_COLORS = {
        "screening": "#FFE0B2",
        "demographics": "#B3E5FC",
        "awareness": "#C8E6C9",
        "usage_experience": "#F0F4C3",
        "evaluation": "#E1BEE7",
        "intent_loyalty": "#FFCDD2",
        "other": "#E0E0E0",
    }

    lines = ['digraph SectionFlow {']
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box, style="filled,rounded", fontsize=11, fontname="Arial"];')
    lines.append('  edge [color="#666666", penwidth=1.5];')
    lines.append('')

    for i, (role, count) in enumerate(sections):
        color = _ROLE_COLORS.get(role, "#E0E0E0")
        label = f"{role.replace('_', ' ').title()}\\n({count} Qs)"
        node_id = f"section_{i}"
        lines.append(f'  {node_id} [label="{label}", fillcolor="{color}"];')

    lines.append('')

    for i in range(len(sections) - 1):
        lines.append(f'  section_{i} -> section_{i + 1};')

    lines.append('}')
    dot_str = '\n'.join(lines)

    st.graphviz_chart(dot_str, use_container_width=True)


def _render_type_distribution(questions: List[SurveyQuestion]) -> None:
    """문항 유형 분포 수평 바 차트 + 테이블."""
    st.subheader("Question Type Distribution")

    type_counter = Counter(_normalize_type(q.question_type) for q in questions)
    if not type_counter:
        st.caption("No question type data available.")
        return

    # 내림차순 정렬
    sorted_types = type_counter.most_common()
    max_count = sorted_types[0][1] if sorted_types else 1

    for qtype, count in sorted_types:
        col_label, col_bar, col_count = st.columns([2, 6, 1])
        with col_label:
            st.text(qtype)
        with col_bar:
            st.progress(count / max_count if max_count > 0 else 0)
        with col_count:
            st.text(str(count))


def _render_role_distribution(questions: List[SurveyQuestion]) -> None:
    """Phase 5 role & variable_type 분포."""
    st.subheader("Role & Variable Type Distribution")

    roles = [q.role for q in questions if q.role]
    var_types = [q.variable_type for q in questions if q.variable_type]

    if not roles and not var_types:
        st.caption("No enrichment metadata available. Run Questionnaire Analyzer with enrichment first.")
        return

    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**Role Distribution**")
        if roles:
            role_counter = Counter(roles)
            sorted_roles = role_counter.most_common()
            max_count = sorted_roles[0][1] if sorted_roles else 1
            for role, count in sorted_roles:
                label = role.replace("_", " ").title()
                col_l, col_b, col_c = st.columns([3, 5, 1])
                with col_l:
                    st.text(label)
                with col_b:
                    st.progress(count / max_count if max_count > 0 else 0)
                with col_c:
                    st.text(str(count))
        else:
            st.caption("No role data.")

    with col_right:
        st.markdown("**Variable Type Distribution**")
        if var_types:
            vt_counter = Counter(var_types)
            sorted_vts = vt_counter.most_common()
            max_count = sorted_vts[0][1] if sorted_vts else 1
            for vtype, count in sorted_vts:
                label = vtype.replace("_", " ").title()
                col_l, col_b, col_c = st.columns([3, 5, 1])
                with col_l:
                    st.text(label)
                with col_b:
                    st.progress(count / max_count if max_count > 0 else 0)
                with col_c:
                    st.text(str(count))
        else:
            st.caption("No variable type data.")


def _render_skip_logic_overview(questions: List[SurveyQuestion]) -> None:
    """스킵 로직 통계 + 미니 그래프 프리뷰."""
    st.subheader("Skip Logic Overview")

    graph = build_skip_logic_graph(questions)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Questions with Skip", graph.questions_with_skip)
    with col2:
        st.metric("Total Skip Rules", graph.total_skip_rules)
    with col3:
        st.metric("Unique Targets", graph.unique_targets)

    # 미니 그래프 프리뷰 (skip_only)
    if graph.questions_with_skip > 0:
        dot = generate_dot(graph, view_mode="skip_only", orientation="LR")
        with st.expander("Skip Logic Graph Preview", expanded=False):
            st.graphviz_chart(dot, use_container_width=True)

    if graph.unparsed_targets:
        with st.expander(f"Unresolved Targets ({len(graph.unparsed_targets)})"):
            df = pd.DataFrame(graph.unparsed_targets, columns=["Source Q#", "Raw Target"])
            st.dataframe(df, use_container_width=True, hide_index=True)


def _render_analytical_readiness(doc: SurveyDocument, questions: List[SurveyQuestion]) -> None:
    """배너 & 분석 준비도 정보."""
    st.subheader("Analytical Readiness")

    banner_count = len(doc.banners)
    banner_points = sum(len(b.points) for b in doc.banners)
    composite_count = sum(1 for b in doc.banners if b.banner_type == "composite")
    composite_ratio = (composite_count / banner_count * 100) if banner_count > 0 else 0

    high_value = sum(1 for q in questions if q.analytical_value == "high")
    high_ratio = (high_value / len(questions) * 100) if questions else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Banners", banner_count)
    with col2:
        st.metric("Banner Points", banner_points)
    with col3:
        st.metric("Composite Ratio", f"{composite_ratio:.0f}%")
    with col4:
        st.metric("High-Value Qs", f"{high_value} ({high_ratio:.0f}%)")

    # Study metadata
    if doc.study_type or doc.client_brand or doc.study_objective:
        with st.expander("Study Metadata", expanded=False):
            if doc.client_brand:
                st.markdown(f"**Client/Brand:** {doc.client_brand}")
            if doc.study_type:
                st.markdown(f"**Study Type:** {doc.study_type}")
            if doc.study_objective:
                st.markdown(f"**Objective:** {doc.study_objective}")
            if doc.research_objectives:
                st.markdown("**Research Objectives:**")
                for obj in doc.research_objectives:
                    st.markdown(f"- {obj}")


def _render_quality_quick_scan() -> None:
    """Quality Checker 결과가 있으면 간략 요약."""
    if 'quality_results' not in st.session_state:
        return

    st.subheader("Quality Quick Scan")

    results = st.session_state['quality_results']
    if isinstance(results, dict):
        issues = results.get('issues', [])
        if issues:
            st.warning(f"**{len(issues)}** quality issue(s) detected. See Quality Checker for details.")
            # 최대 5개만 표시
            for issue in issues[:5]:
                if isinstance(issue, dict):
                    st.caption(f"- {issue.get('description', str(issue))}")
                else:
                    st.caption(f"- {issue}")
            if len(issues) > 5:
                st.caption(f"... and {len(issues) - 5} more")
        else:
            st.success("No quality issues detected.")
    elif isinstance(results, str):
        st.info(results[:500])


# ---------------------------------------------------------------------------
# 메인 페이지 함수
# ---------------------------------------------------------------------------


def page_intelligence_dashboard() -> None:
    """Intelligence Dashboard 메인 진입점."""
    st.title("Intelligence Dashboard")

    # Guard clause
    if "survey_document" not in st.session_state or st.session_state["survey_document"] is None:
        st.warning(
            'Please process a document in "Questionnaire Analyzer" first.'
        )
        return

    doc: SurveyDocument = st.session_state["survey_document"]
    questions = doc.questions

    if not questions:
        st.warning("No questions found in the document.")
        return

    st.info(f"**{doc.filename}** — {len(questions)} questions extracted")

    # Row 1: 핵심 지표
    _render_summary_metrics(doc, questions)

    st.divider()

    # Section Flow
    _render_section_flow(questions)

    st.divider()

    # Type Distribution
    _render_type_distribution(questions)

    st.divider()

    # Role & Variable Type
    _render_role_distribution(questions)

    st.divider()

    # Skip Logic Overview
    _render_skip_logic_overview(questions)

    st.divider()

    # Analytical Readiness
    _render_analytical_readiness(doc, questions)

    # Quality Quick Scan (optional)
    _render_quality_quick_scan()
