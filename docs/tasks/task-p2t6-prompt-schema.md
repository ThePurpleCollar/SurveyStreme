# TASK-P2T6: LLM 프롬프트 확장 + 출력 JSON 스키마 교체 완료

## Status: 🟡 In Progress (90%)

## 선행 조건

**TASK-P1T2 완료 권장** — `[SECTION: ...]`, `[TABLE:multi_question]`, `coding_reference` 스킵 마커가
docx_renderer에 추가된 후 프롬프트에 해석 규칙을 추가해야 한다.

## 배경 및 문제 정의

### 90% 완료된 상태 (이전 세션에서 중단)

이전 세션에서 SYSTEM_PROMPT의 다음 부분들을 업데이트했으나 **OUTPUT JSON 스키마 섹션**에서 중단됨:

- ✅ FORMAT A~E 설명 업데이트
- ✅ ANSWER OPTIONS 추출 규칙 섹션 추가 (TASK-14)
- ✅ skip_logic/filter 추출 규칙 추가 (TASK-15)
- ✅ 청크 컨텍스트 주입 로직 (TASK-07)
- 🟡 **미완료**: 신규 표 타입 마커 해석 규칙 추가
- 🟡 **미완료**: OUTPUT JSON 스키마 교체 (sub_items + programming_guide 포함)

### 신규 요구사항 (이번 Task에서 완료)

**1. 신규 표 타입 마커 처리 규칙 추가**

TASK-P1T2 완료 후 renderer가 추가한 마커들:
- `[SECTION: 텍스트]` — 섹션 경계 표시, 문항 추출 대상 아님
- `[TABLE:multi_question — 각 행이 별도 문항]` — 각 행을 독립 문항으로 추출
- coding_reference 표 → 렌더링 자체가 생략됨 (처리 불필요)
- `[TABLE:options]...[/TABLE]` — 보기 목록
- `[TABLE:grid — 척도형 배터리]` — Grid 문항

**2. 출력 JSON 스키마 교체**

현재 OUTPUT 스키마 (불완전):
```json
{
  "questions": [
    {
      "question_number", "question_text", "question_type",
      "answer_options", "skip_logic", "filter", "instructions"
    }
  ]
}
```

목표 OUTPUT 스키마 (task-p2t5에서 추가된 필드 포함):
```json
{
  "questions": [
    {
      "question_number": "string",
      "question_text": "string",
      "question_type": "string or null",
      "answer_options": [{"code": "string", "label": "string"}],
      "sub_items": ["string"],
      "skip_logic": [{"condition": "string", "target": "string"}],
      "filter": "string or null",
      "instructions": "string or null",
      "programming_guide": {
        "rotate_options": false,
        "exclusive_codes": [],
        "dk_codes": [],
        "na_codes": [],
        "pipe_from": null,
        "constant_sum_total": null,
        "rank_limit": null,
        "anchor_labels": {},
        "raw_notes": null
      }
    }
  ]
}
```

**3. from_llm_dict() 업데이트**

`SurveyQuestion.from_llm_dict()`에서 새 필드(`sub_items`, `programming_guide`)를 
LLM JSON 응답에서 올바르게 매핑하도록 수정.

## Goal

1. `SYSTEM_PROMPT`에 **RENDERING MARKERS** 섹션 추가 — 신규 표 타입 마커 해석 규칙
2. `SYSTEM_PROMPT`의 OUTPUT 스키마 섹션 교체 — `sub_items` + `programming_guide` 포함
3. `SurveyQuestion.from_llm_dict()`에 `sub_items`, `programming_guide` 필드 매핑 추가
4. `from_llm_dict()` 하위 호환성 유지 — 기존 필드 없이도 동작

## 수정 대상 파일

- `services/llm_extractor.py` — SYSTEM_PROMPT 업데이트 (2곳)
- `models/survey.py` — `from_llm_dict()` 업데이트
- `tests/smoke_test_p2t6_schema.py` — 신규 생성

## Implementation Steps

### Step 1: SYSTEM_PROMPT에 RENDERING MARKERS 섹션 추가 (llm_extractor.py)

**위치**: ANSWER OPTIONS 섹션 바로 앞 (또는 FORMAT 섹션 뒤)에 삽입

추가할 내용:
```
RENDERING MARKERS — Special annotations in the text:

- [SECTION: TEXT] — A section boundary marker. This is NOT a question. Skip it.
- [TABLE:multi_question — ...] followed by a table: Each DATA ROW of this table
  is a separate question. Row format: | Q_NUMBER | Question Text | answer cols... |
  Extract each row as an individual question with its own question_number.
- [TABLE:options]...[/TABLE] — Answer options for the preceding question.
  Extract as answer_options for the most recent question above.
- [TABLE:grid — ...]...: A scale battery grid.
  - First row = scale headers (numbers) → use for question_type (e.g., "5pt x N")
  - Data rows = sub_items (battery items)
- [TABLE:matrix — ...]...: A non-scale matrix.
  - First row = column headers → use as answer_options labels
  - Data rows = sub_items
- [TABLE:info]...: Informational table. Usually NOT a question — skip unless it
  clearly contains a question stem.
```

### Step 2: SYSTEM_PROMPT의 OUTPUT 스키마 섹션 교체 (llm_extractor.py)

현재 OUTPUT 섹션을 찾아 아래 내용으로 교체한다.

**현재 (교체 전):**
```
OUTPUT: Return ONLY valid JSON (no markdown code blocks):
{
  "questions": [
    {
      "question_number": "string",
      "question_text": "string",
      "question_type": "string or null",
      "answer_options": [{"code": "string", "label": "string"}],
      "skip_logic": [{"condition": "string", "target": "string"}],
      "filter": "string or null",
      "instructions": "string or null"
    }
  ]
}

Use [] for empty arrays, null for empty strings. Do NOT wrap in code blocks.
```

**교체 후:**
```
OUTPUT: Return ONLY valid JSON. No markdown code blocks, no explanation.

{
  "questions": [
    {
      "question_number": "string — the question identifier (e.g., 'Q1', 'SC2')",
      "question_text": "string — question text WITHOUT number prefix or type brackets",
      "question_type": "string or null — SA/MA/OE/NUMERIC/SCALE/GRID/MATRIX/Npt/TopN/etc.",
      "answer_options": [
        {"code": "string", "label": "string"}
      ],
      "sub_items": [
        "string — battery item label (for GRID/MATRIX questions only, else [])"
      ],
      "skip_logic": [
        {"condition": "string", "target": "string"}
      ],
      "filter": "string or null — who answers this question",
      "instructions": "string or null — interviewer notes (SHOW CARD, ROTATE, etc.)",
      "programming_guide": {
        "rotate_options": false,
        "exclusive_codes": [],
        "dk_codes": [],
        "na_codes": [],
        "pipe_from": null,
        "constant_sum_total": null,
        "rank_limit": null,
        "anchor_labels": {},
        "raw_notes": null
      }
    }
  ]
}

RULES:
- Use [] for empty arrays, null for missing string/number values.
- programming_guide: populate ONLY fields you can detect; leave others as shown above.
  - rotate_options: true if "ROTATE", "randomize", "보기 로테이션" is mentioned
  - exclusive_codes: list of code strings for "해당없음", "None of the above", "단독응답"
  - dk_codes: list of code strings for "모르겠음", "DK", "잘 모름"
  - na_codes: list of code strings for "해당없음", "N/A", "해당사항없음"
  - pipe_from: question number string if piping is indicated (e.g., "Q3")
  - constant_sum_total: number if "total must equal N" (e.g., 100)
  - rank_limit: number if "Top N" ranking (e.g., 3 for "Top 3")
  - anchor_labels: {"1": "Not at all", "5": "Extremely"} for scale anchors
  - raw_notes: any remaining programming notes as a single string
- If programming_guide has no detectable fields, omit it entirely or return null.
```

### Step 3: models/survey.py — SurveyQuestion에 sub_items 필드 추가 확인 및 from_llm_dict() 업데이트

먼저 `models/survey.py`를 읽어 `SurveyQuestion`에 `sub_items` 필드가 있는지 확인한다.

**없으면**: task-p2t5가 아직 실행되지 않은 것이므로, 최소한 `sub_items` 필드를 추가한다:
```python
# SurveyQuestion dataclass에 추가:
sub_items: List[str] = field(default_factory=list)   # Grid/Matrix 배터리 항목
programming_guide_raw: Optional[dict] = None          # LLM 추출 원본 (구조화 보류)
```

**있으면**: task-p2t5가 이미 완료된 것이므로, from_llm_dict() 업데이트만 진행.

`from_llm_dict()` 업데이트:
```python
@classmethod
def from_llm_dict(cls, d: dict) -> 'SurveyQuestion':
    """LLM JSON 응답 딕셔너리에서 SurveyQuestion 생성."""
    # ... 기존 코드 ...
    
    # sub_items 추가 (list of strings)
    sub_items = d.get("sub_items", [])
    if not isinstance(sub_items, list):
        sub_items = []
    sub_items = [str(s).strip() for s in sub_items if s]
    
    # programming_guide 추가 (dict 그대로 저장)
    pg_raw = d.get("programming_guide")
    if not isinstance(pg_raw, dict):
        pg_raw = None
    
    return cls(
        # ... 기존 필드들 ...
        sub_items=sub_items,
        programming_guide_raw=pg_raw,
    )
```

## Do NOT Change

- `SYSTEM_PROMPT`의 FORMAT A~E 섹션 (건드리지 않음)
- `SYSTEM_PROMPT`의 ANSWER OPTIONS 섹션 (TASK-14에서 추가됨, 유지)
- `SYSTEM_PROMPT`의 skip_logic/filter 섹션 (TASK-15에서 추가됨, 유지)
- `_build_chunk_context()` 함수 (TASK-07에서 추가됨, 유지)
- `extract_survey_questions()` 파이프라인 로직 전체 구조
- `to_json_dict()`, `to_dataframe()` 등 기존 직렬화 메서드 구조

## Verification Checklist

- [ ] `python -m py_compile services/llm_extractor.py` 성공
- [ ] `python -m py_compile models/survey.py` 성공
- [ ] `python -c "from services.llm_extractor import SYSTEM_PROMPT; assert 'RENDERING MARKERS' in SYSTEM_PROMPT; print('OK')"` 성공
- [ ] `python -c "from services.llm_extractor import SYSTEM_PROMPT; assert 'sub_items' in SYSTEM_PROMPT; print('OK')"` 성공
- [ ] `python -c "from services.llm_extractor import SYSTEM_PROMPT; assert 'programming_guide' in SYSTEM_PROMPT; print('OK')"` 성공
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] Smoke Test 통과
- [ ] `from_llm_dict()`가 `sub_items` 없는 구형 JSON도 정상 처리

## Smoke Test Script

```python
# tests/smoke_test_p2t6_schema.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_extractor import SYSTEM_PROMPT
from models.survey import SurveyQuestion

# ── Test 1: SYSTEM_PROMPT에 RENDERING MARKERS 섹션 존재 ──
assert 'RENDERING MARKERS' in SYSTEM_PROMPT, "RENDERING MARKERS 섹션 없음"
assert '[SECTION:' in SYSTEM_PROMPT or 'SECTION:' in SYSTEM_PROMPT, \
    "SECTION 마커 설명 없음"
assert 'multi_question' in SYSTEM_PROMPT, "multi_question 마커 설명 없음"
print("✅ Test 1: RENDERING MARKERS 섹션 OK")

# ── Test 2: SYSTEM_PROMPT OUTPUT 스키마에 sub_items ──
assert '"sub_items"' in SYSTEM_PROMPT, "OUTPUT 스키마에 sub_items 없음"
print("✅ Test 2: sub_items in SYSTEM_PROMPT OK")

# ── Test 3: SYSTEM_PROMPT OUTPUT 스키마에 programming_guide ──
assert '"programming_guide"' in SYSTEM_PROMPT, "OUTPUT 스키마에 programming_guide 없음"
assert '"rotate_options"' in SYSTEM_PROMPT, "rotate_options 필드 없음"
assert '"exclusive_codes"' in SYSTEM_PROMPT, "exclusive_codes 필드 없음"
print("✅ Test 3: programming_guide in SYSTEM_PROMPT OK")

# ── Test 4: from_llm_dict()가 sub_items 포함한 JSON 처리 ──
llm_response = {
    "question_number": "Q5",
    "question_text": "다음 브랜드 평가",
    "question_type": "5pt x 3",
    "answer_options": [
        {"code": "1", "label": "전혀 아님"},
        {"code": "5", "label": "매우 그러함"},
    ],
    "sub_items": ["브랜드 인지도", "구매 의향", "재구매 의향"],
    "skip_logic": [],
    "filter": None,
    "instructions": "ROTATE",
    "programming_guide": {
        "rotate_options": True,
        "exclusive_codes": [],
        "dk_codes": ["99"],
        "na_codes": [],
        "pipe_from": None,
        "anchor_labels": {"1": "전혀 아님", "5": "매우 그러함"},
        "raw_notes": "Grid 척도"
    }
}

q = SurveyQuestion.from_llm_dict(llm_response)
assert q.question_number == "Q5"
assert len(q.answer_options) == 2
# sub_items 필드 확인
if hasattr(q, 'sub_items'):
    assert q.sub_items == ["브랜드 인지도", "구매 의향", "재구매 의향"], \
        f"sub_items 불일치: {q.sub_items}"
    print("✅ Test 4a: sub_items 파싱 OK")
else:
    print("⚠️  Test 4a: sub_items 필드 없음 (task-p2t5 미완료)")

# programming_guide 필드 확인
if hasattr(q, 'programming_guide_raw') or hasattr(q, 'programming_guide'):
    print("✅ Test 4b: programming_guide 파싱 OK")
else:
    print("⚠️  Test 4b: programming_guide 필드 없음 (task-p2t5 미완료)")

# ── Test 5: from_llm_dict()가 구형 JSON (sub_items 없음) 처리 ──
old_response = {
    "question_number": "Q1",
    "question_text": "성별",
    "question_type": "SA",
    "answer_options": [{"code": "1", "label": "남"}],
    "skip_logic": [],
    "filter": None,
    "instructions": None,
}
q_old = SurveyQuestion.from_llm_dict(old_response)
assert q_old.question_number == "Q1"
if hasattr(q_old, 'sub_items'):
    assert q_old.sub_items == [], f"기본값이 [] 이어야 함: {q_old.sub_items}"
print("✅ Test 5: 구형 JSON 하위 호환성 OK")

# ── Test 6: import 체인 ──
from services.llm_extractor import extract_survey_questions
from models.survey import SurveyDocument
print("✅ Test 6: import 체인 OK")

print("\n🎉 ALL P2-T6 TESTS PASSED")
```

## 예상 소요 시간

약 1.5시간 (SYSTEM_PROMPT 수정 1시간 + from_llm_dict 수정 20분 + 테스트 10분)

## 중요 주의사항

SYSTEM_PROMPT는 매우 긴 문자열이다. 수정 시 반드시:
1. 전체 SYSTEM_PROMPT를 먼저 읽어서 기존 섹션 경계를 파악
2. `# RENDERING MARKERS` 섹션은 FORMAT 섹션과 ANSWER OPTIONS 섹션 사이에 삽입
3. OUTPUT 스키마 섹션은 SYSTEM_PROMPT의 끝 부분에 있음 — 그 섹션만 교체
4. SYSTEM_PROMPT 전체 재작성 금지 (기존 섹션들이 사라질 위험)
