import os
import re
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages.table_guide as table_guide
from services import table_title_service


original_call = table_guide.call_llm_json
original_workers = table_guide.TITLE_BATCH_WORKERS


def _mock_call_llm_json(system_prompt, user_prompt, model):
    time.sleep(0.2)
    qns = re.findall(r"\[(Q\d+)\]", user_prompt)
    return {
        "results": [
            {
                "question_number": qn,
                "title": f"Title {qn}",
                "reasoning": "mock",
            }
            for qn in qns
        ]
    }


try:
    table_guide.call_llm_json = _mock_call_llm_json
    table_guide.TITLE_BATCH_WORKERS = 3

    rows = [
        {
            "QuestionNumber": f"Q{i}",
            "TableNumber": f"T{i:03d}",
            "QuestionText": f"Question {i}",
            "QuestionType": "SA",
            "SummaryType": "%",
            "AnswerOptions": "1. Yes | 2. No",
            "Filter": "",
        }
        for i in range(1, 81)
    ]
    events = []
    t0 = time.perf_counter()
    results = table_guide._run_title_generation(
        pd.DataFrame(rows),
        language="en",
        progress_callback=lambda event, data: events.append((event, data)),
    )
    elapsed = time.perf_counter() - t0
finally:
    table_guide.call_llm_json = original_call
    table_guide.TITLE_BATCH_WORKERS = original_workers


assert len(results) == 80
assert all(not r["error"] for r in results)
assert sum(1 for event, _ in events if event == "run_start") == 1
assert sum(1 for event, _ in events if event == "batch_done") == 4
run_start = next(data for event, data in events if event == "run_start")
assert run_start["total_batches"] == 4
assert run_start["workers"] == 3

# Four 0.2s batches would take roughly 0.8s sequentially. With three workers it
# should complete in two waves while preserving the same batch-level outputs.
assert elapsed < 0.65, f"title generation did not run batches in parallel: {elapsed:.3f}s"

prompt = table_guide._build_batch_prompt(
    [
        {
            "qn": "QKBF",
            "source_variable": "KBF",
            "text": "How important are the following factors when choosing your next TV?",
            "qtype": "MA",
            "options": "1. Price | 2. Picture quality",
            "filter": "",
            "instructions": "ROTATE",
            "skip_logic": "",
            "role": "evaluation",
            "variable_type": "attitudinal",
            "analytical_value": "high",
            "summary_types": ["%"],
            "table_numbers": ["T001"],
            "row_count": 1,
        }
    ],
    survey_context="## Study Brief\nStudy Type: U&A\nStudy Objective: TV purchase behavior",
    language="en",
)
assert "Key Buying Factors" in prompt
assert "Role: evaluation" in prompt
assert "VariableType: attitudinal" in prompt
assert "Instructions: ROTATE" in prompt

original_call = table_guide.call_llm_json
try:
    table_guide.call_llm_json = lambda *args, **kwargs: {
        "results": [
            {
                "question_number": "Q1",
                "title": "Important Things",
                "reasoning": "literal wording",
            }
        ]
    }
    kbf_rows = [
        {
            "QuestionNumber": "Q1",
            "TableNumber": "T001",
            "QuestionText": "How important are the following factors when choosing your next TV?",
            "QuestionType": "MA",
            "SummaryType": "%",
            "AnswerOptions": "1. Price | 2. Picture quality | 3. Smart features",
            "Filter": "",
        }
    ]
    kbf_results = table_guide._run_title_generation(
        pd.DataFrame(kbf_rows),
        language="en",
        progress_callback=lambda event, data: None,
        survey_context="## Study Brief\nStudy Type: U&A",
    )
finally:
    table_guide.call_llm_json = original_call

assert kbf_results[0]["base_title"] == "Key Buying Factors"

assert table_title_service.polish_generated_title("Respondent Age Distribution", "en") == "Age Group"
assert table_title_service.polish_generated_title("Age Group", "en") == "Age Group"
assert table_title_service.polish_generated_title("Income Level", "en") == "Income Level"
assert table_title_service.polish_generated_title("TV Choice Factors", "en") == "Key Buying Factors"
assert table_title_service.polish_generated_title("Purchase Important Factors", "en") == "Key Buying Factors"
assert table_title_service.polish_generated_title("Future Purchase Intention", "en") == "Purchase Intent"
assert table_title_service.polish_generated_title("Brand Consideration Set", "en") == "Brand Consideration"
assert table_title_service.polish_generated_title("Brand Imagery", "en") == "Brand Image"
assert table_title_service.polish_generated_title("Current TV Brand", "en") == "Main Brand"
assert table_title_service.polish_generated_title("Where Purchased", "en") == "Purchase Channel"

assert table_title_service.polish_generated_title("구매 중요 요소", "ko") == "핵심 구매 요인"
assert table_title_service.polish_generated_title("향후 구매 가능성", "ko") == "구매 의향"
assert table_title_service.polish_generated_title("브랜드 인지 여부", "ko") == "보조 인지 브랜드"
assert table_title_service.polish_generated_title("현재 보유 브랜드", "ko") == "주 사용 브랜드"
assert table_title_service.polish_generated_title("브랜드 고려 여부", "ko") == "브랜드 고려"
assert table_title_service.polish_generated_title("브랜드 연상", "ko") == "브랜드 이미지"
assert table_title_service.polish_generated_title("구매처", "ko") == "구매 채널"

assert table_title_service.normalize_title_by_intent(
    "literal title",
    {
        "source_variable": "B1",
        "text": "Which of the following brands are you aware of?",
        "options": "Samsung | LG | TCL",
        "qtype": "MA",
    },
    "en",
) == "Aided Brand Awareness"

print("ALL TITLE GENERATION PARALLEL TESTS PASSED")
