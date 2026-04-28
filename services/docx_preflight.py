"""DOCX format readiness checks before LLM extraction.

The preflight report reuses the parsed DOCX structure. It adds no LLM calls and
helps users fix formatting issues before spending time on extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from services.docx_parser import DocxParagraph, DocxSection, DocxTable
from services.docx_renderer import render_sections_to_annotated_text
from services.llm_extractor import regex_pre_extract


_TYPE_HINT_RE = re.compile(
    r'[\[(]\s*(SA|S|MA|M|OE|OPEN|OPEN[-\s]?END|NUMERIC|'
    r'\d+\s*PT(?:\s*SCALE)?|SCALE|GRID|MATRIX|RANK|TOP\s*\d+)\s*[\])]',
    re.IGNORECASE,
)
_SKIP_RE = re.compile(
    r'(go\s*to|skip\s*to|terminate|screen\s*out|종료|탈락|이동|건너뜀)',
    re.IGNORECASE,
)
_FILTER_RE = re.compile(
    r'(ask\s*if|only\s*if|show\s+only\s+if|\[pn:|응답자만|모두에게)',
    re.IGNORECASE,
)


@dataclass
class PreflightIssue:
    severity: str
    category: str
    message: str
    evidence: str = ""


@dataclass
class PreflightReport:
    score: int
    sections: int
    paragraphs: int
    tables: int
    question_candidates: int
    typed_question_candidates: int
    numbered_list_paragraphs: int
    option_tables: int
    grid_tables: int
    generic_tables: int
    unknown_tables: int
    merged_tables: int
    textbox_paragraphs: int
    skip_filter_patterns: int
    issues: List[PreflightIssue] = field(default_factory=list)

    @property
    def readiness_label(self) -> str:
        if self.score >= 85:
            return "Good"
        if self.score >= 70:
            return "Usable with review"
        if self.score >= 50:
            return "Risky"
        return "High risk"


def _collect_content(sections: List[DocxSection]) -> tuple[list[DocxParagraph], list[DocxTable]]:
    paragraphs = []
    tables = []
    for section in sections:
        for item in section.content:
            if isinstance(item, DocxParagraph):
                paragraphs.append(item)
            elif isinstance(item, DocxTable):
                tables.append(item)
    return paragraphs, tables


def _score_from_issues(base: int, issues: List[PreflightIssue]) -> int:
    penalty = 0
    for issue in issues:
        if issue.severity == "high":
            penalty += 12
        elif issue.severity == "medium":
            penalty += 7
        else:
            penalty += 3
    return max(0, min(100, base - penalty))


def check_docx_preflight(sections: List[DocxSection]) -> PreflightReport:
    """Return a deterministic readiness report from parsed DOCX sections."""
    paragraphs, tables = _collect_content(sections)
    annotated = render_sections_to_annotated_text(sections)
    candidates = regex_pre_extract(annotated)

    typed_candidates = 0
    for item in candidates:
        if item.get("question_type") or _TYPE_HINT_RE.search(item.get("question_text", "")):
            typed_candidates += 1

    table_types = [getattr(t, "table_type", "unknown") for t in tables]
    option_tables = table_types.count("code_label")
    grid_tables = table_types.count("grid") + table_types.count("matrix")
    generic_tables = table_types.count("generic")
    unknown_tables = table_types.count("unknown")
    merged_tables = sum(1 for t in tables if getattr(t, "has_merged_cells", False))
    textbox_paragraphs = sum(1 for p in paragraphs if "[TEXTBOX:" in p.text)
    numbered_list_paragraphs = sum(1 for p in paragraphs if p.is_numbered_list)
    skip_filter_patterns = len(_SKIP_RE.findall(annotated)) + len(_FILTER_RE.findall(annotated))

    issues: List[PreflightIssue] = []

    if not candidates:
        issues.append(PreflightIssue(
            "high", "question_number",
            "문항번호 후보가 거의 감지되지 않습니다. Q1., SQ1. 같은 명시적 문항번호를 권장합니다.",
        ))
    elif len(candidates) < 5 and len(paragraphs) > 50:
        issues.append(PreflightIssue(
            "medium", "question_number",
            "문서 분량 대비 문항번호 후보가 적습니다. 자동 번호만 있고 실제 텍스트 번호가 없을 수 있습니다.",
        ))

    if candidates and typed_candidates / len(candidates) < 0.5:
        issues.append(PreflightIssue(
            "medium", "question_type",
            f"문항유형 힌트가 적습니다 ({typed_candidates}/{len(candidates)}). "
            "문항 라인에 (SA), (MA), (OE), (5PT SCALE)을 붙이면 안정적입니다.",
        ))

    if tables and (generic_tables + unknown_tables) / len(tables) >= 0.35:
        issues.append(PreflightIssue(
            "medium", "table_classification",
            f"역할이 불명확한 표가 많습니다 (generic {generic_tables}, unknown {unknown_tables}).",
        ))

    if merged_tables >= 5:
        issues.append(PreflightIssue(
            "low", "merged_cells",
            f"병합 셀이 있는 표가 {merged_tables}개입니다. 병합 셀은 보기/그리드 파싱 리스크를 높입니다.",
        ))

    if textbox_paragraphs:
        issues.append(PreflightIssue(
            "low", "textbox",
            f"텍스트박스 내용이 {textbox_paragraphs}개 감지되었습니다. 문항번호는 일반 본문에도 남기는 것이 좋습니다.",
        ))

    if skip_filter_patterns and len(candidates) > 0:
        issues.append(PreflightIssue(
            "low", "logic",
            f"Skip/Filter 패턴 {skip_filter_patterns}개가 감지되었습니다. 추출 후 로직 커버리지를 확인하세요.",
        ))

    if numbered_list_paragraphs and not candidates:
        issues.append(PreflightIssue(
            "medium", "auto_numbering",
            "Word 자동 번호 목록은 있으나 명시적 문항번호가 적습니다. Q1. 같은 텍스트 번호를 병기하세요.",
        ))

    base = 95
    if candidates and option_tables == 0 and len(tables) >= 5:
        issues.append(PreflightIssue(
            "low", "options",
            "보기표(code/label)로 분류된 표가 없습니다. 보기 코드와 라벨 구조를 확인하세요.",
        ))
    score = _score_from_issues(base, issues)

    return PreflightReport(
        score=score,
        sections=len(sections),
        paragraphs=len(paragraphs),
        tables=len(tables),
        question_candidates=len(candidates),
        typed_question_candidates=typed_candidates,
        numbered_list_paragraphs=numbered_list_paragraphs,
        option_tables=option_tables,
        grid_tables=grid_tables,
        generic_tables=generic_tables,
        unknown_tables=unknown_tables,
        merged_tables=merged_tables,
        textbox_paragraphs=textbox_paragraphs,
        skip_filter_patterns=skip_filter_patterns,
        issues=issues,
    )
