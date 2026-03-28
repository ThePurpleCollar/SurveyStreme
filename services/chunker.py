"""문서를 LLM 컨텍스트 윈도우에 맞게 청킹하는 모듈.

청킹의 목적은 '정확한 문항 식별'이 아니라 '적절한 크기로 텍스트를 나누는 것'.
실제 문항 식별은 전적으로 LLM에 위임한다.

DOCX: 파싱 메타데이터(bold, heading, indent) 기반 분할
Text: 느슨한(ultra-loose) 정규식으로 분할 가능 지점 탐색
"""

import re
from typing import List
from services.docx_parser import DocxSection, DocxParagraph, DocxTable
from services.docx_renderer import render_sections_to_annotated_text, render_section

# 최대 청크 크기 (문자 수). ~200K자 ≈ ~50K 토큰.
MAX_CHUNK_CHARS = 200000

# ── Ultra-loose 분할 지점 패턴 ──
# 영어/숫자/한글 등으로 시작하고 구분자(마침표/괄호/콜론/공백)가 따르는 줄.
# 정확한 문항번호가 아니어도 OK — 텍스트를 자르기 좋은 위치를 찾는 것이 목적.
_SPLIT_POINT_RE = re.compile(
    r'^\s*(?:\*\*)?'
    r'([A-Za-z0-9가-힣]+)'       # 영어, 숫자, 한글 등 시작
    r'[.)\]:\s]',                 # 구분자
    re.MULTILINE,
)


def _estimate_section_size(section: DocxSection) -> int:
    """섹션의 대략적인 문자 수를 추정"""
    size = len(section.heading or "")
    for item in section.content:
        if isinstance(item, DocxParagraph):
            size += len(item.text) + 10
        elif isinstance(item, DocxTable):
            for row in item.rows:
                size += sum(len(cell) for cell in row) + len(row) * 3
    return size


def _is_split_candidate(item) -> bool:
    """content 아이템이 청크 분할 후보인지 판별.

    메타데이터 우선 전략:
    1. DocxTable은 절대 분할 지점이 아님 (표 중간 분할 방지)
    2. Bold + 최상위 레벨 단락 → 분할 후보 (가장 신뢰도 높음)
    3. Heading 스타일 → 분할 후보
    4. 느슨한 정규식 매칭 → 폴백 분할 후보

    정규식은 최후 수단이며, 매칭 실패해도 무방.
    """
    if not isinstance(item, DocxParagraph):
        return False

    # Bold이고 목록/들여쓰기가 없는 독립 단락 → 높은 확률로 문항 시작
    if item.is_bold and item.list_level is None and item.indent_level == 0:
        return True

    # Heading 스타일
    if item.style_name and 'Heading' in item.style_name:
        return True

    # 느슨한 정규식 — 폴백 분할 가이드
    text = item.text.strip()
    if text and _SPLIT_POINT_RE.match(text):
        # 목록 항목이나 들여쓰기된 텍스트는 제외 (보기일 가능성)
        if item.list_level is not None or item.indent_level > 0:
            return False
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

    메타데이터 기반 분할 후보에서 분할하며,
    DocxTable 중간에서는 절대 분할하지 않습니다.
    """
    chunks = []
    current_items = []
    current_size = 0
    heading_text = section.heading

    for item in section.content:
        item_size = _estimate_item_size(item)

        # 분할 후보이면서 이미 누적된 내용이 크면 분할
        # DocxTable은 _is_split_candidate에서 False → 표 중간 분할 방지
        if (_is_split_candidate(item) and
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
