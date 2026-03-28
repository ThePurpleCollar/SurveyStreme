import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import ProgrammingGuide, SurveyQuestion, SurveyDocument

# Test 1: ProgrammingGuide 기본값
pg = ProgrammingGuide()
assert pg.is_empty() == True
print("Test 1: ProgrammingGuide 기본값 OK")

# Test 2: SurveyQuestion 기본값
q = SurveyQuestion(question_number="Q1", question_text="성별")
assert q.sub_items == []
assert q.programming_guide is None
print("Test 2: SurveyQuestion 기본값 OK")

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
print("Test 3: 직렬화 OK")

# Test 4: JSON 라운드트립
q3 = SurveyQuestion.from_json_dict(d)
assert q3.sub_items == ["브랜드 이미지", "제품 품질", "가격 경쟁력"]
assert q3.programming_guide.rotate_options == True
print("Test 4: JSON 라운드트립 OK")

# Test 5: 구 JSON 역직렬화 (sub_items 없음)
old = {"question_number": "Q1", "question_text": "성별", "question_type": "SA",
       "answer_options": [], "skip_logic": [], "filter_condition": None,
       "instructions": None, "summary_type": "", "table_number": "", "table_title": "",
       "grammar_checked": "", "net_recode": "", "sort_order": "", "sub_banner": "",
       "banner_ids": "", "special_instructions": "", "role": "", "variable_type": "",
       "analytical_value": "", "section": ""}
q_old = SurveyQuestion.from_json_dict(old)
assert q_old.sub_items == []
assert q_old.programming_guide is None
print("Test 5: 구 JSON 하위 호환 OK")

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
print("Test 6: from_llm_dict OK")

# Test 7: from_llm_dict without programming_guide
llm_dict2 = {
    "question_number": "Q1", "question_text": "성별",
    "answer_options": [], "skip_logic": [],
}
q_llm2 = SurveyQuestion.from_llm_dict(llm_dict2)
assert q_llm2.programming_guide is None
assert q_llm2.sub_items == []
print("Test 7: from_llm_dict without programming_guide OK")

# Test 8: DataFrame SubItems 컬럼
doc = SurveyDocument(filename="test.docx", questions=[q2])
df = doc.to_dataframe()
assert "SubItems" in df.columns
print("Test 8: DataFrame SubItems 컬럼 OK")

print("\nALL P2T5-SCHEMA TESTS PASSED")
