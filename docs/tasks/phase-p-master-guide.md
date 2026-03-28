# Phase P — 파서 레이어 강화 마스터 작업 지시서

> **목적**: DOCX 설문지 → 정확한 JSON 디지털 자산화  
> **범위**: DOCX 전용 (PDF 제외 결정 2026-03)  
> **총 Task 수**: 9개 (P0-SETUP + P1×5 + P2×2 + P3×1)

---

## 📋 전체 작업 맵

```
[P0-SETUP]  roadmap 등록 + PDF 제외 반영        ← 가장 먼저 실행
     │
     ├─► [P1-T1a] 병합 셀 처리 (DocxCell)       ─┐
     │                                            │  동시 실행 가능
     ├─► [P1-T1b] 취소선 셀 처리                 ─┘
     │                    │
     │                    ▼
     ├─► [P1-T2]  표 타입 분류기 (7-type)        ← P1-T1 완료 후
     │                    │
     │                    ▼
     ├─► [P1-T3]  텍스트 박스 추출               ← 독립, P1-T1과 병행 가능
     │
     │                    ▼
     └─► [P1-T4]  표 타입별 렌더링               ← P1-T1 + P1-T2 완료 후
                          │
                          ▼
                  [P2-T5]  스키마 확장            ← P1 전체 완료 후
                          │
                          ▼
                  [P2-T6]  프롬프트 + 스키마 교체 ← P2-T5 완료 후
                          │
                          ▼
                  [P3-T8]  1셀 표 섹션 감지       ← P1-T2 완료 후 (독립 가능)
```

---

## 🚀 Claude Code 세션별 작업 지시

### ⭐ 세션 0: 환경 준비 (5분)

프로젝트 폴더에서 Claude Code 실행 후:

```
@docs/tasks/task-p0-setup.md 파일을 읽고 구현해줘.
roadmap.md에 Phase P 섹션 추가하고, CLAUDE.md에 PDF 제외 주석을 넣어줘.
완료 후 smoke test 실행해서 확인해줘.
```

**완료 기준**: `docs/roadmap.md`에 Phase P 9개 항목 등록됨

---

### 🔵 세션 1: 파서 기반 강화 (P1-T1a + P1-T1b)

P1-T1a (병합 셀)와 P1-T1b (취소선 셀)은 같은 파일(`docx_parser.py`)을 수정하므로
**하나의 세션에서 순서대로 진행**한다.

```
먼저 @docs/tasks/task-p1t1-merged-cell-parsing.md 를 읽고 구현해줘.
DocxCell dataclass 추가 + _parse_table() 병합 셀 처리를 완성하고 smoke test를 통과시켜줘.

그 다음 @docs/tasks/task-p1t1-strikethrough-cells.md 를 읽고 구현해줘.
_is_cell_strikethrough() 헬퍼 추가 + _parse_table()에 취소선 처리를 추가해줘.
smoke test를 통과시키고 두 task 모두 roadmap에 체크해줘.
```

**완료 기준**:
- `DocxCell`, `DocxTable.has_merged_cells`, `DocxTable.rows_text` 존재
- 취소선 셀 → `""` 치환 동작
- 두 smoke test 모두 통과

---

### 🔵 세션 2: 표 타입 분류기 (P1-T2)

```
@docs/tasks/task-p1t2-table-type-classifier.md 를 읽고 구현해줘.

주의사항:
1. DocxTable.table_type 필드 추가 시 기본값 "unknown" 확인
2. _classify_table()의 multi_question 감지 임계값은 보수적으로 60% 이상으로 설정
3. coding_reference 감지 키워드에 한국어 포함 확인

완료 후:
- python -c "from services.docx_parser import _classify_table; print(_classify_table([['Code','Label'],['1','만족']]))" 실행해서 "coding_reference" 출력 확인
- smoke test 전체 통과 확인
- roadmap의 TASK-P1T2 체크
```

**완료 기준**: 7가지 타입 분류 smoke test 9개 케이스 모두 통과

---

### 🔵 세션 3: 텍스트 박스 추출 (P1-T3) — 독립 작업

> P1-T1과 병행 실행 가능. 컨텍스트가 길어지면 `/clear` 후 별도 세션으로 진행.

```
@docs/tasks/task-p1t3-textbox-extraction.md 를 읽고 구현해줘.

구현 전에 먼저:
python -c "
from docx import Document
# 텍스트 박스가 있는 실제 DOCX 파일 없으면 XML 구조만 확인
import docx.oxml.ns as ns
print(ns.qn('w:drawing'))
" 실행해서 네임스페이스 확인

WPS_NS 상수 추가 후 _extract_textbox_text() 구현.
빈 단락에서 오류 없이 동작하는지 확인.
smoke test 통과 후 roadmap 체크.
```

---

### 🔵 세션 4: 타입별 렌더링 (P1-T4)

> P1-T1 + P1-T2 완료 후 진행.

```
@docs/tasks/task-p1t4-table-type-renderer.md 를 읽고 구현해줘.

중요:
1. services/docx_renderer.py의 render_table() 함수를 교체하되,
   render_paragraph(), render_section(), render_sections_to_annotated_text()는 건드리지 마
2. SYSTEM_PROMPT 수정 시 기존 내용을 삭제하지 말고 "RENDERING MARKERS" 섹션을 추가만 해
3. DocxTable에 table_type이 없는 경우(구 코드 호환) getattr(table, 'table_type', 'unknown') 사용

완료 후:
- grid 표 렌더링에서 [TABLE:grid], [SCALE_HEADER], [ROW] 마커 확인
- coding_reference 표 → 빈 문자열 확인
- SYSTEM_PROMPT에 "RENDERING MARKERS" 텍스트 존재 확인
- smoke test 통과 후 roadmap 체크
```

---

### 🟡 세션 5: 스키마 확장 (P2-T5)

> P1 전체 완료 후 진행.

```
@docs/tasks/task-p2t5-schema-extension.md 를 읽고 구현해줘.

구현 전에 models/survey.py 전체를 읽어서 현재 SurveyQuestion 필드 목록 파악해줘.
이미 sub_items나 programming_guide 필드가 있으면 중복 추가하지 말고 from_llm_dict()만 업데이트해.

주의:
- to_dataframe()의 SubItems 컬럼은 ", ".join(sub_items) 형태로 추가
- 구 JSON(sub_items 없음) 역직렬화가 빈 리스트를 반환하는지 반드시 확인
- python -c "from app import *; print('import OK')" 로 전체 import 체인 확인

smoke test 통과 후 roadmap 체크.
```

---

### 🟡 세션 6: 프롬프트 + 스키마 교체 (P2-T6)

> P2-T5 완료 + P1-T4 완료 후 진행.

```
@docs/tasks/task-p2t6-prompt-schema.md 를 읽고 구현해줘.

중요:
1. SYSTEM_PROMPT는 매우 긴 문자열이므로, 수정 전 전체 내용을 먼저 출력해서 구조 파악
2. "RENDERING MARKERS" 섹션이 이미 있으면 중복 삽입 금지
3. OUTPUT 스키마 섹션만 교체 — 나머지 섹션은 유지
4. from_llm_dict()에서 programming_guide가 None이어도 오류 없어야 함

검증:
- python -c "from services.llm_extractor import SYSTEM_PROMPT; print('sub_items' in SYSTEM_PROMPT, 'programming_guide' in SYSTEM_PROMPT)"
  → True True 출력 확인
- smoke test 통과 후 roadmap 체크
```

---

### 🟢 세션 7: 섹션 감지 강화 (P3-T8)

> P1-T2 완료 후 실행 가능 (독립적).

```
@docs/tasks/task-p3t8-section-detection.md 를 읽고 구현해줘.

구현 전에 services/docx_parser.py의 parse_docx() 함수를 읽어서
현재 섹션 분리 로직을 정확히 파악해줘.

핵심 변경:
- elif tag == 'tbl': 블록에서 parsed_table.table_type == "section_header" 처리 추가
- 해당 표는 content에 추가하지 않고 heading으로만 사용

주의: continue 문이 outer for loop에 적용되는지 확인.
      아니면 flag 방식으로 구현.

smoke test의 Test 2 (DocxSection.heading 변환)을 특히 꼼꼼히 확인.
완료 후 roadmap 체크.
```

---

## 🔧 세션 사이 공통 검증 명령

각 세션 완료 후 항상 실행:

```bash
# 1. 전체 import 체인
python -c "from app import *; print('✅ import OK')"

# 2. 핵심 파일 컴파일 확인
python -m py_compile services/docx_parser.py
python -m py_compile services/docx_renderer.py
python -m py_compile services/llm_extractor.py
python -m py_compile models/survey.py

# 3. 전체 smoke test 실행
python -m pytest tests/ -v -k "smoke_test_p" --tb=short 2>&1 | tail -30
```

---

## ⚠️ 자주 발생하는 함정과 대처법

### 함정 1: SYSTEM_PROMPT 중복 삽입

**증상**: RENDERING MARKERS 섹션이 두 번 나타남  
**대처**: 수정 전 `assert 'RENDERING MARKERS' not in SYSTEM_PROMPT` 먼저 실행

### 함정 2: continue 문 스코프 오류

**증상**: `table_type == "section_header"` 처리 후 일반 표까지 건너뜀  
**대처**: inner `if` 블록에서 `continue`가 outer `for child in body:` 루프에 적용되는지 확인. 아니면 `_is_section_table` 플래그 사용

### 함정 3: DocxTable 하위 호환 깨짐

**증상**: 기존 코드에서 `table.rows`를 쓰는데 타입이 바뀜  
**대처**: `rows: List[List[str]]`은 유지. 신규 필드는 `raw_cells`, `rows_text`로 추가

### 함정 4: sub_items 중복 문제

**증상**: Grid 문항의 sub_items가 answer_options에도 들어감  
**대처**: `from_llm_dict()`에서 `sub_items` 있으면 `answer_options`는 스케일 코드만 보존

### 함정 5: 병합 셀 이중 계산

**증상**: `seen_tc_ids` 체크 + continuation 추가가 중복됨  
**대처**: `row.cells`는 이미 가상 셀을 반환하므로 `seen_tc_ids` 방식만 사용. `col_span` 기반 continuation 추가 금지

---

## 📊 진행 추적 체크리스트

```
[ ] P0-SETUP  : roadmap 등록, PDF 제외 반영
[ ] P1-T1a    : DocxCell + 병합 셀 처리
[ ] P1-T1b    : 취소선 셀 처리
[ ] P1-T2     : 표 타입 분류기 (7-type)
[ ] P1-T3     : 텍스트 박스 추출
[ ] P1-T4     : 타입별 렌더링 + SYSTEM_PROMPT 마커
[ ] P2-T5     : SurveyQuestion 스키마 확장 (sub_items, ProgrammingGuide)
[ ] P2-T6     : 프롬프트 + 출력 JSON 스키마 교체
[ ] P3-T8     : 1셀 표 섹션 헤더 감지
```

---

## 📁 Task 파일 디렉토리

| 파일 | 내용 | 선행 조건 |
|------|------|---------|
| `task-p0-setup.md` | roadmap 등록, PDF 제외 | 없음 |
| `task-p1t1-merged-cell-parsing.md` | DocxCell, 병합 셀 처리 | 없음 |
| `task-p1t1-strikethrough-cells.md` | 취소선 셀 처리 | P1-T1a 이후 |
| `task-p1t2-table-type-classifier.md` | 7-type 분류기 | P1-T1 |
| `task-p1t3-textbox-extraction.md` | 텍스트 박스 추출 | 없음 (독립) |
| `task-p1t4-table-type-renderer.md` | 타입별 LLM 렌더링 | P1-T1 + P1-T2 |
| `task-p2t5-schema-extension.md` | sub_items, ProgrammingGuide | P1 전체 |
| `task-p2t6-prompt-schema.md` | SYSTEM_PROMPT + JSON 스키마 | P2-T5 + P1-T4 |
| `task-p3t8-section-detection.md` | 1셀 표 → 섹션 경계 | P1-T2 |

---

## 💡 Claude Code 효율화 팁

### Plan Mode 활용 (복잡한 Task)

P1-T1, P2-T5 같이 구조 변경이 큰 Task는 실행 전 Plan Mode로 전환:
```
shift+tab (2회) → Plan Mode 진입
"/plan @docs/tasks/task-p2t5-schema-extension.md"
→ 계획 확인 후 승인
→ shift+tab → Normal Mode 복귀 → 실행
```

### 컨텍스트 길어질 때

한 세션에서 여러 Task 진행 시 컨텍스트가 길어지면:
```
/clear
```
후 roadmap 체크박스가 상태를 기억하므로 안전하게 이어서 진행.

### 세션 시작 확인 명령

새 세션 시작 시 항상:
```
현재 roadmap 상태 확인해줘: @docs/roadmap.md
다음 미완료 Phase P task는?
```

### 부분 실패 대응

smoke test 일부 실패 시:
```
smoke test에서 Test 3이 실패했어. 해당 부분만 다시 확인하고 수정해줘.
수정 후 전체 smoke test 다시 실행해서 모두 통과하는지 확인해줘.
```

### 긴급 롤백

심각한 오류 발생 시:
```
git diff services/docx_parser.py
git checkout services/docx_parser.py
```
task spec 파일은 변경되지 않으므로 코드만 롤백 후 재시도.
