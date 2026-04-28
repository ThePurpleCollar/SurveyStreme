"""SPSS condition parsing and formatting helpers.

Used by both Table Guide exports and Analyzer downloads so that banner
conditions, source variables, code labels, and warnings stay consistent.
"""

import re


_NEGATIVE_CONDITION_RE = re.compile(r"(!=|<>|≠|\bNOT\b)", re.IGNORECASE)


def parse_condition_parts(condition: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """Parse ``Q1=1,2&Q2=3`` style conditions into question/code parts.

    Returns:
        ``(parts, warnings)`` where parts is a list of ``(question, codes)``.
    """
    condition = str(condition or "").strip()
    if not condition:
        return [], ["Missing banner condition"]

    warnings = []
    if _NEGATIVE_CONDITION_RE.search(condition):
        warnings.append("Negative condition is not SPSS-ready; convert to positive code list")

    parsed = []
    for raw_part in condition.split("&"):
        part = raw_part.strip().strip("()")
        if not part:
            continue
        if "=" not in part:
            warnings.append(f"Invalid condition part: {part}")
            continue
        qn, raw_codes = part.split("=", 1)
        qn = qn.strip()
        # Code delimiters: comma or "OR" (e.g. "Q1=1,2" or "Q1=1 OR 2").
        codes = [
            code.strip().strip("'\"")
            for code in re.split(r",|\bOR\b", raw_codes, flags=re.IGNORECASE)
            if code.strip().strip("'\"")
        ]
        if not qn or not codes:
            warnings.append(f"Invalid condition part: {part}")
            continue
        parsed.append((qn, codes))

    if not parsed:
        warnings.append("No executable condition parts found")

    return parsed, warnings


def format_spss_value(code: str) -> str:
    code = str(code).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", code):
        return code
    escaped = code.replace("'", "''")
    return f"'{escaped}'"


def condition_to_spss(condition: str, source_var_map: dict[str, str] | None = None) -> str:
    parts, _ = parse_condition_parts(condition)
    clauses = []
    for qn, codes in parts:
        var_name = (source_var_map or {}).get(qn, qn)
        if len(codes) == 1:
            clauses.append(f"{var_name} = {format_spss_value(codes[0])}")
        else:
            ors = " OR ".join(f"{var_name} = {format_spss_value(code)}" for code in codes)
            clauses.append(f"({ors})")
    return " AND ".join(clauses)


def condition_source_variables(condition: str, source_var_map: dict[str, str]) -> str:
    parts, _ = parse_condition_parts(condition)
    variables = []
    seen = set()
    for qn, _ in parts:
        var_name = source_var_map.get(qn, qn)
        if var_name not in seen:
            variables.append(var_name)
            seen.add(var_name)
    return "&".join(variables)


def condition_code_labels(condition: str, code_label_map: dict[str, dict[str, str]]) -> str:
    parts, _ = parse_condition_parts(condition)
    labels = []
    for qn, codes in parts:
        q_labels = code_label_map.get(qn, {})
        for code in codes:
            label = q_labels.get(code, "")
            labels.append(f"{qn} {code}={label}" if label else f"{qn} {code}")
    return " | ".join(labels)
