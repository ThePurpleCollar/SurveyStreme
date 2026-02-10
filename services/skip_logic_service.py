"""Skip Logic Visualizer 핵심 서비스.

SurveyDocument의 문항 스킵 로직을 파싱하여
그래프 구조(노드/엣지) + DOT 문자열 + 상세 테이블을 생성한다.
LLM 불필요 — 순수 데이터 변환 (regex 파싱 + 그래프 빌드).
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from models.survey import SurveyQuestion

# ---------------------------------------------------------------------------
# 파싱 패턴
# ---------------------------------------------------------------------------

# 문항 번호 패턴: Q1, SQ1a, Q2_1, SC2, BVT11 등
_TARGET_QN_PATTERN = re.compile(
    r'\b([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)\b', re.IGNORECASE
)

# 종료 패턴
_END_PATTERNS = re.compile(
    r'종료|terminate|end\s*(survey|interview|questionnaire)|screen\s*out|탈락',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class GraphEdge:
    source: str           # "Q1"
    target: str           # "Q5" or "END"
    edge_type: str        # "sequential" | "skip" | "filter"
    label: str            # 조건 텍스트 (sequential은 빈 문자열)
    original_target: str  # 파싱 전 원문


@dataclass
class SkipLogicGraph:
    nodes: List[str]                          # 문항 번호 순서 리스트
    node_types: Dict[str, str]                # Q# → question_type
    node_labels: Dict[str, str]               # Q# → 문항 텍스트 (truncated)
    edges: List[GraphEdge]                    # 모든 엣지
    questions_with_skip: int                  # 스킵 로직 있는 문항 수
    total_skip_rules: int                     # 총 스킵 규칙 수
    unique_targets: int                       # 고유 타겟 수
    unparsed_targets: List[Tuple[str, str]]   # (source_qn, raw_target)


# ---------------------------------------------------------------------------
# Target 파싱
# ---------------------------------------------------------------------------


def parse_target(target_text: str) -> Optional[str]:
    """스킵 로직 target 텍스트에서 문항 번호 또는 'END'를 추출.

    Returns:
        문항 번호 (대문자), ``"END"``, 또는 ``None`` (파싱 불가).
    """
    if not target_text or not target_text.strip():
        return None

    text = target_text.strip()

    # 종료 패턴 먼저 체크
    if _END_PATTERNS.search(text):
        return "END"

    # 문항 번호 추출
    match = _TARGET_QN_PATTERN.search(text)
    if match:
        return match.group(1).upper()

    return None


# ---------------------------------------------------------------------------
# 그래프 빌드
# ---------------------------------------------------------------------------


def build_skip_logic_graph(questions: List[SurveyQuestion]) -> SkipLogicGraph:
    """문항 리스트에서 SkipLogicGraph를 빌드한다."""
    if not questions:
        return SkipLogicGraph(
            nodes=[], node_types={}, node_labels={}, edges=[],
            questions_with_skip=0, total_skip_rules=0,
            unique_targets=0, unparsed_targets=[],
        )

    # 노드 구축
    nodes = [q.question_number for q in questions]
    node_types: Dict[str, str] = {}
    node_labels: Dict[str, str] = {}
    for q in questions:
        qn = q.question_number
        node_types[qn] = q.question_type or "Unknown"
        label = q.question_text
        if len(label) > 40:
            label = label[:37] + "..."
        node_labels[qn] = label

    # 정규화 룩업 (대소문자 매칭)
    norm_lookup: Dict[str, str] = {qn.upper(): qn for qn in nodes}

    edges: List[GraphEdge] = []
    unparsed_targets: List[Tuple[str, str]] = []
    has_end = False
    skip_target_set: set = set()
    questions_with_skip = 0
    total_skip_rules = 0

    # 순차 엣지
    for i in range(len(questions) - 1):
        edges.append(GraphEdge(
            source=questions[i].question_number,
            target=questions[i + 1].question_number,
            edge_type="sequential",
            label="",
            original_target="",
        ))

    # 스킵 엣지
    for q in questions:
        if not q.skip_logic:
            continue
        questions_with_skip += 1
        for sl in q.skip_logic:
            total_skip_rules += 1
            parsed = parse_target(sl.target)
            if parsed is None:
                unparsed_targets.append((q.question_number, sl.target))
                continue
            if parsed == "END":
                has_end = True
                skip_target_set.add("END")
                edges.append(GraphEdge(
                    source=q.question_number,
                    target="END",
                    edge_type="skip",
                    label=_truncate(sl.condition, 30),
                    original_target=sl.target,
                ))
            else:
                # 정규화된 문항 번호로 매칭
                resolved = norm_lookup.get(parsed, parsed)
                skip_target_set.add(resolved)
                edges.append(GraphEdge(
                    source=q.question_number,
                    target=resolved,
                    edge_type="skip",
                    label=_truncate(sl.condition, 30),
                    original_target=sl.target,
                ))

    # 필터 엣지 (역참조)
    for q in questions:
        if not q.filter_condition:
            continue
        match = _TARGET_QN_PATTERN.search(q.filter_condition)
        if match:
            ref_qn = match.group(1).upper()
            resolved = norm_lookup.get(ref_qn, ref_qn)
            edges.append(GraphEdge(
                source=resolved,
                target=q.question_number,
                edge_type="filter",
                label=_truncate(q.filter_condition, 30),
                original_target=q.filter_condition,
            ))

    # END 노드
    if has_end:
        nodes_final = nodes + ["END"]
        node_types["END"] = "END"
        node_labels["END"] = "End"
    else:
        nodes_final = nodes

    return SkipLogicGraph(
        nodes=nodes_final,
        node_types=node_types,
        node_labels=node_labels,
        edges=edges,
        questions_with_skip=questions_with_skip,
        total_skip_rules=total_skip_rules,
        unique_targets=len(skip_target_set),
        unparsed_targets=unparsed_targets,
    )


# ---------------------------------------------------------------------------
# DOT 생성
# ---------------------------------------------------------------------------

_NODE_COLORS: Dict[str, str] = {
    "SA": "#B3D9FF",
    "MA": "#B3FFB3",
    "OE": "#FFFFB3",
    "NUMERIC": "#FFD9B3",
    "Npt": "#D9B3FF",
    "Npt x M": "#D9B3FF",
    "TopN": "#FFB3D9",
    "MATRIX": "#B3FFE0",
    "Unknown": "#E8E8E8",
    "END": "#FF6B6B",
}

_EDGE_STYLES: Dict[str, dict] = {
    "sequential": {"color": "#CCCCCC", "style": "solid", "penwidth": "1.0"},
    "skip":       {"color": "#0066CC", "style": "bold",  "penwidth": "2.0"},
    "filter":     {"color": "#CC6600", "style": "dashed", "penwidth": "1.5"},
}


def generate_dot(
    graph: SkipLogicGraph,
    view_mode: str = "skip_only",
    orientation: str = "TB",
) -> str:
    """SkipLogicGraph에서 Graphviz DOT 문자열을 생성한다.

    Args:
        graph: 빌드된 그래프.
        view_mode: ``"skip_only"`` (스킵 관련 문항만) 또는 ``"full_flow"`` (전체).
        orientation: ``"TB"`` (위→아래) 또는 ``"LR"`` (왼→오른).
    """
    lines: List[str] = []
    lines.append(f'digraph SkipLogic {{')
    lines.append(f'  rankdir={orientation};')
    lines.append('  node [shape=box, style="filled,rounded", fontsize=10, fontname="Arial"];')
    lines.append('  edge [fontsize=8, fontname="Arial"];')
    lines.append('')

    # 뷰 모드에 따라 표시할 노드/엣지 필터링
    if view_mode == "skip_only":
        # 스킵/필터 엣지에 관련된 노드만
        relevant_nodes: set = set()
        relevant_edges: List[GraphEdge] = []
        for e in graph.edges:
            if e.edge_type in ("skip", "filter"):
                relevant_nodes.add(e.source)
                relevant_nodes.add(e.target)
                relevant_edges.append(e)
    else:
        relevant_nodes = set(graph.nodes)
        relevant_edges = graph.edges

    # 노드 생성
    for node in graph.nodes:
        if node not in relevant_nodes:
            continue
        qtype = graph.node_types.get(node, "Unknown")
        color = _NODE_COLORS.get(qtype, _NODE_COLORS["Unknown"])
        label = f"{node}\\n{qtype}"
        lines.append(f'  "{node}" [label="{label}", fillcolor="{color}"];')

    lines.append('')

    # 엣지 생성
    for e in relevant_edges:
        style_info = _EDGE_STYLES.get(e.edge_type, _EDGE_STYLES["sequential"])
        attrs = [
            f'color="{style_info["color"]}"',
            f'style="{style_info["style"]}"',
            f'penwidth={style_info["penwidth"]}',
        ]
        if e.label:
            escaped_label = e.label.replace('"', '\\"')
            attrs.append(f'label="{escaped_label}"')
        lines.append(f'  "{e.source}" -> "{e.target}" [{", ".join(attrs)}];')

    lines.append('}')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 상세 테이블
# ---------------------------------------------------------------------------


def build_detail_table(
    questions: List[SurveyQuestion],
    graph: SkipLogicGraph,
) -> pd.DataFrame:
    """스킵 로직 상세 테이블을 DataFrame으로 반환."""
    # 노드 셋 (타겟 존재 여부 확인용)
    node_set = set(graph.nodes)
    unparsed_set = {(src, tgt) for src, tgt in graph.unparsed_targets}

    rows = []
    for q in questions:
        if not q.skip_logic:
            continue
        for sl in q.skip_logic:
            parsed = parse_target(sl.target)
            if parsed is None:
                status = "Unresolved"
            elif parsed == "END":
                status = "END"
            elif parsed in node_set or parsed in {n.upper() for n in node_set}:
                status = "Resolved"
            else:
                status = "Not Found"
            rows.append({
                "From Q#": q.question_number,
                "Condition": sl.condition,
                "Target Text": sl.target,
                "Parsed Target": parsed or sl.target,
                "Status": status,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "From Q#", "Condition", "Target Text", "Parsed Target", "Status"
        ])

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
