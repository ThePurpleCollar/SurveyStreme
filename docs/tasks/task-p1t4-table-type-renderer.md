# TASK-P1T4: 표 타입별 LLM 친화적 렌더링

## Status: 🔴 Not Started

## 선행 조건

**P1-T1 완료 필수** — `DocxTable.raw_cells`, `rows_text` 프로퍼티 필요
**P1-T2 완료 필수** — `DocxTable.table_type` 분류 결과 필요

## 배경

P1-T1, P1-T2로 파서가 표 구조와 유형을 정확히 파악하게 됐으나,
LLM에 전달되는 텍스트가 여전히 단순 마크다운 표 형식이면 개선 효과가 전달되지 않는다.

### 현재 vs 목표 렌더링 (Grid 예시)

**현재 (단순 마크다운):**
```
| Q5. 브랜드 평가 | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
|  | 브랜드 이미지 | | | | |
|  | 제품 품질 | | | | |
```

**목표 (구조화된 마커):**
```
[TABLE:grid]
[STEM] Q5. 브랜드 평가
[SCALE_HEADER] 1 | 2 | 3 | 4 | 5
[ROW] 브랜드 이미지
[ROW] 제품 품질
[/TABLE]
```

## Goal

1. `render_table()`을 표 타입별 분기 렌더러로 교체
2. 각 유형별 LLM 친화적 포맷 구현
3. SYSTEM_PROMPT에 신규 마커 해석 규칙 추가 (P2-T6에서 확장 예정이나 기본은 여기서)

## 유형별 목표 렌더링

| 타입 | 렌더링 포맷 |
|------|------------|
| `section_header` | `[SECTION: TEXT]` |
| `coding_reference` | `""` (스킵, LLM에 미전달) |
| `multi_question` | `[TABLE:multi_question]` + 마크다운 |
| `code_label` | `[TABLE:options]...[/TABLE]` |
| `grid` | `[TABLE:grid] [STEM] [SCALE_HEADER] [ROW]...` |
| `matrix` | `[TABLE:matrix] [COL_HEADER] [ROW]...` |
| `generic` / `unknown` | `[TABLE:info]` + 마크다운 |

## Files to Modify

- `services/docx_renderer.py` — `render_table()` 전면 교체
- `services/llm_extractor.py` — SYSTEM_PROMPT에 마커 설명 추가
- `tests/smoke_test_p1t4_renderer.py` (신규)

## Implementation Steps

### Step 1: render_table() 타입별 분기 (docx_renderer.py)

```python
def render_table(table: DocxTable) -> str:
    if not table.rows:
        return ""

    table_type = getattr(table, 'table_type', 'unknown')

    if table_type == "section_header":
        text = (table.rows_text[0][0] if hasattr(table, 'rows_text')
                else table.rows[0][0]).strip()
        return f"\n[SECTION: {text}]\n" if text else ""

    if table_type == "coding_reference":
        return ""  # LLM에 미전달

    rows = table.rows_text if hasattr(table, 'rows_text') else table.rows
    if not rows:
        return ""

    if table_type == "grid":
        return _render_grid_table(rows)
    elif table_type == "matrix":
        return _render_matrix_table(rows)
    elif table_type == "code_label":
        return _render_code_label_table(rows)
    elif table_type == "multi_question":
        return _render_multi_question_table(rows)
    else:
        return _render_generic_table(rows)


def _render_grid_table(rows: List[List[str]]) -> str:
    lines = ["\n[TABLE:grid]"]
    if not rows:
        return ""
    scale_header = " | ".join(c for c in rows[0] if c)
    lines.append(f"[SCALE_HEADER] {scale_header}")
    for row in rows[1:]:
        item = row[0].strip() if row else ""
        if item:
            lines.append(f"[ROW] {item}")
    lines.append("[/TABLE]\n")
    return "\n".join(lines)


def _render_matrix_table(rows: List[List[str]]) -> str:
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


def _render_code_label_table(rows: List[List[str]]) -> str:
    lines = ["\n[TABLE:options]"]
    for row in rows:
        line = "| " + " | ".join(c if c else "" for c in row) + " |"
        lines.append(line)
    lines.append("[/TABLE]\n")
    return "\n".join(lines)


def _render_multi_question_table(rows: List[List[str]]) -> str:
    lines = ["\n[TABLE:multi_question — 각 행이 별도 문항]"]
    for i, row in enumerate(rows):
        line = "| " + " | ".join(c if c else "" for c in row) + " |"
        lines.append(line)
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")
    lines.append("")
    return "\n".join(lines)


def _render_generic_table(rows: List[List[str]]) -> str:
    lines = ["\n[TABLE:info]"]
    for i, row in enumerate(rows):
        line = "| " + " | ".join(c if c else "" for c in row) + " |"
        lines.append(line)
        if i == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")
    lines.append("")
    return "\n".join(lines)
```

### Step 2: SYSTEM_PROMPT에 마커 해석 규칙 추가 (llm_extractor.py)

`SYSTEM_PROMPT`의 TABLE RECOGNITION 섹션 뒤에 추가:

```
RENDERING MARKERS — Special annotations in document text:
- [SECTION: TEXT] = Section boundary. NOT a question.
- [TABLE:grid] [SCALE_HEADER] N | N ... [ROW] item [/TABLE]:
  Scale battery. STEM before the table = question_text.
  SCALE_HEADER count → question_type (e.g., "5pt x N").
  ROW items → sub_items list.
- [TABLE:matrix] [COL_HEADER] ... [ROW] item [/TABLE]:
  Non-scale matrix. COL_HEADER → answer_options, ROW items → sub_items.
- [TABLE:options]...[/TABLE] = Answer options for preceding question.
- [TABLE:multi_question ...]: Each DATA ROW is a separate question.
- [TABLE:info]: Informational. NOT a question.
```

## Do NOT Change

- `render_paragraph()` 함수
- `render_section()`, `render_sections_to_annotated_text()` 구조
- `chunker.py` 청킹 로직

## Verification Checklist

- [ ] `python -m py_compile services/docx_renderer.py` 성공
- [ ] `python -c "from services.docx_renderer import render_table; print('OK')"` 성공
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] `grid` 표에서 `[TABLE:grid]`, `[SCALE_HEADER]`, `[ROW]` 마커 확인
- [ ] `coding_reference` → 빈 문자열 확인
- [ ] Smoke Test 전체 통과

## Smoke Test Script

```python
# tests/smoke_test_p1t4_renderer.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.docx_parser import DocxTable
from services.docx_renderer import render_table

def make_table(rows, table_type="unknown"):
    return DocxTable(rows=rows, row_count=len(rows),
                     col_count=len(rows[0]) if rows else 0,
                     table_type=table_type)

# grid 렌더링
t = make_table([["","1","2","3","4","5"],
                ["브랜드이미지","○","○","○","○","○"],
                ["제품품질","○","○","○","○","○"]], "grid")
r = render_table(t)
assert "[TABLE:grid]" in r and "[SCALE_HEADER]" in r and "[ROW] 브랜드이미지" in r
print("✅ grid 렌더링 OK")

# coding_reference → 빈 문자열
t2 = make_table([["Code","Label"],["1","만족"]], "coding_reference")
assert render_table(t2) == ""
print("✅ coding_reference 스킵 OK")

# section_header
t3 = make_table([["SECTION A"]], "section_header")
r3 = render_table(t3)
assert "[SECTION: SECTION A]" in r3
print("✅ section_header 렌더링 OK")

print("\n🎉 ALL P1T4-RENDERER TESTS PASSED")
```

## 예상 소요 시간

약 2시간 (렌더러 구현 1.5h + 프롬프트 추가 0.5h)
