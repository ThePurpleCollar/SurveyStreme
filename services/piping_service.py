"""Piping & Quota Intelligence 서비스.

문항 간 데이터 의존성(파이핑, 필터 체인) 분석 및 이슈 탐지.
대부분 알고리즘(regex) 기반, implicit piping 탐지만 LLM 사용.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from models.survey import SurveyQuestion
from services.llm_client import DEFAULT_MODEL, call_llm_json

# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------


@dataclass
class PipingRef:
    """문항 간 파이핑 참조."""
    source_qn: str        # 참조되는 문항 ("Q1")
    target_qn: str        # 참조하는 문항 ("Q5")
    pipe_type: str        # "text_piping"|"code_piping"|"filter_dependency"|"implicit_piping"
    context: str          # 매칭된 텍스트
    severity: str = "info"


@dataclass
class PipingIssue:
    """파이핑 관련 이슈."""
    issue_type: str       # "circular"|"ordering"|"missing_source"|"long_chain"
    description: str
    involved_questions: List[str] = field(default_factory=list)
    severity: str = "warning"  # "warning"|"error"


@dataclass
class FilterChain:
    """필터 의존성 체인."""
    root_question: str
    dependents: List[str] = field(default_factory=list)
    chain_length: int = 0


@dataclass
class PipingAnalysisResult:
    """파이핑 분석 전체 결과."""
    piping_refs: List[PipingRef] = field(default_factory=list)
    issues: List[PipingIssue] = field(default_factory=list)
    filter_chains: List[FilterChain] = field(default_factory=list)
    bottleneck_questions: List[Tuple[str, int]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Regex 패턴
# ---------------------------------------------------------------------------

# 문항 번호 패턴: Q1, SQ1a, Q2_1, SC2, BVT11 등
_QN_PATTERN = re.compile(
    r'\b([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)\b', re.IGNORECASE
)

# 텍스트 파이핑: [Q1 응답], {Q2_answer}, <<Q3>>, [Q1 에서 선택], [Q1 response] 등
_TEXT_PIPING_PATTERN = re.compile(
    r'\[([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)\s*(?:응답|response|answer|에서|from)[^\]]*\]'
    r'|\{([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)_?(?:answer|응답)?\}'
    r'|<<([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)>>'
    r'|\[PIPE\s+([A-Za-z]+\d+[a-z]?(?:[-_]\d+)*)\]',
    re.IGNORECASE,
)

# 코드 파이핑: pipe, piping, carry forward, 전달 등
_CODE_PIPING_KEYWORDS = re.compile(
    r'pipe|piping|carry\s*forward|전달|이전\s*응답|selected\s*(?:at|in|from)',
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# 그래프 스타일
# ---------------------------------------------------------------------------

_PIPING_EDGE_STYLES: Dict[str, Dict[str, str]] = {
    "text_piping":       {"color": "#2ECC71", "style": "bold"},
    "code_piping":       {"color": "#3498DB", "style": "bold"},
    "filter_dependency": {"color": "#E67E22", "style": "dashed"},
    "implicit_piping":   {"color": "#9B59B6", "style": "dotted"},
}

_PIPE_TYPE_LABELS: Dict[str, str] = {
    "text_piping": "Text Piping",
    "code_piping": "Code Piping",
    "filter_dependency": "Filter Dependency",
    "implicit_piping": "Implicit Piping",
}

# ---------------------------------------------------------------------------
# 텍스트 파이핑 탐지
# ---------------------------------------------------------------------------


def detect_text_piping(questions: List[SurveyQuestion]) -> List[PipingRef]:
    """문항 텍스트 및 보기 라벨에서 텍스트 파이핑 참조를 탐지."""
    refs: List[PipingRef] = []
    qn_set = {q.question_number.upper() for q in questions}

    for q in questions:
        # 문항 텍스트 검색
        texts_to_search = [q.question_text or ""]
        # 보기 라벨도 검색
        for opt in q.answer_options:
            texts_to_search.append(opt.label or "")
        # instructions
        if q.instructions:
            texts_to_search.append(q.instructions)

        for text in texts_to_search:
            for match in _TEXT_PIPING_PATTERN.finditer(text):
                # 매칭 그룹 중 None이 아닌 첫 번째가 문항 번호
                source_qn = next(
                    (g for g in match.groups() if g is not None), None
                )
                if source_qn is None:
                    continue
                source_upper = source_qn.upper()
                # 자기 참조 제외, 존재하는 문항만
                if source_upper == q.question_number.upper():
                    continue
                if source_upper not in qn_set:
                    continue
                refs.append(PipingRef(
                    source_qn=source_upper,
                    target_qn=q.question_number,
                    pipe_type="text_piping",
                    context=match.group(0).strip(),
                ))

    return refs


# ---------------------------------------------------------------------------
# 코드 파이핑 탐지
# ---------------------------------------------------------------------------


def detect_code_piping(questions: List[SurveyQuestion]) -> List[PipingRef]:
    """instructions/special_instructions에서 코드 파이핑 키워드 및 문항 참조를 탐지."""
    refs: List[PipingRef] = []
    qn_set = {q.question_number.upper() for q in questions}

    for q in questions:
        fields_to_check = [
            q.instructions or "",
            q.special_instructions or "",
        ]
        combined = " ".join(fields_to_check)
        if not _CODE_PIPING_KEYWORDS.search(combined):
            continue

        # 해당 텍스트에서 참조 문항 추출
        for text in fields_to_check:
            if not _CODE_PIPING_KEYWORDS.search(text):
                continue
            for match in _QN_PATTERN.finditer(text):
                ref_qn = match.group(1).upper()
                if ref_qn == q.question_number.upper():
                    continue
                if ref_qn not in qn_set:
                    continue
                # 컨텍스트: 매칭 주변 텍스트
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end].strip()
                refs.append(PipingRef(
                    source_qn=ref_qn,
                    target_qn=q.question_number,
                    pipe_type="code_piping",
                    context=context,
                ))

    return refs


# ---------------------------------------------------------------------------
# 필터 의존성 탐지
# ---------------------------------------------------------------------------


def detect_filter_dependencies(questions: List[SurveyQuestion]) -> List[PipingRef]:
    """filter_condition 파싱 → 필터 의존성 추출."""
    refs: List[PipingRef] = []
    qn_set = {q.question_number.upper() for q in questions}

    for q in questions:
        if not q.filter_condition:
            continue

        for match in _QN_PATTERN.finditer(q.filter_condition):
            ref_qn = match.group(1).upper()
            if ref_qn == q.question_number.upper():
                continue
            if ref_qn not in qn_set:
                continue
            refs.append(PipingRef(
                source_qn=ref_qn,
                target_qn=q.question_number,
                pipe_type="filter_dependency",
                context=q.filter_condition.strip(),
            ))

    return refs


# ---------------------------------------------------------------------------
# 암묵적 파이핑 탐지 (LLM)
# ---------------------------------------------------------------------------

_IMPLICIT_SYSTEM_PROMPT_EN = """You are a survey questionnaire analyst. Identify implicit piping references — where a question implicitly refers to responses from earlier questions without explicit piping syntax like [Q1 response] or {Q2_answer}.

Examples of implicit piping:
- "the brand you selected earlier" → refers to a prior brand selection question
- "the product you mentioned" → refers to a prior product question
- "your preferred option from before" → refers to a prior preference question

Return JSON:
{
  "implicit_refs": [
    {"source_qn": "Q1", "target_qn": "Q5", "context": "matched text snippet"}
  ]
}

If no implicit piping found, return {"implicit_refs": []}."""

_IMPLICIT_SYSTEM_PROMPT_KO = """설문지 분석가입니다. 명시적 파이핑 구문([Q1 응답], {Q2_answer}) 없이 이전 문항 응답을 암묵적으로 참조하는 경우를 식별합니다.

암묵적 파이핑 예시:
- "앞서 선택한 브랜드" → 이전 브랜드 선택 문항 참조
- "위에서 응답한 제품" → 이전 제품 문항 참조

JSON 반환:
{
  "implicit_refs": [
    {"source_qn": "Q1", "target_qn": "Q5", "context": "매칭된 텍스트"}
  ]
}

암묵적 파이핑이 없으면 {"implicit_refs": []} 반환."""


def detect_implicit_piping(
    questions: List[SurveyQuestion],
    model: str = DEFAULT_MODEL,
    progress_callback: Optional[Callable] = None,
) -> List[PipingRef]:
    """LLM을 사용하여 암묵적 파이핑 참조를 탐지."""
    if not questions:
        return []

    # 배치 크기: 20문항씩
    batch_size = 20
    all_refs: List[PipingRef] = []
    qn_set = {q.question_number.upper() for q in questions}

    # 한국어 감지
    sample_text = " ".join(q.question_text[:100] for q in questions[:5])
    is_korean = any('\uac00' <= c <= '\ud7a3' for c in sample_text)
    system_prompt = _IMPLICIT_SYSTEM_PROMPT_KO if is_korean else _IMPLICIT_SYSTEM_PROMPT_EN

    total_batches = (len(questions) + batch_size - 1) // batch_size

    for batch_idx in range(0, len(questions), batch_size):
        batch = questions[batch_idx:batch_idx + batch_size]
        batch_num = batch_idx // batch_size

        if progress_callback:
            progress_callback("batch_start", {
                "batch_index": batch_num,
                "total_batches": total_batches,
                "question_count": len(batch),
            })

        # 문항 텍스트 정리
        q_texts = []
        for q in batch:
            text = f"{q.question_number}: {q.question_text}"
            if q.answer_options:
                opts = ", ".join(o.label for o in q.answer_options[:10])
                text += f" [Options: {opts}]"
            q_texts.append(text)

        user_prompt = "Analyze these questions for implicit piping:\n\n" + "\n".join(q_texts)

        try:
            result = call_llm_json(system_prompt, user_prompt, model=model)
            implicit_refs = result.get("implicit_refs", [])
            for ref in implicit_refs:
                source = ref.get("source_qn", "").upper()
                target = ref.get("target_qn", "").upper()
                if source in qn_set and target in qn_set and source != target:
                    all_refs.append(PipingRef(
                        source_qn=source,
                        target_qn=target,
                        pipe_type="implicit_piping",
                        context=ref.get("context", ""),
                        severity="info",
                    ))
        except Exception:
            pass  # LLM 실패 시 무시 — 알고리즘 결과만 사용

        if progress_callback:
            progress_callback("batch_done", {
                "batch_index": batch_num,
                "total_batches": total_batches,
            })

    return all_refs


# ---------------------------------------------------------------------------
# 필터 체인 빌드
# ---------------------------------------------------------------------------


def build_filter_chains(
    questions: List[SurveyQuestion],
    filter_refs: List[PipingRef],
) -> Tuple[List[FilterChain], List[Tuple[str, int]]]:
    """필터 참조에서 체인 구조를 빌드하고 병목 문항을 식별."""
    # 소스 → 의존 문항 매핑
    dependency_map: Dict[str, List[str]] = defaultdict(list)
    for ref in filter_refs:
        if ref.pipe_type == "filter_dependency":
            dependency_map[ref.source_qn].append(ref.target_qn)

    if not dependency_map:
        return [], []

    # 루트 문항 식별 (다른 문항에 의존하지 않는 소스)
    all_dependents = set()
    for deps in dependency_map.values():
        all_dependents.update(deps)

    roots = [qn for qn in dependency_map if qn not in all_dependents]
    if not roots:
        # 순환 가능성 — 모든 소스를 루트로 처리
        roots = list(dependency_map.keys())

    # BFS로 체인 구성
    chains: List[FilterChain] = []
    for root in roots:
        visited = set()
        queue = [root]
        dependents: List[str] = []
        max_depth = 0
        depth_map = {root: 0}

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            for dep in dependency_map.get(current, []):
                if dep not in visited:
                    dependents.append(dep)
                    depth_map[dep] = depth_map.get(current, 0) + 1
                    max_depth = max(max_depth, depth_map[dep])
                    queue.append(dep)

        if dependents:
            chains.append(FilterChain(
                root_question=root,
                dependents=dependents,
                chain_length=max_depth,
            ))

    # 병목 문항: 의존 문항 수 기준 내림차순
    bottlenecks = sorted(
        [(qn, len(deps)) for qn, deps in dependency_map.items()],
        key=lambda x: x[1],
        reverse=True,
    )

    return chains, bottlenecks


# ---------------------------------------------------------------------------
# 유효성 검증
# ---------------------------------------------------------------------------


def validate_piping(
    questions: List[SurveyQuestion],
    all_refs: List[PipingRef],
) -> List[PipingIssue]:
    """파이핑 참조의 유효성을 검증하여 이슈를 반환."""
    issues: List[PipingIssue] = []
    qn_set = {q.question_number.upper() for q in questions}
    qn_order = {q.question_number.upper(): i for i, q in enumerate(questions)}

    # 1. 누락된 소스 문항
    for ref in all_refs:
        if ref.source_qn.upper() not in qn_set:
            issues.append(PipingIssue(
                issue_type="missing_source",
                description=f"Piping source {ref.source_qn} referenced by {ref.target_qn} does not exist.",
                involved_questions=[ref.source_qn, ref.target_qn],
                severity="error",
            ))

    # 2. 순서 오류 (소스가 타겟 뒤에 위치)
    for ref in all_refs:
        src_idx = qn_order.get(ref.source_qn.upper())
        tgt_idx = qn_order.get(ref.target_qn.upper())
        if src_idx is not None and tgt_idx is not None and src_idx > tgt_idx:
            issues.append(PipingIssue(
                issue_type="ordering",
                description=f"{ref.target_qn} references {ref.source_qn}, but source appears after target.",
                involved_questions=[ref.source_qn, ref.target_qn],
                severity="warning",
            ))

    # 3. 순환 참조 탐지
    adj: Dict[str, set] = defaultdict(set)
    for ref in all_refs:
        adj[ref.source_qn.upper()].add(ref.target_qn.upper())

    # DFS 사이클 탐지
    visited: set = set()
    in_stack: set = set()
    cycles: List[List[str]] = []

    def _dfs(node: str, path: List[str]):
        if node in in_stack:
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        in_stack.add(node)
        path.append(node)
        for neighbor in adj.get(node, set()):
            _dfs(neighbor, path)
        path.pop()
        in_stack.discard(node)

    for start in adj:
        if start not in visited:
            _dfs(start, [])

    for cycle in cycles:
        issues.append(PipingIssue(
            issue_type="circular",
            description=f"Circular piping reference detected: {' -> '.join(cycle)}",
            involved_questions=list(set(cycle)),
            severity="error",
        ))

    # 4. 긴 체인 (4단계 이상)
    # BFS로 각 노드에서의 최대 깊이 계산
    for start in adj:
        depth = 0
        queue = [(start, 0)]
        chain_visited: set = set()
        while queue:
            current, d = queue.pop(0)
            if current in chain_visited:
                continue
            chain_visited.add(current)
            depth = max(depth, d)
            for neighbor in adj.get(current, set()):
                if neighbor not in chain_visited:
                    queue.append((neighbor, d + 1))
        if depth >= 4:
            issues.append(PipingIssue(
                issue_type="long_chain",
                description=f"Long piping chain starting from {start} (depth: {depth}).",
                involved_questions=[start],
                severity="warning",
            ))

    # 중복 이슈 제거
    seen: set = set()
    unique_issues: List[PipingIssue] = []
    for issue in issues:
        key = (issue.issue_type, tuple(sorted(issue.involved_questions)))
        if key not in seen:
            seen.add(key)
            unique_issues.append(issue)

    return unique_issues


# ---------------------------------------------------------------------------
# Graphviz DOT 생성
# ---------------------------------------------------------------------------


def generate_piping_dot(
    all_refs: List[PipingRef],
    questions: List[SurveyQuestion],
    show_types: Optional[List[str]] = None,
) -> str:
    """파이핑 참조에서 Graphviz DOT 문자열을 생성."""
    if show_types is None:
        show_types = list(_PIPING_EDGE_STYLES.keys())

    filtered_refs = [r for r in all_refs if r.pipe_type in show_types]

    # 관련 노드 수집
    relevant_nodes: set = set()
    for ref in filtered_refs:
        relevant_nodes.add(ref.source_qn)
        relevant_nodes.add(ref.target_qn)

    # 문항 유형 룩업
    qtype_map = {q.question_number.upper(): q.question_type or "Unknown" for q in questions}

    _NODE_COLORS: Dict[str, str] = {
        "SA": "#B3D9FF",
        "MA": "#B3FFB3",
        "OE": "#FFFFB3",
        "NUMERIC": "#FFD9B3",
        "Scale": "#D9B3FF",
        "Unknown": "#E8E8E8",
    }

    lines: List[str] = []
    lines.append('digraph Piping {')
    lines.append('  rankdir=LR;')
    lines.append('  node [shape=box, style="filled,rounded", fontsize=10, fontname="Arial"];')
    lines.append('  edge [fontsize=8, fontname="Arial"];')
    lines.append('')

    # 노드
    for node in sorted(relevant_nodes):
        qtype = qtype_map.get(node.upper(), "Unknown")
        color = _NODE_COLORS.get(qtype, _NODE_COLORS["Unknown"])
        label = f"{node}\\n{qtype}"
        lines.append(f'  "{node}" [label="{label}", fillcolor="{color}"];')

    lines.append('')

    # 엣지
    for ref in filtered_refs:
        style = _PIPING_EDGE_STYLES.get(ref.pipe_type, {"color": "#999", "style": "solid"})
        context = ref.context.replace('"', '\\"')[:40]
        attrs = [
            f'color="{style["color"]}"',
            f'style="{style["style"]}"',
            'penwidth=2.0',
        ]
        if context:
            attrs.append(f'label="{context}"')
        lines.append(f'  "{ref.source_qn}" -> "{ref.target_qn}" [{", ".join(attrs)}];')

    lines.append('}')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def analyze_piping(
    questions: List[SurveyQuestion],
    model: str = DEFAULT_MODEL,
    include_implicit: bool = True,
    progress_callback: Optional[Callable] = None,
) -> PipingAnalysisResult:
    """파이핑 분석 메인 함수 — 모든 탐지 + 검증을 순차 실행."""
    if progress_callback:
        progress_callback("phase", {"name": "text_piping", "status": "start"})

    text_refs = detect_text_piping(questions)
    code_refs = detect_code_piping(questions)
    filter_refs = detect_filter_dependencies(questions)

    if progress_callback:
        progress_callback("phase", {"name": "text_piping", "status": "done",
                                     "count": len(text_refs) + len(code_refs) + len(filter_refs)})

    # 암묵적 파이핑 (선택)
    implicit_refs: List[PipingRef] = []
    if include_implicit:
        if progress_callback:
            progress_callback("phase", {"name": "implicit_piping", "status": "start"})
        implicit_refs = detect_implicit_piping(questions, model=model,
                                                progress_callback=progress_callback)
        if progress_callback:
            progress_callback("phase", {"name": "implicit_piping", "status": "done",
                                         "count": len(implicit_refs)})

    all_refs = text_refs + code_refs + filter_refs + implicit_refs

    # 중복 참조 제거 (동일 source-target-type)
    seen: set = set()
    unique_refs: List[PipingRef] = []
    for ref in all_refs:
        key = (ref.source_qn, ref.target_qn, ref.pipe_type)
        if key not in seen:
            seen.add(key)
            unique_refs.append(ref)

    # 필터 체인 빌드
    chains, bottlenecks = build_filter_chains(questions, unique_refs)

    # 유효성 검증
    issues = validate_piping(questions, unique_refs)

    return PipingAnalysisResult(
        piping_refs=unique_refs,
        issues=issues,
        filter_chains=chains,
        bottleneck_questions=bottlenecks,
    )
