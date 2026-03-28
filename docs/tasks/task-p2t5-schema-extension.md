# TASK-P2T5: SurveyQuestion 스키마 확장

## Status: 🔴 Not Started

## 선행 조건

**P1-T1 ~ P1-T4 완료 후 진행 권장** — 파서 개선 후 실제 추출 가능한 정보 기반 설계.

## 배경

현재 `SurveyQuestion`에서 누락된 3가지:

| 누락 | 현재 상태 | 문제 |
|------|---------|------|
| `sub_items` | 없음 | Grid 행 항목 수 파악 불가 → "5pt x ?" 타입 검증 불가 |
| `ProgrammingGuide` | `instructions: str`만 있음 | "보기 로테이션 / 단독응답 / Q3 파이핑" 이 뭉쳐짐 |
| `source_span` | 없음 | 원본 문서에서 어느 위치인지 추적 불가 |

## Goal

1. `ProgrammingGuide` dataclass 추가
2. `SurveyQuestion`에 `sub_items`, `programming_guide`, `source_span` 필드 추가
3. `to_json_dict()` / `from_json_dict()` / `from_llm_dict()` 업데이트 (하위 호환 유지)
4. `to_dataframe()` 업데이트 — `SubItems` 컬럼 추가

## Files to Modify

- `models/survey.py`
- `tests/smoke_test_p2t5_schema.py` (신규)

## Implementation Steps

### Step 1: ProgrammingGuide dataclass 추가

`AnswerOption` 정의 위에 추가:

```python
@dataclass
class ProgrammingGuide:
    """문항 프로그래밍 지시사항 — 구조화된 형태."""
    rotate_options: bool = False
    # 보기 순서 로테이션 여부 (ROTATE, 보기 로테이션, randomize)

    pipe_from: Optional[str] = None
    # 파이핑 소스 문항 번호 예: "Q3"

    exclusive_codes: List[str] = field(default_factory=list)
    # 단독응답 코드 예: ["99"]

    show_card: bool = False
    # SHOW CARD 제시 여부

    dk_na_codes: List[str] = field(default_factory=list)
    # 모름/해당없음 코드 예: ["98", "99"]

    rank_limit: Optional[int] = None
    # 순위 선택 개수 제한 (Top3 → 3)

    anchor_labels: dict = field(default_factory=dict)
    # 척도 앵커 예: {"1": "전혀 아님", "5": "매우 그러함"}

    constant_sum_total: Optional[int] = None
    # 합산 배분 총합 (예: 100)

    raw_notes: str = ""
    # 원본 PN 노트 전체 텍스트 보존

    def is_empty(self) -> bool:
        return (not self.rotate_options and self.pipe_from is None
                and not self.exclusive_codes and not self.show_card
                and not self.dk_na_codes and self.rank_limit is None
                and not self.anchor_labels and self.constant_sum_total is None
                and not self.raw_notes)

    def to_json_dict(self) -> dict:
        return {
            "rotate_options": self.rotate_options,
            "pipe_from": self.pipe_from,
            "exclusive_codes": self.exclusive_codes,
            "show_card": self.show_card,
            "dk_na_codes": self.dk_na_codes,
            "rank_limit": self.rank_limit,
            "anchor_labels": self.anchor_labels,
            "constant_sum_total": self.constant_sum_total,
            "raw_notes": self.raw_notes,
        }

    @classmethod
    def from_json_dict(cls, d: dict) -> 'ProgrammingGuide':
        return cls(
            rotate_options=d.get("rotate_options", False),
            pipe_from=d.get("pipe_from"),
            exclusive_codes=d.get("exclusive_codes", []),
            show_card=d.get("show_card", False),
            dk_na_codes=d.get("dk_na_codes", []),
            rank_limit=d.get("rank_limit"),
            anchor_labels=d.get("anchor_labels", {}),
            constant_sum_total=d.get("constant_sum_total"),
            raw_notes=d.get("raw_notes", ""),
        )
```

### Step 2: SurveyQuestion에 신규 필드 추가

기존 필드들 마지막에 추가:

```python
# Phase P: 파서 강화 신규 필드
sub_items: List[str] = field(default_factory=list)
# Grid/Matrix 배터리 행 항목 예: ["브랜드 이미지", "제품 품질"]

programming_guide: Optional[ProgrammingGuide] = None
# 구조화된 프로그래밍 지시사항

source_span: Optional[dict] = None
# 원본 문서 위치 예: {"chunk_index": 0, "para_index": 12}
```

### Step 3: to_json_dict() 업데이트

```python
# 기존 직렬화 코드에 추가:
d["sub_items"] = self.sub_items
d["programming_guide"] = (self.programming_guide.to_json_dict()
                           if self.programming_guide else None)
d["source_span"] = self.source_span
```

### Step 4: from_json_dict() 업데이트 (하위 호환)

```python
sub_items = d.get("sub_items", [])
pg_data = d.get("programming_guide")
programming_guide = (ProgrammingGuide.from_json_dict(pg_data)
                     if isinstance(pg_data, dict) else None)
source_span = d.get("source_span")
```

### Step 5: from_llm_dict() 업데이트

```python
sub_items = [str(s).strip() for s in d.get("sub_items", []) if s]

pg_raw = d.get("programming_guide")
if isinstance(pg_raw, dict):
    programming_guide = ProgrammingGuide(
        rotate_options=bool(pg_raw.get("rotate_options", False)),
        pipe_from=pg_raw.get("pipe_from"),
        exclusive_codes=pg_raw.get("exclusive_codes", []),
        dk_na_codes=pg_raw.get("dk_na_codes", []),
        rank_limit=pg_raw.get("rank_limit"),
        anchor_labels=pg_raw.get("anchor_labels", {}),
        constant_sum_total=pg_raw.get("constant_sum_total"),
        raw_notes=pg_raw.get("raw_notes", ""),
    )
else:
    programming_guide = None
```

### Step 6: to_dataframe() 업데이트

```python
# 기존 컬럼들 이후에 추가:
"SubItems": ", ".join(q.sub_items) if q.sub_items else "",
```

## Do NOT Change

- 기존 `SurveyQuestion` 필드들 (특히 `instructions`, `summary_type` 등)
- `Banner`, `BannerPoint`, `TableGuideDocument` dataclass
- `SurveyDocument.to_json_bytes()` / `from_json()` 구조

## Verification Checklist

- [ ] `python -m py_compile models/survey.py` 성공
- [ ] `python -c "from models.survey import ProgrammingGuide, SurveyQuestion; print('OK')"` 성공
- [ ] `SurveyQuestion("Q1","text").sub_items == []` 확인
- [ ] `SurveyQuestion("Q1","text").programming_guide is None` 확인
- [ ] 구 JSON (sub_items 없음) 역직렬화 성공 확인
- [ ] `python -c "from app import *; print('import OK')"` 성공
- [ ] Smoke Test 전체 통과

## Smoke Test Script

```python
# tests/smoke_test_p2t5_schema.py
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import ProgrammingGuide, SurveyQuestion, SurveyDocument

# Test 1: ProgrammingGuide 기본값
pg = ProgrammingGuide()
assert pg.is_empty() == True
print("✅ Test 1: ProgrammingGuide 기본값 OK")

# Test 2: SurveyQuestion 기본값
q = SurveyQuestion(question_number="Q1", question_text="성별")
assert q.sub_items == []
assert q.programming_guide is None
print("✅ Test 2: SurveyQuestion 기본값 OK")

# Test 3: sub_items + programming_guide 직렬화
q2 = SurveyQuestion(
    question_number="Q5", question_text="브랜드 평가",
    question_type="5pt x 3",
    sub_items=["브랜드 이미지", "제품 품질", "가격 경쟁력"],
    programming_guide=ProgrammingGuide(rotate_options=True, dk_na_codes=["99"])
)
d = q2.to_json_dict()
assert d["sub_items"] == ["브랜드 이미지", "제품 품질", "가격 경쟁력"]
assert d["programming_guide"]["rotate_options"] == True
print("✅ Test 3: 직렬화 OK")

# Test 4: JSON 라운드트립
q3 = SurveyQuestion.from_json_dict(d)
assert q3.sub_items == ["브랜드 이미지", "제품 품질", "가격 경쟁력"]
assert q3.programming_guide.rotate_options == True
print("✅ Test 4: JSON 라운드트립 OK")

# Test 5: 구 JSON 역직렬화 (sub_items 없음)
old = {"question_number": "Q1", "question_text": "성별", "question_type": "SA",
       "answer_options": [], "skip_logic": [], "filter_condition": None,
       "instructions": None, "summary_type": "", "table_number": "", "table_title": "",
       "grammar_checked": "", "net_recode": "", "sort_order": "", "sub_banner": "",
       "banner_ids": "", "special_instructions": "", "role": "", "variable_type": "",
       "analytical_value": "", "section": ""}
q_old = SurveyQuestion.from_json_dict(old)
assert q_old.sub_items == []
print("✅ Test 5: 구 JSON 하위 호환 OK")

# Test 6: from_llm_dict
llm_dict = {
    "question_number": "Q5", "question_text": "브랜드 평가",
    "question_type": "5pt x 3",
    "answer_options": [{"code": "1", "label": "전혀 아님"}],
    "sub_items": ["브랜드 이미지", "제품 품질"],
    "skip_logic": [], "filter": None, "instructions": "ROTATE",
    "programming_guide": {"rotate_options": True, "dk_na_codes": ["99"]}
}
q_llm = SurveyQuestion.from_llm_dict(llm_dict)
assert q_llm.sub_items == ["브랜드 이미지", "제품 품질"]
print("✅ Test 6: from_llm_dict OK")

# Test 7: DataFrame SubItems 컬럼
doc = SurveyDocument(filename="test.docx", questions=[q2])
df = doc.to_dataframe()
assert "SubItems" in df.columns
print("✅ Test 7: DataFrame SubItems 컬럼 OK")

print("\n🎉 ALL P2T5-SCHEMA TESTS PASSED")
```

## 예상 소요 시간

약 3시간 (모델 설계 1h + 구현 1.5h + 테스트 0.5h)
