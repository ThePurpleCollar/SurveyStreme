import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_extractor import SYSTEM_PROMPT
from models.survey import SurveyQuestion

# Test 1: RENDERING MARKERS 섹션 존재
assert 'RENDERING MARKERS' in SYSTEM_PROMPT
assert 'SECTION:' in SYSTEM_PROMPT
assert 'multi_question' in SYSTEM_PROMPT
print("Test 1: RENDERING MARKERS 섹션 OK")

# Test 2: sub_items in OUTPUT 스키마
assert '"sub_items"' in SYSTEM_PROMPT
print("Test 2: sub_items in SYSTEM_PROMPT OK")

# Test 3: programming_guide in OUTPUT 스키마
assert '"programming_guide"' in SYSTEM_PROMPT
assert '"rotate_options"' in SYSTEM_PROMPT
assert '"exclusive_codes"' in SYSTEM_PROMPT
print("Test 3: programming_guide in SYSTEM_PROMPT OK")

# Test 4: from_llm_dict sub_items + programming_guide
llm_response = {
    "question_number": "Q5",
    "question_text": "브랜드 평가",
    "question_type": "5pt x 3",
    "answer_options": [{"code": "1", "label": "전혀 아님"}, {"code": "5", "label": "매우 그러함"}],
    "sub_items": ["브랜드 인지도", "구매 의향", "재구매 의향"],
    "skip_logic": [],
    "filter": None,
    "instructions": "ROTATE",
    "programming_guide": {
        "rotate_options": True,
        "exclusive_codes": [],
        "dk_codes": ["99"],
        "anchor_labels": {"1": "전혀 아님", "5": "매우 그러함"},
        "raw_notes": "Grid 척도"
    }
}
q = SurveyQuestion.from_llm_dict(llm_response)
assert q.sub_items == ["브랜드 인지도", "구매 의향", "재구매 의향"]
assert q.programming_guide is not None
assert q.programming_guide.rotate_options == True
print("Test 4: from_llm_dict sub_items + programming_guide OK")

# Test 5: 구형 JSON 하위 호환
old_response = {
    "question_number": "Q1", "question_text": "성별",
    "question_type": "SA",
    "answer_options": [{"code": "1", "label": "남"}],
    "skip_logic": [], "filter": None, "instructions": None,
}
q_old = SurveyQuestion.from_llm_dict(old_response)
assert q_old.sub_items == []
assert q_old.programming_guide is None
print("Test 5: 구형 JSON 하위 호환 OK")

# Test 6: import 체인
from services.llm_extractor import extract_survey_questions
from models.survey import SurveyDocument
print("Test 6: import 체인 OK")

print("\nALL P2-T6 TESTS PASSED")
