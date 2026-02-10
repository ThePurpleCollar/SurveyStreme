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
    """DocxTable을 마크다운 형식 테이블로 변환"""
    if not table.rows:
        return ""

    lines = [""]  # 빈 줄로 시작

    for i, row in enumerate(table.rows):
        line = "| " + " | ".join(cell if cell else "" for cell in row) + " |"
        lines.append(line)
        if i == 0:
            # 헤더 구분선
            separator = "| " + " | ".join("---" for _ in row) + " |"
            lines.append(separator)

    lines.append("")  # 빈 줄로 끝
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
