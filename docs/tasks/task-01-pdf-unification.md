# TASK-01: PDF 파이프라인 SurveyDocument 출력 통일

## Status: 🟢 Complete

## Problem
현재 PDF 업로드 시 `_process_pdf()` 함수가:
1. `extract_question_data()` → 튜플 리스트 `(qn, text, type)` 반환
2. `pd.DataFrame`으로 변환 후 `st.data_editor`로 바로 표시
3. **`SurveyDocument` 객체를 생성하지 않음** → `st.session_state['survey_document']` 미설정
4. 결과: Table Guide Builder, Quality Checker 등 모든 후속 기능 사용 불가

DOCX 경로는 `SurveyDocument` 생성 → 세션 저장 → 모든 후속 기능 정상 동작.

## Goal
PDF 처리 후에도 DOCX와 동일한 `SurveyDocument` 객체가 생성되어 세션에 저장되도록 한다.

## Files to Modify
- `pages/doc_analyzer.py` — `_process_pdf()` 함수 리팩터링
- `models/survey.py` — 필요 시 `SurveyQuestion.from_pdf_tuple()` 팩토리 추가

## Implementation Steps
1. `_process_pdf()` 내에서 `extract_question_data()` 결과를 `SurveyQuestion` 객체 리스트로 변환
2. `SurveyDocument(filename=..., questions=...)` 생성
3. DOCX와 동일한 `_apply_postprocessing(survey_doc)` 호출
4. `st.session_state['survey_document'] = survey_doc` 저장
5. `st.session_state['edited_df'] = survey_doc.to_dataframe()` 저장
6. 결과 표시를 `_display_docx_results(survey_doc)` 재사용 (또는 공통 함수로 리네임)
7. 세션 저장 버튼 추가 (DOCX와 동일)

## Do NOT Change
- `services/postprocessor.py`의 `extract_question_data()` 함수 자체는 유지 (PDF 정규식은 TASK-03에서 개선)
- DOCX 처리 경로 (`_process_docx`)는 건드리지 않음

## Verification Checklist
- [ ] PDF 업로드 후 `st.session_state['survey_document']`가 `SurveyDocument` 타입인지 확인
- [ ] PDF 업로드 후 Table Guide Builder 페이지로 이동 시 잠금 해제되는지 확인
- [ ] PDF 업로드 후 Quality Checker 페이지에서 문항 목록이 표시되는지 확인
- [ ] 기존 DOCX 업로드 경로가 영향받지 않는지 확인
- [ ] `python -c "from pages.doc_analyzer import page_document_processing; print('OK')"` 성공
- [ ] 세션 저장(.json) 후 재로드 시 정상 동작 확인

## Smoke Test Script
```python
# tests/smoke_test_pdf.py
from models.survey import SurveyQuestion, SurveyDocument

# PDF 추출 결과 시뮬레이션
mock_data = [
    ("Q1", "What is your gender?", "SA"),
    ("Q2", "What is your age?", "SA"),
    ("Q3", "How satisfied are you?", "5pt"),
]

questions = []
for qn, text, qtype in mock_data:
    q = SurveyQuestion(question_number=qn, question_text=text, question_type=qtype)
    questions.append(q)

doc = SurveyDocument(filename="test.pdf", questions=questions)
assert len(doc.questions) == 3
assert doc.questions[0].question_number == "Q1"

# to_dataframe 확인
df = doc.to_dataframe()
assert "QuestionNumber" in df.columns
assert len(df) == 3

# JSON 직렬화/역직렬화
import json
json_bytes = doc.to_json_bytes()
restored = SurveyDocument.from_json(json.loads(json_bytes))
assert len(restored.questions) == 3

print("✅ All smoke tests passed!")
```
