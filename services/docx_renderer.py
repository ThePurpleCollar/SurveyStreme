"""파싱된 DOCX 구조를 LLM이 이해할 수 있는 어노테이션 텍스트로 변환하는 모듈.

서식 정보(굵기, 목록 레벨, 들여쓰기, 표 등)를 경량 마크업으로 보존하여
LLM이 설문지 구조를 파악할 수 있게 합니다.
"""

from typing import List
from services.docx_parser import DocxSection, DocxParagraph, DocxTable, ContentItem


def render_paragraph(para: DocxParagraph) -> str:
    """단일 paragraph를 어노테이션 텍스트로 변환"""
    prefix = ""
    text = para.text

    # 목록 항목
    if para.list_level is not None:
        indent = "  " * para.list_level
        if para.is_numbered_list:
            prefix = f"{indent}  #. "
        else:
            prefix = f"{indent}  - "
    elif para.indent_level > 0:
        prefix = "  " * para.indent_level

    # 서식 마커
    if para.is_bold and text:
        text = f"**{text}**"
    if para.is_all_caps and text:
        text = f"[CAPS]{text}[/CAPS]"

    # 스타일 힌트 (Normal이 아닌 경우)
    style_hint = ""
    if para.style_name and para.style_name not in ('Normal', 'Body Text', 'List Paragraph',
                                                      'Body', 'Default Paragraph Font'):
        style_hint = f"  [style:{para.style_name}]"

    return f"{prefix}{text}{style_hint}"


def render_table(table: DocxTable) -> str:
    """DocxTable을 LLM 친화적 텍스트로 변환.

    table_type에 따라 구조화된 마커를 사용하여 LLM이 표의 역할을 정확히 파악할 수 있게 함.
    """
    if not table.rows:
        return ""

    table_type = getattr(table, 'table_type', 'unknown')

    if table_type == "section_header":
        rows = table.rows_text if hasattr(table, 'rows_text') else table.rows
        text = (rows[0][0] if rows and rows[0] else "").strip()
        return f"\n[SECTION: {text}]\n" if text else ""

    if table_type == "coding_reference":
        return _render_coding_ref(
            table.rows_text if hasattr(table, 'rows_text') else table.rows
        )

    rows = table.rows_text if hasattr(table, 'rows_text') else table.rows
    if not rows:
        return ""

    if table_type == "grid":
        return _render_grid(rows)
    elif table_type == "matrix":
        return _render_matrix(rows)
    elif table_type == "code_label":
        return _render_code_label(rows)
    elif table_type == "multi_question":
        return _render_multi_question(rows)
    else:
        return _render_generic(rows)


def _render_grid(rows: List[List[str]]) -> str:
    """grid 표: [SCALE_HEADER] + [ROW] 구조화 렌더링"""
    lines = ["\n[TABLE:grid]"]
    scale_header = " | ".join(c for c in rows[0] if c)
    lines.append(f"[SCALE_HEADER] {scale_header}")
    for row in rows[1:]:
        item = row[0].strip() if row else ""
        if item:
            lines.append(f"[ROW] {item}")
    lines.append("[/TABLE]\n")
    return "\n".join(lines)


def _render_matrix(rows: List[List[str]]) -> str:
    """matrix 표: [COL_HEADER] + [ROW] 구조화 렌더링"""
    lines = ["\n[TABLE:matrix]"]
    if rows:
        col_header = " | ".join(c for c in rows[0] if c)
        lines.append(f"[COL_HEADER] {col_header}")
        for row in rows[1:]:
            item = row[0].strip() if row else ""
            if item:
                lines.append(f"[ROW] {item}")
    lines.append("[/TABLE]\n")
    return "\n".join(lines)


def _render_code_label(rows: List[List[str]]) -> str:
    """code_label 표: [TABLE:options] 마크다운 렌더링"""
    lines = ["\n[TABLE:options]"]
    for row in rows:
        line = "| " + " | ".join(c if c else "" for c in row) + " |"
        lines.append(line)
    lines.append("[/TABLE]\n")
    return "\n".join(lines)


def _render_multi_question(rows: List[List[str]]) -> str:
    """multi_question 표: 각 행이 별도 문항임을 마킹"""
    lines = ["\n[TABLE:multi_question — each row is a separate question]"]
    for i, row in enumerate(rows):
        line = "| " + " | ".join(c if c else "" for c in row) + " |"
        lines.append(line)
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")
    lines.append("[/TABLE]\n")
    return "\n".join(lines)


def _render_coding_ref(rows: List[List[str]]) -> str:
    """coding_reference 표: 내용을 보존하되 역할을 마킹"""
    if not rows:
        return ""
    lines = ["\n[CODING_REF — this is a coding/variable reference, NOT answer options]"]
    for row in rows:
        line = "| " + " | ".join(c if c else "" for c in row) + " |"
        lines.append(line)
    lines.append("[/CODING_REF]\n")
    return "\n".join(lines)


def _render_generic(rows: List[List[str]]) -> str:
    """generic/unknown 표: 기본 마크다운 렌더링"""
    lines = ["\n[TABLE:info]"]
    for i, row in enumerate(rows):
        line = "| " + " | ".join(c if c else "" for c in row) + " |"
        lines.append(line)
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")
    lines.append("[/TABLE]\n")
    return "\n".join(lines)


def render_section(section: DocxSection) -> str:
    """단일 섹션을 어노테이션 텍스트로 변환 (원본 순서 보존)"""
    lines = []

    if section.heading:
        lines.append(f"\n=== {section.heading} ===\n")

    for item in section.content:
        if isinstance(item, DocxParagraph):
            rendered = render_paragraph(item)
            if rendered.strip():
                lines.append(rendered)
        elif isinstance(item, DocxTable):
            rendered = render_table(item)
            if rendered.strip():
                lines.append(rendered)

    return "\n".join(lines)


def render_sections_to_annotated_text(sections: List[DocxSection]) -> str:
    """전체 섹션 리스트를 LLM용 어노테이션 텍스트로 변환.

    Args:
        sections: parse_docx()에서 반환된 DocxSection 리스트

    Returns:
        서식 어노테이션이 포함된 텍스트 문자열
    """
    parts = []
    for section in sections:
        rendered = render_section(section)
        if rendered.strip():
            parts.append(rendered)

    return "\n".join(parts)
