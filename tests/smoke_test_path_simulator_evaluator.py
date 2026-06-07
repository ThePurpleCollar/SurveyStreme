import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import AnswerOption, SkipLogic, SurveyQuestion
from services.path_simulator import parse_condition, simulate_paths, trace_path
from services.skip_logic_service import build_skip_logic_graph


cross_question_questions = [
    SurveyQuestion(
        question_number="Q1",
        question_text="Pick a segment",
        question_type="SA",
        answer_options=[AnswerOption("1", "Segment A"), AnswerOption("2", "Segment B")],
    ),
    SurveyQuestion(
        question_number="Q2",
        question_text="Pick a product",
        question_type="SA",
        answer_options=[AnswerOption("1", "Product A"), AnswerOption("2", "Product B")],
        skip_logic=[SkipLogic(condition="Q1=1&Q2=2", target="Q4")],
    ),
    SurveyQuestion(
        question_number="Q3",
        question_text="Skipped for segment A product B",
        question_type="SA",
    ),
    SurveyQuestion(
        question_number="Q4",
        question_text="Final question",
        question_type="SA",
    ),
]

cross_graph = build_skip_logic_graph(cross_question_questions)
cross_path = trace_path(cross_question_questions, cross_graph, {"Q1": "1", "Q2": "2"})
assert cross_path.question_numbers == ["Q1", "Q2", "Q4"]
assert cross_path.steps[1].skip_triggered == "Q4"

cross_result = simulate_paths(cross_question_questions)
assert cross_result.unparsed_conditions == []
assert cross_result.branch_coverage_percent == 100.0
assert cross_result.test_scenarios[0].answer_selections == {"Q1": "1", "Q2": "2"}
assert cross_result.test_scenarios[0].expected_path == ["Q1", "Q2", "Q4"]


not_in_questions = [
    SurveyQuestion(
        question_number="Q1",
        question_text="Eligible?",
        question_type="SA",
        answer_options=[AnswerOption("1", "Yes"), AnswerOption("99", "None")],
        skip_logic=[SkipLogic(condition="Q1!=99", target="END")],
    ),
    SurveyQuestion(question_number="Q2", question_text="Follow-up", question_type="SA"),
]

not_in_graph = build_skip_logic_graph(not_in_questions)
terminating_path = trace_path(not_in_questions, not_in_graph, {"Q1": "1"})
assert terminating_path.question_numbers == ["Q1"]
assert terminating_path.steps[0].skip_triggered == "END"

continuing_path = trace_path(not_in_questions, not_in_graph, {"Q1": "99"})
assert continuing_path.question_numbers == ["Q1", "Q2"]

not_in_result = simulate_paths(not_in_questions)
assert not_in_result.test_scenarios[0].answer_selections == {"Q1": "1"}
assert not_in_result.test_scenarios[0].expected_path == ["Q1"]


shorthand = parse_condition("Q1=1 또는 2 응답자")
assert shorthand.is_parsed is True
assert shorthand.question_number == "Q1"
assert shorthand.answer_codes == ["1", "2"]


long_code = "123456789012345678901234567890"
long_condition_questions = [
    SurveyQuestion(
        question_number="Q1",
        question_text="Long-code screening",
        question_type="SA",
        answer_options=[AnswerOption(long_code, "Long code")],
        skip_logic=[SkipLogic(condition=f"Q1={long_code}", target="END")],
    ),
    SurveyQuestion(question_number="Q2", question_text="Should be skipped", question_type="SA"),
]

long_graph = build_skip_logic_graph(long_condition_questions)
skip_edge = [edge for edge in long_graph.edges if edge.edge_type == "skip"][0]
assert skip_edge.label.endswith("...")
assert skip_edge.original_condition == f"Q1={long_code}"

long_path = trace_path(long_condition_questions, long_graph, {"Q1": long_code})
assert long_path.question_numbers == ["Q1"]
assert long_path.steps[0].skip_triggered == "END"


forward_reference_questions = [
    SurveyQuestion(
        question_number="Q1",
        question_text="Should not inspect future answers",
        question_type="SA",
        skip_logic=[SkipLogic(condition="Q2=1", target="END")],
    ),
    SurveyQuestion(
        question_number="Q2",
        question_text="Future answer",
        question_type="SA",
        answer_options=[AnswerOption("1", "Yes")],
    ),
]

forward_graph = build_skip_logic_graph(forward_reference_questions)
forward_path = trace_path(forward_reference_questions, forward_graph, {"Q2": "1"})
assert forward_path.question_numbers == ["Q1", "Q2"]
assert forward_path.steps[0].skip_triggered is None

print("ALL PATH SIMULATOR EVALUATOR TESTS PASSED")
