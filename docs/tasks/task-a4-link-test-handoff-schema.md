# TASK-A4 — SurveyStreme to survey-link-tester Handoff Schema

## Goal

SurveyStreme에서 추출/검증한 설문 구조와 테스트 시나리오를 `survey-link-tester` agent가 바로 실행할 수 있는 A2A payload로 정의한다.

이 단계의 목표는 브라우저 자동화 자체 구현이 아니라, 두 프로젝트 사이의 계약을 명확히 만드는 것이다.

## Current State

- SurveyStreme can parse DOCX-derived survey structures into `SurveyQuestion`.
- Path Simulator generates test scenarios from executable skip conditions.
- Branch coverage is now verified from actual traced paths, not condition truth alone.
- `Branch Diagnostics` distinguishes covered, unparsed, unsatisfiable, source-not-reached, candidate-truncated, and not-triggered branches.
- `survey-link-tester` can run browser-based survey link tests separately.

## Proposed Payload

```json
{
  "schema_version": "survey_link_test_handoff.v1",
  "survey": {
    "source_file": "questionnaire.docx",
    "language": "ko|en|multi",
    "question_count": 0
  },
  "target": {
    "survey_url": "https://...",
    "locale": "eng",
    "mode": "validation"
  },
  "questions": [
    {
      "question_number": "Q1",
      "question_text": "...",
      "question_type": "SA|MA|OE|NUMERIC|MATRIX|GRID",
      "answer_options": [
        {"code": "1", "label": "..."}
      ],
      "skip_logic": [
        {"condition": "Q1=1", "target": "Q5"}
      ],
      "filter_condition": "..."
    }
  ],
  "test_scenarios": [
    {
      "scenario_id": 1,
      "priority": "REQUIRED",
      "answer_selections": {"Q1": "1"},
      "answer_labels": {"Q1": "Yes"},
      "expected_path": ["Q1", "Q5"],
      "verified_branches": ["Q1->Q5 (Q1=1)"],
      "intent": "Confirm Q1 skip to Q5"
    }
  ],
  "branch_diagnostics": [
    {
      "branch": "Q1->Q5 (Q1=1)",
      "status": "covered",
      "severity": "info",
      "detail": "..."
    }
  ],
  "agent_instructions": {
    "read_page_before_answering": true,
    "record_video": true,
    "capture_screenshots_on_error": true,
    "include_reasoning_summary": true,
    "do_not_submit_final_if_review_mode": false
  }
}
```

## Acceptance Criteria

- [ ] Schema file or typed model is added in SurveyStreme.
- [ ] Export function maps current `SimulationResult` and `SurveyQuestion` data to the payload.
- [ ] Payload preserves multilingual text without normalization loss.
- [ ] Open-ended and numeric questions can carry generated-answer guidance.
- [ ] Branch diagnostics are included so the tester knows which paths need manual attention.
- [ ] Smoke test validates the payload shape for:
  - normal skip scenario
  - open-ended/numeric scenario placeholder
  - branch diagnostic with `source_not_reached`

## Notes For Next Agent

Keep the schema conservative. The first contract should prioritize replayable validation:

- question ids
- expected path
- answer selections
- branch diagnostics
- recording and reasoning flags

Avoid adding browser-specific selectors in this task. Selectors belong in `survey-link-tester`, because they depend on the target platform and runtime page inspection.
