# Extraction Quality Workflow

Survey Stream의 파싱 품질은 실제 설문지별 Ground Truth와 비교해서 관리한다.

## Ground Truth 파일

Questionnaire Analyzer에서 세션 JSON을 저장한 뒤, 사람이 검수하여 정답 파일을 만든다.
형식은 기존 세션 JSON과 동일한 `SurveyDocument` JSON을 권장한다.

필수 검수 필드:

- `question_number`
- `question_text`
- `question_type`
- `answer_options`
- `skip_logic`
- `filter_condition`
- `instructions`
- `review_status`
- `review_notes`

검수 상태:

- `needs_review`: AI 추출 직후 기본값
- `verified`: 원본과 대조하여 확정
- `rejected`: 오추출 또는 삭제 대상

Questionnaire Analyzer의 스프레드시트에서 `ReviewStatus`와 `ReviewNotes`를 수정하면
세션 JSON과 Ground Truth 후보에 반영된다.

## 평가 실행

```bash
python scripts/evaluate_extraction.py \
  --ground-truth path/to/ground_truth.json \
  --extracted path/to/analyzer_session.json \
  --out output/evaluation_report.json
```

품질 게이트 예시:

```bash
python scripts/evaluate_extraction.py \
  --ground-truth path/to/ground_truth.json \
  --extracted path/to/analyzer_session.json \
  --fail-under-question-recall 0.98 \
  --fail-under-option-recall 0.95 \
  --fail-under-type-accuracy 0.95
```

## 권장 기준

- 문항 recall: 98% 이상
- 문항 precision: 98% 이상
- question_type accuracy: 95% 이상
- option code-label recall: 95% 이상
- skip/filter는 프로젝트별 편차가 커서 초기에는 리포트 기반 수동 리뷰로 운영

## 리뷰 순서

1. `missing_questions`를 먼저 확인한다. 문항 누락은 가장 치명적이다.
2. `option_mismatches`를 확인한다. 보기 코드/라벨 누락은 Table Guide와 DP에 직접 영향을 준다.
3. `type_mismatches`를 확인한다. SummaryType과 TableNumber 생성 품질에 영향을 준다.
4. `skip_mismatches`, `filter_mismatches`를 확인한다. Logic Checker 결과의 신뢰도와 직결된다.
