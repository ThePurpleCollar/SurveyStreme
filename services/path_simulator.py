"""Path Simulator 핵심 서비스.

SurveyDocument의 스킵 로직 그래프를 기반으로
가능한 설문 경로를 열거하고 테스트 시나리오를 생성한다.
LLM 불필요 — 순수 알고리즘.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from models.survey import SurveyQuestion
from services.skip_logic_service import (
    build_skip_logic_graph,
    parse_target,
    SkipLogicGraph,
    GraphEdge,
)

# ---------------------------------------------------------------------------
# 조건 파싱 패턴
# ---------------------------------------------------------------------------

# "Q1=1 또는 2 응답자", "Q3=3,4", "Q5 = 1~3" 등에서 Q#과 코드 추출
_CONDITION_PATTERN = re.compile(
    r'([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)'   # Q 번호
    r'\s*[=≠]\s*'                           # = 또는 ≠
    r'([\d,~\-\s또는or/and및]+)',            # 코드 목록
    re.IGNORECASE,
)

_CODE_SPLIT = re.compile(r'[,\s또는or/and및~\-]+', re.IGNORECASE)


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class ConditionRef:
    question_number: str        # "Q1"
    answer_codes: List[str]     # ["1", "2"]
    raw_text: str               # 원본 조건 텍스트
    is_parsed: bool             # 파싱 성공 여부


@dataclass
class PathStep:
    question_number: str
    question_text: str          # 표시용 (100자 제한)
    question_type: str
    selected_answer: Optional[str] = None
    skip_triggered: Optional[str] = None
    is_terminal: bool = False


@dataclass
class SimulatedPath:
    path_id: int
    steps: List[PathStep]
    description: str = ""

    @property
    def length(self) -> int:
        return len(self.steps)

    @property
    def question_numbers(self) -> List[str]:
        return [s.question_number for s in self.steps]


@dataclass
class TestScenario:
    scenario_id: int
    description: str                     # "Q1=1 → Q5 스킵 테스트"
    answer_selections: Dict[str, str]    # {"Q1": "1", "Q3": "2"}
    expected_path: List[str]             # ["Q1", "Q5", "Q6", ...]
    verified_branches: List[str]         # ["Q1→Q5"]
    priority: str = "REQUIRED"           # REQUIRED | RECOMMENDED


@dataclass
class GraphAnalysis:
    unreachable_questions: List[str]     # 도달 불가 문항
    loop_detected: bool
    loop_details: List[List[str]]        # 순환 경로
    terminal_points: List[str]           # 종료 지점


@dataclass
class SimulationResult:
    all_paths: List[SimulatedPath]
    test_scenarios: List[TestScenario]
    graph_analysis: GraphAnalysis
    total_questions: int
    total_skip_rules: int
    unparsed_conditions: List[Tuple[str, str]]

    @property
    def total_paths(self) -> int:
        return len(self.all_paths)

    @property
    def max_path_length(self) -> int:
        if not self.all_paths:
            return 0
        return max(p.length for p in self.all_paths)

    @property
    def min_path_length(self) -> int:
        if not self.all_paths:
            return 0
        return min(p.length for p in self.all_paths)

    @property
    def branch_coverage_percent(self) -> float:
        """테스트 시나리오가 커버하는 스킵 분기 비율."""
        if self.total_skip_rules == 0:
            return 100.0
        covered = set()
        for ts in self.test_scenarios:
            covered.update(ts.verified_branches)
        return min(100.0, len(covered) / self.total_skip_rules * 100)


# ---------------------------------------------------------------------------
# 조건 파싱
# ---------------------------------------------------------------------------


def parse_condition(condition_text: str) -> ConditionRef:
    """스킵 로직 condition 텍스트에서 문항 번호와 응답 코드를 추출.

    "Q1=1 또는 2 응답자" → ConditionRef("Q1", ["1","2"], ..., True)
    파싱 불가 시 is_parsed=False.
    """
    if not condition_text or not condition_text.strip():
        return ConditionRef("", [], condition_text or "", False)

    m = _CONDITION_PATTERN.search(condition_text)
    if not m:
        return ConditionRef("", [], condition_text, False)

    qn = m.group(1).upper()
    codes_raw = m.group(2).strip()
    codes = [c.strip() for c in _CODE_SPLIT.split(codes_raw) if c.strip() and c.strip().isdigit()]

    if not codes:
        return ConditionRef(qn, [], condition_text, False)

    return ConditionRef(qn, codes, condition_text, True)


# ---------------------------------------------------------------------------
# 그래프 분석
# ---------------------------------------------------------------------------


def analyze_graph(
    graph: SkipLogicGraph,
    questions: List[SurveyQuestion],
) -> GraphAnalysis:
    """DFS 기반 도달성 분석 + 순환 탐지."""
    if not questions:
        return GraphAnalysis([], False, [], [])

    question_nodes = [q.question_number for q in questions]
    node_set = set(question_nodes)
    first_node = question_nodes[0]

    # 인접 리스트 구축 (question 노드만)
    adj: Dict[str, List[str]] = {qn: [] for qn in question_nodes}
    adj["END"] = []
    for edge in graph.edges:
        if edge.source in adj:
            adj[edge.source].append(edge.target)

    # BFS 도달성
    reachable = set()
    queue = [first_node]
    reachable.add(first_node)
    while queue:
        curr = queue.pop(0)
        for nxt in adj.get(curr, []):
            if nxt not in reachable:
                reachable.add(nxt)
                queue.append(nxt)

    unreachable = [qn for qn in question_nodes if qn not in reachable]

    # 순환 탐지 (DFS)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {qn: WHITE for qn in question_nodes}
    color["END"] = WHITE
    parent_path: Dict[str, List[str]] = {}
    loops: List[List[str]] = []

    def _dfs_cycle(node: str, path: List[str]):
        color[node] = GRAY
        for nxt in adj.get(node, []):
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                # 사이클 발견 — 현재 경로에서 nxt부터 추출
                cycle_start = path.index(nxt) if nxt in path else -1
                if cycle_start >= 0:
                    cycle = path[cycle_start:] + [nxt]
                    loops.append(cycle)
            elif color[nxt] == WHITE:
                _dfs_cycle(nxt, path + [nxt])
        color[node] = BLACK

    for qn in question_nodes:
        if color[qn] == WHITE:
            _dfs_cycle(qn, [qn])

    # 종료 지점: END로 가는 엣지가 있는 소스 또는 마지막 문항
    terminal_points = []
    for edge in graph.edges:
        if edge.target == "END" and edge.edge_type == "skip":
            terminal_points.append(edge.source)
    # 마지막 문항도 종료 지점
    if question_nodes:
        last_q = question_nodes[-1]
        if last_q not in terminal_points:
            terminal_points.append(last_q)

    return GraphAnalysis(
        unreachable_questions=unreachable,
        loop_detected=len(loops) > 0,
        loop_details=loops[:10],  # 최대 10개
        terminal_points=terminal_points,
    )


# ---------------------------------------------------------------------------
# 경로 열거
# ---------------------------------------------------------------------------


def enumerate_paths(
    questions: List[SurveyQuestion],
    graph: SkipLogicGraph,
    max_paths: int = 500,
) -> List[SimulatedPath]:
    """DFS로 모든 가능 경로를 열거한다.

    각 문항에서 순차 진행과 스킵 분기를 모두 탐색.
    루프 감지 + max_paths 제한.
    """
    if not questions:
        return []

    question_nodes = [q.question_number for q in questions]
    node_set = set(question_nodes)
    qn_to_q: Dict[str, SurveyQuestion] = {q.question_number: q for q in questions}
    qn_to_idx: Dict[str, int] = {qn: i for i, qn in enumerate(question_nodes)}

    # 스킵 엣지 맵: source → [(target, condition_label)]
    skip_map: Dict[str, List[Tuple[str, str]]] = {}
    for edge in graph.edges:
        if edge.edge_type == "skip":
            skip_map.setdefault(edge.source, []).append((edge.target, edge.label))

    paths: List[SimulatedPath] = []
    path_id = [0]

    def _make_step(qn: str, answer: Optional[str] = None,
                   skip_to: Optional[str] = None) -> PathStep:
        q = qn_to_q.get(qn)
        text = q.question_text[:100] if q else ""
        qtype = q.question_type or "Unknown" if q else "Unknown"
        return PathStep(
            question_number=qn,
            question_text=text,
            question_type=qtype,
            selected_answer=answer,
            skip_triggered=skip_to,
        )

    def _dfs(current_qn: str, steps: List[PathStep], visited: set):
        if len(paths) >= max_paths:
            return

        if current_qn == "END" or current_qn not in node_set:
            # 종료 — 경로 완성
            if steps:
                steps[-1].is_terminal = True
                path_id[0] += 1
                qn_list = [s.question_number for s in steps]
                desc = " -> ".join(qn_list[:8])
                if len(qn_list) > 8:
                    desc += f" ... ({len(qn_list)} steps)"
                paths.append(SimulatedPath(
                    path_id=path_id[0],
                    steps=list(steps),
                    description=desc,
                ))
            return

        if current_qn in visited:
            # 루프 감지 — 경로 종료
            if steps:
                steps[-1].is_terminal = True
                path_id[0] += 1
                paths.append(SimulatedPath(
                    path_id=path_id[0],
                    steps=list(steps),
                    description=" -> ".join(s.question_number for s in steps) + " (loop)",
                ))
            return

        visited_new = visited | {current_qn}

        # 옵션 1: 순차 진행 (다음 문항으로)
        idx = qn_to_idx.get(current_qn)
        next_qn = question_nodes[idx + 1] if idx is not None and idx + 1 < len(question_nodes) else None

        # 옵션 2: 스킵 분기들
        skip_targets = skip_map.get(current_qn, [])

        if not skip_targets:
            # 스킵 없음 — 순차 진행만
            step = _make_step(current_qn)
            steps.append(step)
            if next_qn:
                _dfs(next_qn, steps, visited_new)
            else:
                # 마지막 문항
                step.is_terminal = True
                path_id[0] += 1
                paths.append(SimulatedPath(
                    path_id=path_id[0],
                    steps=list(steps),
                    description=" -> ".join(s.question_number for s in steps),
                ))
            steps.pop()
        else:
            # 분기 1: 순차 진행 (스킵 조건에 해당하지 않는 경우)
            step_seq = _make_step(current_qn)
            steps.append(step_seq)
            if next_qn:
                _dfs(next_qn, steps, visited_new)
            else:
                step_seq.is_terminal = True
                path_id[0] += 1
                paths.append(SimulatedPath(
                    path_id=path_id[0],
                    steps=list(steps),
                    description=" -> ".join(s.question_number for s in steps),
                ))
            steps.pop()

            # 분기 2+: 각 스킵 타겟으로
            for target, label in skip_targets:
                if len(paths) >= max_paths:
                    break
                step_skip = _make_step(current_qn, skip_to=target)
                steps.append(step_skip)
                _dfs(target, steps, visited_new)
                steps.pop()

    # 첫 문항부터 시작
    _dfs(question_nodes[0], [], set())

    return paths


# ---------------------------------------------------------------------------
# 특정 경로 추적
# ---------------------------------------------------------------------------


def trace_path(
    questions: List[SurveyQuestion],
    graph: SkipLogicGraph,
    answer_selections: Dict[str, str],
) -> SimulatedPath:
    """사용자 응답 선택에 따른 특정 경로를 추적한다.

    answer_selections: {"Q1": "1", "Q3": "2"} — 스킵 로직 조건 매칭에 사용.
    선택되지 않은 문항은 순차 진행.
    """
    if not questions:
        return SimulatedPath(path_id=0, steps=[], description="Empty")

    question_nodes = [q.question_number for q in questions]
    node_set = set(question_nodes)
    qn_to_q: Dict[str, SurveyQuestion] = {q.question_number: q for q in questions}
    qn_to_idx: Dict[str, int] = {qn: i for i, qn in enumerate(question_nodes)}

    # 스킵 엣지 맵
    skip_edges: Dict[str, List[Tuple[str, str, str]]] = {}  # source → [(target, condition, label)]
    for edge in graph.edges:
        if edge.edge_type == "skip":
            skip_edges.setdefault(edge.source, []).append(
                (edge.target, edge.label, edge.original_target)
            )

    steps: List[PathStep] = []
    visited = set()
    current_qn = question_nodes[0]

    while current_qn and current_qn in node_set and current_qn not in visited:
        visited.add(current_qn)
        q = qn_to_q.get(current_qn)
        text = q.question_text[:100] if q else ""
        qtype = q.question_type or "Unknown" if q else "Unknown"

        selected = answer_selections.get(current_qn)
        skip_to = None

        # 스킵 조건 매칭
        if selected and current_qn in skip_edges:
            for target, cond_label, orig in skip_edges[current_qn]:
                cond_ref = parse_condition(cond_label)
                if not cond_ref.is_parsed:
                    # 조건 파싱 불가 시 원본 텍스트에서 재시도
                    cond_ref = parse_condition(orig)
                # 파싱된 조건의 Q#이 현재 문항이고 선택한 코드가 포함되면 스킵
                if cond_ref.is_parsed and selected in cond_ref.answer_codes:
                    skip_to = target
                    break

        step = PathStep(
            question_number=current_qn,
            question_text=text,
            question_type=qtype,
            selected_answer=selected,
            skip_triggered=skip_to,
        )
        steps.append(step)

        if skip_to:
            if skip_to == "END":
                step.is_terminal = True
                break
            current_qn = skip_to
        else:
            idx = qn_to_idx.get(current_qn)
            if idx is not None and idx + 1 < len(question_nodes):
                current_qn = question_nodes[idx + 1]
            else:
                step.is_terminal = True
                break

    if steps:
        steps[-1].is_terminal = True

    qn_list = [s.question_number for s in steps]
    desc = " -> ".join(qn_list[:8])
    if len(qn_list) > 8:
        desc += f" ... ({len(qn_list)} steps)"

    return SimulatedPath(path_id=0, steps=steps, description=desc)


# ---------------------------------------------------------------------------
# 테스트 시나리오 생성
# ---------------------------------------------------------------------------


def generate_test_scenarios(
    questions: List[SurveyQuestion],
    graph: SkipLogicGraph,
) -> List[TestScenario]:
    """Greedy set-cover: 모든 스킵 분기를 커버하는 최소 시나리오를 생성한다."""
    if not questions:
        return []

    question_nodes = [q.question_number for q in questions]
    qn_to_q: Dict[str, SurveyQuestion] = {q.question_number: q for q in questions}

    # 모든 스킵 분기 수집: (source, target, condition_label)
    all_branches: List[Tuple[str, str, str]] = []
    for edge in graph.edges:
        if edge.edge_type == "skip":
            branch_id = f"{edge.source}->{edge.target}"
            all_branches.append((edge.source, edge.target, edge.label))

    if not all_branches:
        # 스킵 없음 — 순차 경로 1개만
        path = trace_path(questions, graph, {})
        return [TestScenario(
            scenario_id=1,
            description="Sequential path (no skip logic)",
            answer_selections={},
            expected_path=path.question_numbers,
            verified_branches=[],
            priority="REQUIRED",
        )]

    uncovered = set(range(len(all_branches)))
    scenarios: List[TestScenario] = []
    scenario_id = 0

    # 각 분기마다 시나리오 생성 (greedy)
    while uncovered:
        # 가장 많은 미커버 분기를 커버하는 단일 답변 조합 찾기
        best_selections: Dict[str, str] = {}
        best_covered: set = set()

        for idx in list(uncovered):
            source, target, cond_label = all_branches[idx]
            cond_ref = parse_condition(cond_label)

            # 이 분기를 트리거하는 답변 선택
            selections: Dict[str, str] = {}
            if cond_ref.is_parsed and cond_ref.answer_codes:
                selections[cond_ref.question_number] = cond_ref.answer_codes[0]
            else:
                # 파싱 불가 — 강제로 source 문항에 코드 "1" 설정
                selections[source] = "1"

            # 이 선택으로 커버되는 분기들 계산
            covered_by_this: set = set()
            for j in uncovered:
                s2, t2, c2 = all_branches[j]
                c2_ref = parse_condition(c2)
                if c2_ref.is_parsed and c2_ref.question_number in selections:
                    if selections[c2_ref.question_number] in c2_ref.answer_codes:
                        covered_by_this.add(j)
                elif s2 == source:
                    covered_by_this.add(j)

            if not covered_by_this:
                covered_by_this.add(idx)

            if len(covered_by_this) > len(best_covered):
                best_covered = covered_by_this
                best_selections = selections

        if not best_covered:
            # 안전장치 — 하나씩 제거
            idx = next(iter(uncovered))
            best_covered = {idx}
            source, target, cond_label = all_branches[idx]
            best_selections = {source: "1"}

        uncovered -= best_covered
        scenario_id += 1

        # 경로 추적
        path = trace_path(questions, graph, best_selections)
        verified = [f"{all_branches[i][0]}->{all_branches[i][1]}" for i in best_covered]

        # 설명 생성
        selections_desc = ", ".join(f"{k}={v}" for k, v in best_selections.items())
        desc = f"Test {selections_desc} ({len(verified)} branches)"

        scenarios.append(TestScenario(
            scenario_id=scenario_id,
            description=desc,
            answer_selections=best_selections,
            expected_path=path.question_numbers,
            verified_branches=verified,
            priority="REQUIRED" if scenario_id <= 5 else "RECOMMENDED",
        ))

    return scenarios


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def simulate_paths(questions: List[SurveyQuestion]) -> SimulationResult:
    """경로 시뮬레이션 메인 함수.

    build_skip_logic_graph() 재사용 → 그래프 분석 + 경로 열거 + 시나리오 생성.
    """
    if not questions:
        return SimulationResult(
            all_paths=[],
            test_scenarios=[],
            graph_analysis=GraphAnalysis([], False, [], []),
            total_questions=0,
            total_skip_rules=0,
            unparsed_conditions=[],
        )

    graph = build_skip_logic_graph(questions)
    analysis = analyze_graph(graph, questions)
    paths = enumerate_paths(questions, graph)
    scenarios = generate_test_scenarios(questions, graph)

    # 파싱 불가 조건 수집
    unparsed: List[Tuple[str, str]] = []
    for q in questions:
        for sl in q.skip_logic:
            cond_ref = parse_condition(sl.condition)
            if not cond_ref.is_parsed:
                unparsed.append((q.question_number, sl.condition))

    return SimulationResult(
        all_paths=paths,
        test_scenarios=scenarios,
        graph_analysis=analysis,
        total_questions=len(questions),
        total_skip_rules=graph.total_skip_rules,
        unparsed_conditions=unparsed,
    )
