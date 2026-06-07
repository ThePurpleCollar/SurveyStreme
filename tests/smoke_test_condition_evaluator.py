import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import AnswerOption, SkipLogic, SurveyQuestion
from services.condition_evaluator import (
    ConditionClause,
    ConditionGroup,
    evaluate_condition,
    parse_condition_expression,
)
from services.path_simulator import simulate_paths


def _assert_parsed(condition: str):
    result = parse_condition_expression(condition)
    assert result.is_parsed, f"Expected parsed condition: {condition} / {result.warnings}"
    assert result.node is not None
    return result


result = _assert_parsed("Q1=1")
assert isinstance(result.node, ConditionClause)
assert result.references == {"Q1"}
assert result.evaluate({"Q1": "1"}) is True
assert result.evaluate({"Q1": "2"}) is False

result = _assert_parsed("Q1=1,2")
assert result.node.values == ("1", "2")
assert result.evaluate({"Q1": "2"}) is True
assert result.evaluate({"Q1": ["2", "3"]}) is True
assert result.evaluate({"Q1": ["3", "4"]}) is False

result = _assert_parsed("Q1!=99")
assert result.node.operator == "not_in"
assert result.evaluate({"Q1": "1"}) is True
assert result.evaluate({"Q1": "99"}) is False
assert result.evaluate({}) is False

result = _assert_parsed("Q1=1&Q2=3")
assert isinstance(result.node, ConditionGroup)
assert result.node.operator == "and"
assert result.references == {"Q1", "Q2"}
assert result.evaluate({"Q1": "1", "Q2": "3"}) is True
assert result.evaluate({"Q1": "1", "Q2": "2"}) is False

result = _assert_parsed("Q1=1 OR Q1=2")
assert isinstance(result.node, ConditionGroup)
assert result.node.operator == "or"
assert result.evaluate({"Q1": "2"}) is True
assert result.evaluate({"Q1": "3"}) is False

result = _assert_parsed("Q2=1~3")
assert result.node.values == ("1", "2", "3")
assert result.evaluate({"Q2": "2"}) is True
assert result.evaluate({"Q2": "4"}) is False

result = _assert_parsed("Q3=A1,B2")
assert result.node.values == ("A1", "B2")
assert result.evaluate({"Q3": "A1"}) is True

result = _assert_parsed("(Q1=1 OR Q1=2)&Q2!=99")
assert result.evaluate({"Q1": "2", "Q2": "1"}) is True
assert result.evaluate({"Q1": "2", "Q2": "99"}) is False

assert evaluate_condition("Q1=1 또는 Q1=2", {"Q1": "2"}) is True
assert evaluate_condition("Q1=1 및 Q2=3", {"Q1": "1", "Q2": "3"}) is True

unparsed = parse_condition_expression("ASK IF brand selected earlier")
assert unparsed.is_parsed is False
assert unparsed.evaluate({"Q1": "1"}) is False

unparsed = parse_condition_expression("Q1=1 AND")
assert unparsed.is_parsed is False

# Additive PR guard: existing path simulator behavior remains available.
questions = [
    SurveyQuestion(
        question_number="S1",
        question_text="Age",
        question_type="SA",
        answer_options=[AnswerOption("1", "Under 18"), AnswerOption("2", "18+")],
        skip_logic=[SkipLogic(condition="S1=1", target="END")],
    ),
    SurveyQuestion(
        question_number="Q1",
        question_text="Main question",
        question_type="SA",
        answer_options=[AnswerOption("1", "Yes"), AnswerOption("2", "No")],
    ),
]

simulation = simulate_paths(questions)
assert simulation.total_skip_rules == 1
assert simulation.branch_coverage_percent == 100.0
assert len(simulation.test_scenarios) == 1
assert simulation.test_scenarios[0].answer_selections == {"S1": "1"}

print("ALL CONDITION EVALUATOR TESTS PASSED")
