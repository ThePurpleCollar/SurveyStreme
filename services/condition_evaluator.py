"""Executable survey condition parser/evaluator.

This module is additive. Existing path simulation still uses its legacy
``parse_condition`` wrapper until the simulator is explicitly rewired.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal


LogicalOperator = Literal["and", "or"]
ComparisonOperator = Literal["in", "not_in"]


@dataclass(frozen=True)
class ConditionClause:
    question_number: str
    operator: ComparisonOperator
    values: tuple[str, ...]
    raw_text: str

    @property
    def references(self) -> set[str]:
        return {self.question_number}

    def evaluate(self, answers: dict[str, object]) -> bool:
        selected = _answer_values(answers.get(self.question_number))
        if not selected:
            return False

        expected = set(self.values)
        intersects = bool(selected & expected)
        if self.operator == "in":
            return intersects
        return not intersects


@dataclass(frozen=True)
class ConditionGroup:
    operator: LogicalOperator
    children: tuple["ConditionNode", ...]

    @property
    def references(self) -> set[str]:
        refs: set[str] = set()
        for child in self.children:
            refs.update(child.references)
        return refs

    def evaluate(self, answers: dict[str, object]) -> bool:
        if self.operator == "and":
            return all(child.evaluate(answers) for child in self.children)
        return any(child.evaluate(answers) for child in self.children)


ConditionNode = ConditionClause | ConditionGroup


@dataclass(frozen=True)
class ConditionParseResult:
    raw_text: str
    node: ConditionNode | None
    is_parsed: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def references(self) -> set[str]:
        return self.node.references if self.node else set()

    def evaluate(self, answers: dict[str, object]) -> bool:
        if not self.node:
            return False
        return self.node.evaluate(answers)


_CLAUSE_RE = re.compile(
    r"(?P<question>[A-Za-z]+\d+[A-Za-z]?(?:[-_]\d+)*)"
    r"\s*(?P<operator>!=|<>|≠|=)\s*"
    r"(?P<values>[^=&|()]+)",
    re.IGNORECASE,
)

def parse_condition_expression(condition_text: str | None) -> ConditionParseResult:
    """Parse a condition string into an executable clause tree.

    Supported examples:
    - ``Q1=1``
    - ``Q1=1,2``
    - ``Q1!=99``
    - ``Q1=1&Q2=3``
    - ``Q1=1 OR Q1=2``
    - ``Q2=1~3``
    """
    raw = str(condition_text or "").strip()
    if not raw:
        return ConditionParseResult(raw_text=raw, node=None, is_parsed=False, warnings=("empty_condition",))

    normalized = _normalize_condition_text(raw)
    if re.search(r"\b(?:AND|OR)$", normalized, flags=re.IGNORECASE):
        return ConditionParseResult(
            raw_text=raw,
            node=None,
            is_parsed=False,
            warnings=("trailing_logical_operator",),
        )
    try:
        node = _parse_or_expression(normalized)
    except ValueError as exc:
        return ConditionParseResult(raw_text=raw, node=None, is_parsed=False, warnings=(str(exc),))

    return ConditionParseResult(raw_text=raw, node=node, is_parsed=True)


def evaluate_condition(condition_text: str | None, answers: dict[str, object]) -> bool:
    """Return whether ``answers`` satisfy ``condition_text``."""
    return parse_condition_expression(condition_text).evaluate(answers)


def _parse_or_expression(text: str) -> ConditionNode:
    parts = _fold_bare_or_values(_split_top_level(text, " OR "))
    if len(parts) > 1:
        return ConditionGroup("or", tuple(_parse_and_expression(part) for part in parts))
    return _parse_and_expression(parts[0])


def _parse_and_expression(text: str) -> ConditionNode:
    parts = _split_top_level(text, " AND ")
    if len(parts) > 1:
        return ConditionGroup("and", tuple(_parse_factor(part) for part in parts))
    return _parse_factor(text)


def _parse_factor(text: str) -> ConditionNode:
    value = text.strip()
    if not value:
        raise ValueError("empty_factor")

    if value.startswith("(") and value.endswith(")") and _balanced_parentheses(value[1:-1]):
        return _parse_or_expression(value[1:-1])

    match = _CLAUSE_RE.fullmatch(value)
    if not match:
        raise ValueError(f"unsupported_condition: {value}")

    raw_values = match.group("values").strip()
    values = _parse_values(raw_values)
    if not values:
        raise ValueError(f"missing_condition_values: {value}")

    operator = "not_in" if match.group("operator") in {"!=", "<>", "≠"} else "in"
    return ConditionClause(
        question_number=match.group("question").upper(),
        operator=operator,
        values=tuple(values),
        raw_text=value,
    )


def _fold_bare_or_values(parts: list[str]) -> list[str]:
    """Fold ``Q1=1 OR 2`` shorthand into ``Q1=1,2``.

    The fold is intentionally conservative. Bare values are attached only when
    the immediately preceding part is a single clause, not a compound group.
    """
    folded: list[str] = []
    for part in parts:
        value = part.strip()
        if not value:
            folded.append(value)
            continue

        if folded and _is_bare_value_expression(value):
            previous = folded[-1]
            try:
                previous_clause = _parse_factor(previous)
            except ValueError:
                folded.append(value)
                continue
            if isinstance(previous_clause, ConditionClause):
                folded[-1] = _append_clause_values(previous, value)
                continue

        folded.append(value)
    return folded


def _append_clause_values(clause_text: str, extra_values: str) -> str:
    match = _CLAUSE_RE.fullmatch(clause_text.strip())
    if not match:
        return clause_text
    prefix = clause_text[:match.start("values")]
    values = f"{match.group('values').strip()},{extra_values.strip()}"
    return f"{prefix}{values}"


def _is_bare_value_expression(text: str) -> bool:
    cleaned = _strip_respondent_suffix(text)
    if not cleaned:
        return False
    if re.search(r"[=<>≠]|(?:^|\s)(?:AND|OR)(?:\s|$)|&|\|", cleaned, flags=re.IGNORECASE):
        return False
    if re.search(r"[A-Za-z]+\d+[A-Za-z]?(?:[-_]\d+)*\s*(?:=|!=|<>|≠)", cleaned, flags=re.IGNORECASE):
        return False
    return bool(re.fullmatch(r"[-A-Za-z0-9_'\",./~\s]+", cleaned))


def _normalize_condition_text(text: str) -> str:
    normalized = str(text).strip()
    normalized = normalized.replace("≠", "!=").replace("<>", "!=")
    normalized = re.sub(r"\bAND\b|및", " AND ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bOR\b|또는", " OR ", normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("&", " AND ").replace("|", " OR ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _split_top_level(text: str, delimiter: str) -> list[str]:
    parts = []
    depth = 0
    start = 0
    i = 0
    while i < len(text):
        char = text[i]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced_parentheses")
        if depth == 0 and text.startswith(delimiter, i):
            parts.append(text[start:i].strip())
            i += len(delimiter)
            start = i
            continue
        i += 1

    if depth != 0:
        raise ValueError("unbalanced_parentheses")
    parts.append(text[start:].strip())
    return parts


def _balanced_parentheses(text: str) -> bool:
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _parse_values(raw_values: str) -> list[str]:
    cleaned = _strip_respondent_suffix(raw_values)
    cleaned = re.sub(r"\s+", "", cleaned)
    if not cleaned:
        return []

    values: list[str] = []
    for part in re.split(r",|/", cleaned):
        if not part:
            continue
        if "~" in part:
            values.extend(_expand_range(part, "~"))
        else:
            values.append(part.strip("'\""))

    return _dedupe(values)


def _strip_respondent_suffix(text: str) -> str:
    return re.sub(r"\brespondents?\b|응답자(?:만|에게)?", "", str(text), flags=re.IGNORECASE).strip()


def _expand_range(value: str, separator: str) -> list[str]:
    left, right = value.split(separator, 1)
    try:
        start = int(left)
        end = int(right)
    except ValueError:
        return [value]

    step = 1 if end >= start else -1
    return [str(item) for item in range(start, end + step, step)]


def _answer_values(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, list | tuple | set):
        return {str(item).strip() for item in value if str(item).strip()}
    return {str(value).strip()}


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
