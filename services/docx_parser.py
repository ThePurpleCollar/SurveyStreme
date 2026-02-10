"""DOCX 파일을 서식 메타데이터와 함께 파싱하는 모듈.

python-docx로 각 paragraph의 스타일, 서식(굵기/기울임/밑줄/취소선/대문자),
들여쓰기 레벨, 목록 레벨, 표 데이터를 추출합니다.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Union
from docx import Document

# Word XML 네임스페이스
WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NSMAP = {'w': WORD_NS}


@dataclass
class DocxRun:
    """paragraph 내 개별 텍스트 런"""
    text: str
    is_bold: bool = False
    is_italic: bool = False
    is_underline: bool = False
    is_strike: bool = False


@dataclass
class DocxParagraph:
    """서식 메타데이터를 포함한 paragraph"""
    text: str
    style_name: str = "Normal"
    is_bold: bool = False          # 전체 paragraph가 굵은지
    is_italic: bool = False
    is_underline: bool = False
    is_strikethrough: bool = False
    is_all_caps: bool = False
    indent_level: int = 0          # left_indent 기반 (0, 1, 2...)
    list_level: Optional[int] = None   # 목록 레벨 (None이면 목록 아님)
    list_num_id: Optional[int] = None  # 같은 목록 그룹 ID
    is_numbered_list: bool = False     # True면 번호 목록, False면 글머리 기호
    runs: List[DocxRun] = field(default_factory=list)


@dataclass
class DocxTable:
    """DOCX 테이블"""
    rows: List[List[str]] = field(default_factory=list)
    header_row: List[str] = field(default_factory=list)
    row_count: int = 0
    col_count: int = 0


ContentItem = Union[DocxParagraph, DocxTable]


@dataclass
class DocxSection:
    """문서의 논리적 섹션 (Heading 단위로 분리)"""
    heading: Optional[str] = None
    content: List[ContentItem] = field(default_factory=list)  # 단락+표 원본 순서 보존

    @property
    def paragraphs(self) -> List[DocxParagraph]:
        return [c for c in self.content if isinstance(c, DocxParagraph)]

    @property
    def tables(self) -> List[DocxTable]:
        return [c for c in self.content if isinstance(c, DocxTable)]


def _get_list_info(paragraph) -> tuple:
    """paragraph의 XML에서 목록 레벨과 numId를 추출.

    Returns:
        (list_level, num_id, is_numbered)
    """
    pPr = paragraph._element.find(f'{{{WORD_NS}}}pPr')
    if pPr is None:
        return None, None, False

    numPr = pPr.find(f'{{{WORD_NS}}}numPr')
    if numPr is None:
        return None, None, False

    ilvl_elem = numPr.find(f'{{{WORD_NS}}}ilvl')
    numId_elem = numPr.find(f'{{{WORD_NS}}}numId')

    list_level = int(ilvl_elem.get(f'{{{WORD_NS}}}val', '0')) if ilvl_elem is not None else 0
    num_id = int(numId_elem.get(f'{{{WORD_NS}}}val', '0')) if numId_elem is not None else None

    # numId == 0은 목록 아님
    if num_id == 0:
        return None, None, False

    # 번호 매기기 형식 확인 시도
    is_numbered = _check_numbering_format(paragraph, num_id, list_level)
    return list_level, num_id, is_numbered


def _check_numbering_format(paragraph, num_id, list_level) -> bool:
    """numbering.xml에서 번호 매기기 형식 확인.

    Returns: True면 번호 목록, False면 글머리 기호
    """
    try:
        numbering_part = paragraph.part.numbering_part
        if numbering_part is None:
            return False

        numbering_xml = numbering_part._element

        # w:num 요소 찾기
        for num_elem in numbering_xml.findall(f'{{{WORD_NS}}}num'):
            if int(num_elem.get(f'{{{WORD_NS}}}numId', '0')) == num_id:
                abstract_num_id_elem = num_elem.find(f'{{{WORD_NS}}}abstractNumId')
                if abstract_num_id_elem is None:
                    continue
                abstract_num_id = int(abstract_num_id_elem.get(f'{{{WORD_NS}}}val', '0'))

                # w:abstractNum에서 numFmt 확인
                for abstract_num in numbering_xml.findall(f'{{{WORD_NS}}}abstractNum'):
                    if int(abstract_num.get(f'{{{WORD_NS}}}abstractNumId', '0')) == abstract_num_id:
                        for lvl in abstract_num.findall(f'{{{WORD_NS}}}lvl'):
                            if int(lvl.get(f'{{{WORD_NS}}}ilvl', '0')) == list_level:
                                num_fmt = lvl.find(f'{{{WORD_NS}}}numFmt')
                                if num_fmt is not None:
                                    fmt_val = num_fmt.get(f'{{{WORD_NS}}}val', '')
                                    # bullet은 글머리 기호, 나머지(decimal, lowerLetter 등)는 번호
                                    return fmt_val != 'bullet'
                        break
                break
    except Exception:
        pass
    return False


def _get_indent_level(paragraph) -> int:
    """paragraph의 들여쓰기 레벨 계산 (EMU → 레벨)"""
    pf = paragraph.paragraph_format
    left_indent = pf.left_indent
    if left_indent is None:
        return 0
    # 1 레벨 ≈ 360000 EMU (약 0.25인치)
    return max(0, int(left_indent / 360000))


def _parse_paragraph(paragraph) -> Optional[DocxParagraph]:
    """python-docx paragraph를 DocxParagraph로 변환"""
    text = paragraph.text.strip()

    # 빈 paragraph 건너뛰기
    if not text:
        return None

    # 스타일 이름
    style_name = paragraph.style.name if paragraph.style else "Normal"

    # 런 분석
    runs = []
    all_bold = True
    all_italic = True
    all_underline = True
    all_strike = True
    all_caps = True
    has_runs = False

    for run in paragraph.runs:
        if not run.text.strip():
            continue
        has_runs = True

        run_bold = bool(run.font.bold)
        run_italic = bool(run.font.italic)
        run_underline = bool(run.font.underline)
        run_strike = bool(run.font.strike)

        if not run_bold:
            all_bold = False
        if not run_italic:
            all_italic = False
        if not run_underline:
            all_underline = False
        if not run_strike:
            all_strike = False
        if not run.font.all_caps:
            all_caps = False

        runs.append(DocxRun(
            text=run.text,
            is_bold=run_bold,
            is_italic=run_italic,
            is_underline=run_underline,
            is_strike=run_strike,
        ))

    if not has_runs:
        all_bold = False
        all_italic = False
        all_underline = False
        all_strike = False
        all_caps = False

    # 취소선 paragraph는 건너뛰기
    if all_strike and has_runs:
        return None

    # 목록 정보
    list_level, list_num_id, is_numbered = _get_list_info(paragraph)

    # 들여쓰기 레벨
    indent_level = _get_indent_level(paragraph)

    return DocxParagraph(
        text=text,
        style_name=style_name,
        is_bold=all_bold,
        is_italic=all_italic,
        is_underline=all_underline,
        is_strikethrough=all_strike,
        is_all_caps=all_caps,
        indent_level=indent_level,
        list_level=list_level,
        list_num_id=list_num_id,
        is_numbered_list=is_numbered,
        runs=runs,
    )


def _parse_table(table) -> DocxTable:
    """python-docx Table을 DocxTable로 변환"""
    rows_data = []
    for row in table.rows:
        row_data = [cell.text.strip() for cell in row.cells]
        rows_data.append(row_data)

    return DocxTable(
        rows=rows_data,
        header_row=rows_data[0] if rows_data else [],
        row_count=len(rows_data),
        col_count=len(rows_data[0]) if rows_data else 0,
    )


def parse_docx(file) -> List[DocxSection]:
    """DOCX 파일을 서식 정보와 함께 섹션 단위로 파싱.

    Args:
        file: 업로드된 파일 객체 또는 파일 경로

    Returns:
        DocxSection 리스트 (Heading 단위로 분리)
    """
    doc = Document(file)
    sections = []
    current_section = DocxSection()

    # 문서 body의 모든 요소를 순서대로 처리
    # doc.element.body의 자식 요소를 순회하여 paragraph와 table 순서를 보존
    body = doc.element.body

    # paragraph와 table을 인덱싱하기 위한 매핑
    para_index = 0
    table_index = 0

    for child in body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag

        if tag == 'p':
            # Paragraph
            if para_index < len(doc.paragraphs):
                paragraph = doc.paragraphs[para_index]
                para_index += 1

                parsed = _parse_paragraph(paragraph)
                if parsed is None:
                    continue

                # Heading이면 새 섹션 시작
                if parsed.style_name and 'Heading' in parsed.style_name:
                    if current_section.content or current_section.heading:
                        sections.append(current_section)
                    current_section = DocxSection(heading=parsed.text)
                else:
                    current_section.content.append(parsed)

        elif tag == 'tbl':
            # Table
            if table_index < len(doc.tables):
                table = doc.tables[table_index]
                table_index += 1

                parsed_table = _parse_table(table)
                if parsed_table.row_count > 0:
                    current_section.content.append(parsed_table)

    # 마지막 섹션 추가
    if current_section.content or current_section.heading:
        sections.append(current_section)

    return sections
