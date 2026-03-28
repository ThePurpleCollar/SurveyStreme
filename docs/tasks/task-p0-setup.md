# TASK-P0-SETUP: PDF 제외 결정 반영 & Phase P Roadmap 추가

## Status: 🔴 Not Started

## 배경

실제 7개 설문지 파일 분석 결과, DOCX만으로도 충분한 파싱 정확도를 달성할 수 있음이 확인됐다.
PDF는 텍스트 박스, 병합 셀, 서식 정보가 완전히 손실되므로 DOCX-only 전략으로 스코프를 명확히 한다.

또한 Phase P (Parser 레이어 강화) 태스크들이 새로 설계됐으나
`docs/roadmap.md`에 아직 등록되지 않았다.

## Goal

1. `docs/roadmap.md`에 **Phase P — 파서 레이어 강화** 섹션 추가
2. `CLAUDE.md`에 PDF 스코프 제외 주석 추가
3. README.md의 지원 포맷 설명 업데이트 (선택적)

## Files to Modify

- `docs/roadmap.md` — Phase P 섹션 추가
- `CLAUDE.md` — Tech Stack PDF 제외 주석

## Implementation Steps

### Step 1: docs/roadmap.md에 Phase P 섹션 추가

기존 내용 맨 아래에 아래 섹션을 추가한다:

```markdown
## Phase P — 파서 레이어 강화 (DOCX 전용)

> 실제 설문지 7개 파일 분석 결과 도출된 개선 항목.
> PDF는 서식 손실로 인해 스코프 제외 결정 (2026-03).

- [ ] **TASK-P0-SETUP**: PDF 제외 결정 반영, roadmap 업데이트 → @docs/tasks/task-p0-setup.md
- [ ] **TASK-P1T1**: _parse_table() 취소선 셀 처리 추가 → @docs/tasks/task-p1t1-strikethrough-cells.md
- [ ] **TASK-P1T2**: 표 타입 분류기 확장 (section_header, coding_reference, multi_question) → @docs/tasks/task-p1t2-table-type-classifier.md
- [ ] **TASK-P2T6**: LLM 프롬프트 + 출력 JSON 스키마 교체 완료 → @docs/tasks/task-p2t6-prompt-schema.md
- [ ] **TASK-P3T8**: 1셀 표 섹션 헤더 패턴 추가 → @docs/tasks/task-p3t8-section-detection.md
```

### Step 2: CLAUDE.md Tech Stack 섹션에 PDF 제외 주석 추가

`CLAUDE.md`의 Tech Stack 섹션에서 `PyMuPDF` 줄 뒤에 아래 한 줄을 추가한다:

```
# NOTE: PDF 스코프 제외 결정 (2026-03). 현재 DOCX-only 파이프라인만 유지.
#       PyMuPDF는 기존 PDF 경로 호환성 유지를 위해 의존성에 잔류하나, 신규 개발 없음.
```

## Do NOT Change

- 기존 Phase 1~10 섹션 (건드리지 않음)
- `services/pdf_parser.py` 파일 자체 (삭제/수정 불가, 기존 코드 호환성 유지)
- `pages/doc_analyzer.py`의 PDF 업로드 UI (기존 사용자가 있을 수 있음)

## Verification Checklist

- [ ] `docs/roadmap.md`에 "Phase P" 섹션이 존재함
- [ ] Phase P에 5개 task 항목이 `[ ]` (미완료) 상태로 등록됨
- [ ] 각 task 항목에 `@docs/tasks/task-p*.md` 참조가 포함됨
- [ ] `CLAUDE.md`에 PDF 제외 주석이 추가됨
- [ ] `python -c "from app import *; print('import OK')"` 성공 (코드 변경 없으므로 반드시 통과해야 함)

## Smoke Test Script

```python
# tests/smoke_test_p0_setup.py
import os

# roadmap.md에 Phase P 섹션 존재 확인
roadmap_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                             'docs', 'roadmap.md')
assert os.path.exists(roadmap_path), "docs/roadmap.md 파일이 없습니다"

with open(roadmap_path, encoding='utf-8') as f:
    content = f.read()

assert 'Phase P' in content, "Phase P 섹션이 없습니다"
assert 'TASK-P1T1' in content, "TASK-P1T1이 없습니다"
assert 'TASK-P1T2' in content, "TASK-P1T2가 없습니다"
assert 'TASK-P2T6' in content, "TASK-P2T6이 없습니다"
assert 'TASK-P3T8' in content, "TASK-P3T8이 없습니다"
assert 'task-p1t1-strikethrough-cells.md' in content, "task-p1t1 파일 참조 없음"
assert 'task-p1t2-table-type-classifier.md' in content, "task-p1t2 파일 참조 없음"
assert 'task-p2t6-prompt-schema.md' in content, "task-p2t6 파일 참조 없음"
assert 'task-p3t8-section-detection.md' in content, "task-p3t8 파일 참조 없음"

# CLAUDE.md에 PDF 제외 주석 확인
claude_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                            'CLAUDE.md')
assert os.path.exists(claude_path), "CLAUDE.md 파일이 없습니다"

with open(claude_path, encoding='utf-8') as f:
    claude_content = f.read()

assert 'PDF 스코프 제외' in claude_content or 'DOCX-only' in claude_content, \
    "CLAUDE.md에 PDF 제외 결정이 반영되지 않았습니다"

print("✅ P0-SETUP smoke test 통과")
```

## 예상 소요 시간

약 15분 (텍스트 편집만)
