# Ground Truth Files

이 디렉터리는 사람이 검수한 Questionnaire Analyzer 정답셋을 보관한다.

권장 파일명:

```text
<source-docx-name>_ground_truth.json
```

생성 흐름:

1. Questionnaire Analyzer에서 DOCX를 추출한다.
2. 화면에서 문항/보기/유형/필터/스킵로직을 검수하고 수정한다.
3. 세션 JSON을 저장한다.
4. 아래 명령으로 Ground Truth 후보를 만든다.

```bash
python scripts/promote_ground_truth.py \
  --session output/my_session.json \
  --out ground_truth/my_questionnaire_ground_truth.json
```

5. 생성된 JSON을 사람이 다시 확인한 뒤 커밋한다.

평가:

```bash
python scripts/evaluate_extraction.py \
  --ground-truth ground_truth/my_questionnaire_ground_truth.json \
  --extracted output/my_new_session.json \
  --fail-under-question-recall 0.98 \
  --fail-under-option-recall 0.95 \
  --fail-under-type-accuracy 0.95
```
