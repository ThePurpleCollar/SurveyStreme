"""Path Simulator 핵심 서비스.

SurveyDocument의 스킵 로직 그래프를 기반으로
가능한 설문 경로를 열거하고 테스트 시나리오를 생성한다.
LLM 불필요 — 순수 알고리즘.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from models.survey import SurveyQuestion
from services.condition_evaluator import (
    ConditionClause,
    ConditionNode,
    parse_condition_expression,
)
from services.skip_logic_service import (
    build_skip_logic_graph,
    SkipLogicGraph,
)

MAX_TRIGGER_SELECTION_OPTIONS = 12

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
    answer_labels: Dict[str, str] = field(default_factory=dict)  # {"Q1": "남성", "Q3": "20대"}
    expected_path: List[str] = field(default_factory=list)       # ["Q1", "Q5", "Q6", ...]
    verified_branches: List[str] = field(default_factory=list)   # ["Q1→Q5"]
    priority: str = "REQUIRED"           # REQUIRED | RECOMMENDED


@dataclass
class BranchDiagnostic:
    """Per skip-rule coverage diagnosis for QA handoff."""
    branch: str
    source: str
    target: str
    condition: str
    status: str
    severity: str
    detail: str
    candidate_count: int = 0
    truncated: bool = False
    example_selections: Dict[str, str] = field(default_factory=dict)
    example_path: List[str] = field(default_factory=list)


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
    branch_diagnostics: List[BranchDiagnostic] = field(default_factory=list)

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
    """스킵 로직 condition 텍스트에서 첫 조건 clause의 문항/코드를 추출.

    "Q1=1 또는 2 응답자" → ConditionRef("Q1", ["1","2"], ..., True)
    파싱 불가 시 is_parsed=False.

    이 함수는 UI/기존 호출부 호환용 wrapper다. 실제 경로 추적은
    ``condition_evaluator``의 full expression 평가 결과를 사용한다.
    """
    if not condition_text or not condition_text.strip():
        return ConditionRef("", [], condition_text or "", False)

    parsed = parse_condition_expression(condition_text)
    if not parsed.is_parsed or parsed.node is None:
        return ConditionRef("", [], condition_text, False)

    clause = _first_clause(parsed.node)
    if clause is None:
        return ConditionRef("", [], condition_text, False)

    return ConditionRef(
        question_number=clause.question_number,
        answer_codes=list(clause.values),
        raw_text=condition_text,
        is_parsed=True,
    )


def _first_clause(node: ConditionNode) -> Optional[ConditionClause]:
    if isinstance(node, ConditionClause):
        return node
    for child in node.children:
        clause = _first_clause(child)
        if clause is not None:
            return clause
    return None


def _edge_condition_text(edge) -> str:
    return getattr(edge, "original_condition", "") or edge.label


def _answers_for_evaluator(answer_selections: Dict[str, object]) -> Dict[str, object]:
    answers: Dict[str, object] = {}
    for qn, value in answer_selections.items():
        answers[qn] = value
        answers[str(qn).upper()] = value
    return answers


def _get_answer(answer_selections: Dict[str, str], question_number: str) -> Optional[str]:
    return answer_selections.get(question_number) or answer_selections.get(question_number.upper())


def _condition_matches(condition_text: str, answer_selections: Dict[str, object]) -> bool:
    parsed = parse_condition_expression(condition_text)
    if not parsed.is_parsed:
        return False
    return parsed.evaluate(_answers_for_evaluator(answer_selections))


@dataclass
class _SelectionOptionResult:
    options: List[Dict[str, str]]
    truncated: bool = False
    unsatisfiable: bool = False
    reason: str = ""


def _trigger_selections_for_condition(
    condition_text: str,
    questions_by_number: Dict[str, SurveyQuestion],
) -> Dict[str, str]:
    options = _trigger_selection_options_for_condition(condition_text, questions_by_number)
    return options[0] if options else {}


def _trigger_selection_options_for_condition(
    condition_text: str,
    questions_by_number: Dict[str, SurveyQuestion],
) -> List[Dict[str, str]]:
    return _trigger_selection_option_result_for_condition(condition_text, questions_by_number).options


def _trigger_selection_option_result_for_condition(
    condition_text: str,
    questions_by_number: Dict[str, SurveyQuestion],
) -> _SelectionOptionResult:
    parsed = parse_condition_expression(condition_text)
    if not parsed.is_parsed or parsed.node is None:
        return _SelectionOptionResult([], reason="unparsed_condition")
    return _trigger_selection_option_result_for_node(parsed.node, questions_by_number)


def _trigger_selections_for_node(
    node: ConditionNode,
    questions_by_number: Dict[str, SurveyQuestion],
) -> Dict[str, str]:
    options = _trigger_selection_options_for_node(node, questions_by_number)
    return options[0] if options else {}


def _trigger_selection_options_for_node(
    node: ConditionNode,
    questions_by_number: Dict[str, SurveyQuestion],
) -> List[Dict[str, str]]:
    return _trigger_selection_option_result_for_node(node, questions_by_number).options


def _trigger_selection_option_result_for_node(
    node: ConditionNode,
    questions_by_number: Dict[str, SurveyQuestion],
) -> _SelectionOptionResult:
    if isinstance(node, ConditionClause):
        codes, truncated = _trigger_codes_for_clause(node, questions_by_number)
        options = [
            {node.question_number: code}
            for code in codes
        ]
        return _SelectionOptionResult(
            options,
            truncated=truncated,
            unsatisfiable=not options,
            reason="" if options else "no_satisfying_answer_code",
        )

    if node.operator == "and":
        options: List[Dict[str, str]] = [{}]
        truncated = False
        for child in node.children:
            child_result = _trigger_selection_option_result_for_node(child, questions_by_number)
            truncated = truncated or child_result.truncated
            child_options = child_result.options
            if not child_options:
                return _SelectionOptionResult(
                    [],
                    truncated=truncated,
                    unsatisfiable=True,
                    reason=child_result.reason or "no_child_candidates",
                )
            merged_options: List[Dict[str, str]] = []
            seen_merged = set()
            cap_reached = False
            for base in options:
                if cap_reached:
                    break
                for child_selection in child_options:
                    merged = dict(base)
                    conflict = False
                    for qn, code in child_selection.items():
                        existing = merged.get(qn)
                        if existing is not None and existing != code:
                            conflict = True
                            break
                        merged[qn] = code
                    if not conflict:
                        key = tuple(sorted(merged.items()))
                        if key in seen_merged:
                            continue
                        seen_merged.add(key)
                        merged_options.append(merged)
                        if len(merged_options) >= MAX_TRIGGER_SELECTION_OPTIONS:
                            cap_reached = True
                            break
            if cap_reached:
                truncated = True
            options = merged_options
            if not options:
                return _SelectionOptionResult(
                    [],
                    truncated=truncated,
                    unsatisfiable=True,
                    reason="conflicting_and_conditions",
                )
        return _SelectionOptionResult(options, truncated=truncated)

    options = []
    seen_options = set()
    truncated = False
    for child_idx, child in enumerate(node.children):
        child_result = _trigger_selection_option_result_for_node(child, questions_by_number)
        truncated = truncated or child_result.truncated
        for option_idx, option in enumerate(child_result.options):
            key = tuple(sorted(option.items()))
            if key in seen_options:
                continue
            seen_options.add(key)
            options.append(option)
            if len(options) >= MAX_TRIGGER_SELECTION_OPTIONS:
                has_more_current = option_idx + 1 < len(child_result.options)
                has_more_children = child_idx + 1 < len(node.children)
                truncated = truncated or has_more_current or has_more_children
                break
        if len(options) >= MAX_TRIGGER_SELECTION_OPTIONS:
            break
    return _SelectionOptionResult(
        options,
        truncated=truncated,
        unsatisfiable=not options,
        reason="" if options else "no_or_candidates",
    )


def _dedupe_selection_options(options: List[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped = []
    seen = set()
    for option in options:
        key = tuple(sorted(option.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(option)
    return deduped


def _trigger_code_for_clause(
    clause: ConditionClause,
    questions_by_number: Dict[str, SurveyQuestion],
) -> Optional[str]:
    codes, _ = _trigger_codes_for_clause(clause, questions_by_number)
    return codes[0] if codes else None


def _trigger_codes_for_clause(
    clause: ConditionClause,
    questions_by_number: Dict[str, SurveyQuestion],
) -> Tuple[List[str], bool]:
    if clause.operator == "in":
        values = list(clause.values)
        return values[:MAX_TRIGGER_SELECTION_OPTIONS], len(values) > MAX_TRIGGER_SELECTION_OPTIONS

    excluded = set(clause.values)
    q = questions_by_number.get(clause.question_number)
    if q is None:
        q = questions_by_number.get(clause.question_number.upper())
    if q and q.answer_options:
        codes = []
        for opt in q.answer_options:
            code = str(opt.code)
            if code not in excluded:
                codes.append(code)
        return codes[:MAX_TRIGGER_SELECTION_OPTIONS], len(codes) > MAX_TRIGGER_SELECTION_OPTIONS
    return (["1"], False) if "1" not in excluded else ([], False)


def _covered_branch_indices_from_path(
    path: SimulatedPath,
    branches: List[Tuple[str, str, str]],
) -> set:
    """Return skip-rule indices that were actually triggered on a traced path."""
    covered = set()
    observed_answers: Dict[str, str] = {}

    for step in path.steps:
        if step.selected_answer is not None:
            observed_answers[step.question_number] = step.selected_answer

        if not step.skip_triggered:
            continue

        for idx, (source, target, condition_text) in enumerate(branches):
            if source != step.question_number or target != step.skip_triggered:
                continue
            if _condition_matches(condition_text, observed_answers):
                covered.add(idx)

    return covered


def _branch_display(branch: Tuple[str, str, str]) -> str:
    source, target, condition_text = branch
    if condition_text:
        return f"{source}->{target} ({condition_text})"
    return f"{source}->{target}"


def _skip_branches_from_graph(graph: SkipLogicGraph) -> List[Tuple[str, str, str]]:
    return [
        (edge.source, edge.target, _edge_condition_text(edge))
        for edge in graph.edges
        if edge.edge_type == "skip"
    ]


def analyze_branch_diagnostics(
    questions: List[SurveyQuestion],
    graph: SkipLogicGraph,
    scenarios: List[TestScenario],
) -> List[BranchDiagnostic]:
    """Diagnose why each skip branch is or is not covered by generated scenarios."""
    qn_to_q: Dict[str, SurveyQuestion] = {q.question_number: q for q in questions}
    for q in questions:
        qn_to_q[q.question_number.upper()] = q

    branches = _skip_branches_from_graph(graph)
    covered_labels = {
        branch
        for scenario in scenarios
        for branch in scenario.verified_branches
    }
    diagnostics: List[BranchDiagnostic] = []

    for branch in branches:
        source, target, condition_text = branch
        branch_label = _branch_display(branch)
        if branch_label in covered_labels:
            diagnostics.append(BranchDiagnostic(
                branch=branch_label,
                source=source,
                target=target,
                condition=condition_text,
                status="covered",
                severity="info",
                detail="생성된 테스트 시나리오에서 실제 경로가 이 분기를 트리거했습니다.",
            ))
            continue

        parsed = parse_condition_expression(condition_text)
        if not parsed.is_parsed:
            diagnostics.append(BranchDiagnostic(
                branch=branch_label,
                source=source,
                target=target,
                condition=condition_text,
                status="unparsed_condition",
                severity="warning",
                detail="조건식을 자동 파싱할 수 없어 분기 커버리지를 검증하지 못했습니다.",
            ))
            continue

        option_result = _trigger_selection_option_result_for_condition(condition_text, qn_to_q)
        if option_result.unsatisfiable or not option_result.options:
            diagnostics.append(BranchDiagnostic(
                branch=branch_label,
                source=source,
                target=target,
                condition=condition_text,
                status="unsatisfiable_condition",
                severity="critical",
                detail=(
                    "조건을 만족하는 응답 조합을 만들 수 없습니다. "
                    f"원인: {option_result.reason or 'unknown'}"
                ),
                truncated=option_result.truncated,
            ))
            continue

        reached_source = False
        source_path: Optional[SimulatedPath] = None
        source_selections: Dict[str, str] = {}
        for selections in option_result.options:
            path = trace_path(questions, graph, selections)
            if source in path.question_numbers:
                reached_source = True
                source_path = path
                source_selections = selections
                break
            if source_path is None:
                source_path = path
                source_selections = selections

        if option_result.truncated:
            status = "candidate_truncated"
            severity = "warning"
            detail = (
                f"후보 응답 조합이 {MAX_TRIGGER_SELECTION_OPTIONS}개로 제한되어 "
                "일부 조합을 검증하지 못했습니다."
            )
        elif not reached_source:
            status = "source_not_reached"
            severity = "warning"
            detail = (
                "조건을 만족하는 후보 응답은 만들었지만, 앞선 스킵 로직 때문에 "
                "분기 기준 문항에 도달하지 못했습니다."
            )
        else:
            status = "not_triggered_on_trace"
            severity = "warning"
            detail = (
                "분기 기준 문항에는 도달했지만 해당 target으로 이동하지 않았습니다. "
                "동일 문항의 다른 스킵 규칙 우선순위나 조건 구현을 확인해야 합니다."
            )

        diagnostics.append(BranchDiagnostic(
            branch=branch_label,
            source=source,
            target=target,
            condition=condition_text,
            status=status,
            severity=severity,
            detail=detail,
            candidate_count=len(option_result.options),
            truncated=option_result.truncated,
            example_selections=source_selections,
            example_path=source_path.question_numbers if source_path else [],
        ))

    return diagnostics


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
    skip_edges: Dict[str, List[Tuple[str, str]]] = {}  # source → [(target, original_condition)]
    for edge in graph.edges:
        if edge.edge_type == "skip":
            skip_edges.setdefault(edge.source, []).append(
                (edge.target, _edge_condition_text(edge))
            )

    steps: List[PathStep] = []
    visited = set()
    observed_answers: Dict[str, str] = {}
    current_qn = question_nodes[0]

    while current_qn and current_qn in node_set and current_qn not in visited:
        visited.add(current_qn)
        q = qn_to_q.get(current_qn)
        text = q.question_text[:100] if q else ""
        qtype = q.question_type or "Unknown" if q else "Unknown"

        selected = _get_answer(answer_selections, current_qn)
        if selected is not None:
            observed_answers[current_qn] = selected
        skip_to = None

        # 스킵 조건 매칭
        if current_qn in skip_edges:
            for target, condition_text in skip_edges[current_qn]:
                if _condition_matches(condition_text, observed_answers):
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
    for q in questions:
        qn_to_q[q.question_number.upper()] = q

    # 모든 스킵 분기 수집: (source, target, original_condition)
    all_branches = _skip_branches_from_graph(graph)

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

            # 이 분기를 트리거하는 답변 선택
            candidate_selections = _trigger_selection_options_for_condition(cond_label, qn_to_q)
            if not candidate_selections:
                # 파싱 불가 — 강제로 source 문항에 코드 "1" 설정
                candidate_selections = [{source: "1"}]

            for selections in candidate_selections:
                # 이 선택으로 실제 trace에서 발생하는 분기만 커버로 인정
                candidate_path = trace_path(questions, graph, selections)
                covered_by_this = (
                    _covered_branch_indices_from_path(candidate_path, all_branches)
                    & uncovered
                )

                if len(covered_by_this) > len(best_covered):
                    best_covered = covered_by_this
                    best_selections = selections

        if not best_covered:
            # 도달 불가/파싱 불가 분기는 시나리오를 만들되 커버로 과대계상하지 않는다.
            idx = next(iter(uncovered))
            source, target, cond_label = all_branches[idx]
            best_selections = _trigger_selections_for_condition(cond_label, qn_to_q)
            if not best_selections:
                best_selections = {source: "1"}
            uncovered.remove(idx)
        else:
            uncovered -= best_covered

        scenario_id += 1

        # 경로 추적
        path = trace_path(questions, graph, best_selections)
        verified_indices = _covered_branch_indices_from_path(path, all_branches) & best_covered
        verified = [_branch_display(all_branches[i]) for i in sorted(verified_indices)]

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
            branch_diagnostics=[],
        )

    graph = build_skip_logic_graph(questions)
    analysis = analyze_graph(graph, questions)
    paths = enumerate_paths(questions, graph)
    scenarios = generate_test_scenarios(questions, graph)
    branch_diagnostics = analyze_branch_diagnostics(questions, graph, scenarios)

    # 시나리오에 보기 라벨 매핑
    qn_map = {q.question_number: q for q in questions}
    for sc in scenarios:
        labels = {}
        for qn, code in sc.answer_selections.items():
            q = qn_map.get(qn)
            if q and q.answer_options:
                for opt in q.answer_options:
                    if opt.code == code:
                        labels[qn] = opt.label
                        break
                else:
                    labels[qn] = f"코드 {code}"
            else:
                labels[qn] = f"코드 {code}"
        sc.answer_labels = labels

    # 파싱 불가 조건 수집
    unparsed: List[Tuple[str, str]] = []
    for q in questions:
        for sl in q.skip_logic:
            parsed = parse_condition_expression(sl.condition)
            if not parsed.is_parsed:
                unparsed.append((q.question_number, sl.condition))

    return SimulationResult(
        all_paths=paths,
        test_scenarios=scenarios,
        graph_analysis=analysis,
        total_questions=len(questions),
        total_skip_rules=graph.total_skip_rules,
        unparsed_conditions=unparsed,
        branch_diagnostics=branch_diagnostics,
    )


# ---------------------------------------------------------------------------
# 페르소나 기반 테스트 시나리오
# ---------------------------------------------------------------------------

@dataclass
class PersonaScenario:
    """페르소나 기반 테스트 시나리오."""
    persona_id: int
    persona_label: str               # "20대 여성, 삼성폰 사용자"
    answer_selections: Dict[str, str]  # {"S1": "2", "S2": "1", "Q3": "1"}
    answer_labels: Dict[str, str]    # {"S1": "여성", "S2": "20대", "Q3": "삼성"}
    expected_path: List[str]         # ["S1", "S2", "Q1", "Q3", ...]
    path_length: int = 0
    is_termination: bool = False     # 중도 탈락 경로인지


def generate_persona_scenarios(
    questions: List[SurveyQuestion],
    graph=None,
) -> List[PersonaScenario]:
    """demographics/screening 문항의 보기 조합으로 페르소나 시나리오를 생성.

    LLM 없이 알고리즘으로 대표 페르소나를 구성한다:
    1. role이 'screening'/'demographics'이거나 문항번호가 S/D/DM으로 시작하는 문항 식별
    2. 각 문항의 보기 중 대표값 선택 (첫 번째, 마지막, 중간)
    3. 조합하여 페르소나 생성 → trace_path로 경로 추적
    """
    import itertools

    if not questions:
        return []

    if graph is None:
        graph = build_skip_logic_graph(questions)

    # 1. 스크리닝/인구통계 문항 식별
    demo_questions = []
    for q in questions:
        role = getattr(q, 'role', '').lower()
        qn_upper = q.question_number.upper()
        is_demo = (
            role in ('screening', 'demographics')
            or qn_upper.startswith(('S', 'D', 'DM', 'DE', 'SC'))
        )
        if is_demo and q.answer_options and q.question_type in ('SA', None, 'sa'):
            demo_questions.append(q)

    if not demo_questions:
        return []

    # 2. 각 문항에서 대표 보기 선택 (최대 3개: 첫 번째, 중간, 마지막)
    demo_choices = []
    for q in demo_questions[:5]:  # 최대 5개 문항
        opts = q.answer_options
        # 특수 코드(98, 99) 제외
        regular = [o for o in opts if o.code not in ('98', '99', '97', '96')]
        if not regular:
            continue

        picks = []
        picks.append(regular[0])
        if len(regular) >= 3:
            picks.append(regular[len(regular) // 2])
        if len(regular) >= 2:
            picks.append(regular[-1])
        # 중복 제거
        seen = set()
        unique_picks = []
        for p in picks:
            if p.code not in seen:
                seen.add(p.code)
                unique_picks.append(p)
        demo_choices.append((q, unique_picks))

    if not demo_choices:
        return []

    # 3. 조합 생성 (최대 12개 페르소나)
    all_combos = list(itertools.product(*[choices for _, choices in demo_choices]))
    if len(all_combos) > 12:
        # 균등 샘플링
        step = len(all_combos) // 12
        all_combos = all_combos[::step][:12]

    # 4. 각 조합으로 경로 추적
    qn_map = {q.question_number: q for q in questions}
    personas = []

    for idx, combo in enumerate(all_combos, 1):
        selections = {}
        labels = {}
        label_parts = []

        for (q, _), opt in zip(demo_choices, combo):
            selections[q.question_number] = opt.code
            labels[q.question_number] = opt.label
            label_parts.append(opt.label)

        # 경로 추적
        path = trace_path(questions, graph, selections)

        # 중도 탈락 판별 (경로가 전체 문항의 30% 이하면 탈락 경로)
        is_term = path.length < len(questions) * 0.3

        persona_label = ", ".join(label_parts)
        if is_term:
            persona_label += " (탈락 경로)"

        personas.append(PersonaScenario(
            persona_id=idx,
            persona_label=persona_label,
            answer_selections=selections,
            answer_labels=labels,
            expected_path=path.question_numbers,
            path_length=path.length,
            is_termination=is_term,
        ))

    # 경로 길이 다양성으로 정렬 (긴 경로 먼저, 탈락 경로는 뒤로)
    personas.sort(key=lambda p: (p.is_termination, -p.path_length))

    return personas
