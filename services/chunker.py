"""문서를 LLM 컨텍스트 윈도우에 맞게 청킹하는 모듈.

설문지의 섹션/문항 경계에서만 분할하여 문항 중간 잘림을 방지합니다.
"""

import re
from typing import List
from services.docx_parser import DocxSection, DocxParagraph, DocxTable
from services.docx_renderer import render_sections_to_annotated_text, render_section
from services.llm_extractor import _is_valid_question_number

# 최대 청크 크기 (문자 수). ~200K자 ≈ ~50K 토큰.
# Gemini 2.5는 1M 토큰 컨텍스트. 시스템 프롬프트(~2K) + 출력(~65K) 고려하여
# 대부분의 설문지(50~100문항)를 1회 호출로 처리 가능.
MAX_CHUNK_CHARS = 200000


def _estimate_section_size(section: DocxSection) -> int:
    """섹션의 대략적인 문자 수를 추정"""
    size = len(section.heading or "")
    for item in section.content:
        if isinstance(item, DocxParagraph):
            size += len(item.text) + 10  # 서식 어노테이션 오버헤드
        elif isinstance(item, DocxTable):
            for row in item.rows:
                size += sum(len(cell) for cell in row) + len(row) * 3  # 구분자
    return size


# 문항 시작 패턴 (bold paragraph 또는 대괄호 헤더 등)
_QUESTION_START_RE = re.compile(
    r'^(?:\*\*)?'
    r'(?:'
    r'[A-Za-z]+[a-z]*\d+[a-z]?(?:-\d+)*'  # Q1, SQ1a, A1-1
    r'|[A-Za-z]+\d+[A-Za-z]'               # Q1A
    r')'
    r'[\s.\):\[]'                           # 마침표, 괄호, 콜론, 공백+대괄호
)

_BRACKET_HEADER_RE = re.compile(r'^\[([A-Za-z]+\d+)')


def _is_question_start(item) -> bool:
    """content 아이템이 문항 시작점인지 판별"""
    if not isinstance(item, DocxParagraph):
        return False
    # Bold이고 목록이 아닌 paragraph
    if item.is_bold and item.list_level is None and item.indent_level == 0:
        return True
    text = item.text.strip()
    # 문항번호 패턴 + 유효성 검증 (RegionCode, SegCode 등 변수명 제외)
    m = _QUESTION_START_RE.match(text)
    if m:
        qn = re.match(r'(?:\*\*)?([A-Za-z]+[a-z]*\d+[a-z]?(?:-\d+)*|[A-Za-z]+\d+[A-Za-z])', text)
        if qn and _is_valid_question_number(qn.group(1)):
            return True
    # 대괄호 헤더형 [SC2. ...]
    m_bracket = _BRACKET_HEADER_RE.match(text)
    if m_bracket and _is_valid_question_number(m_bracket.group(1)):
        return True
    return False


def _estimate_item_size(item) -> int:
    """개별 content 아이템의 대략적인 문자 수"""
    if isinstance(item, DocxParagraph):
        return len(item.text) + 10
    elif isinstance(item, DocxTable):
        size = 0
        for row in item.rows:
            size += sum(len(cell) for cell in row) + len(row) * 3
        return size
    return 0


def _split_section_at_content(section: DocxSection, max_chars: int) -> List[str]:
    """큰 섹션을 content 아이템 단위로 분할 (표 순서 보존).

    문항 시작점(bold paragraph, 대괄호 헤더 등)에서 분할하며,
    테이블은 직전 문항에 포함되도록 유지합니다.
    """
    chunks = []
    current_items = []
    current_size = 0
    heading_text = section.heading

    for item in section.content:
        item_size = _estimate_item_size(item)

        # 문항 시작점이면서 이미 누적된 내용이 크면 분할
        if (_is_question_start(item) and
                current_size + item_size > max_chars and current_items):
            temp_section = DocxSection(heading=heading_text, content=current_items)
            chunks.append(render_section(temp_section))
            current_items = []
            current_size = 0
            heading_text = f"{section.heading} (continued)" if section.heading else "(continued)"

        current_items.append(item)
        current_size += item_size

    # 남은 아이템
    if current_items:
        temp_section = DocxSection(heading=heading_text, content=current_items)
        chunks.append(render_section(temp_section))

    return chunks


def chunk_sections(sections: List[DocxSection], max_chars: int = MAX_CHUNK_CHARS) -> List[str]:
    """섹션 리스트를 LLM 컨텍스트에 맞는 청크로 분할.

    각 청크는 완전한 섹션을 포함합니다. 단일 섹션이 너무 크면
    paragraph 단위로 추가 분할합니다.

    Args:
        sections: parse_docx()에서 반환된 DocxSection 리스트
        max_chars: 최대 청크 크기 (문자 수)

    Returns:
        어노테이션 텍스트 청크 리스트
    """
    if not sections:
        return []

    chunks = []
    current_sections = []
    current_size = 0

    for section in sections:
        section_size = _estimate_section_size(section)

        if section_size > max_chars:
            # 현재 누적된 섹션 플러시
            if current_sections:
                chunks.append(render_sections_to_annotated_text(current_sections))
                current_sections = []
                current_size = 0

            # 큰 섹션을 content 아이템 단위로 분할
            sub_chunks = _split_section_at_content(section, max_chars)
            chunks.extend(sub_chunks)

        elif current_size + section_size > max_chars:
            # 현재 청크 플러시 후 새 청크 시작
            chunks.append(render_sections_to_annotated_text(current_sections))
            current_sections = [section]
            current_size = section_size

        else:
            current_sections.append(section)
            current_size += section_size

    # 마지막 청크
    if current_sections:
        chunks.append(render_sections_to_annotated_text(current_sections))

    return chunks
