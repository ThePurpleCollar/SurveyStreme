"""Smoke tests for deterministic default demographic banner seeding."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.survey import AnswerOption, Banner, BannerPoint, SurveyQuestion
from services.table_guide_service import (
    _build_default_demographic_banners,
    _merge_default_demographic_banners,
)


def _opts(*items):
    return [AnswerOption(code=str(code), label=label) for code, label in items]


questions = [
    SurveyQuestion(
        question_number="S1",
        question_text="What is your gender?",
        question_type="SA",
        answer_options=_opts((1, "Male"), (2, "Female")),
        role="demographics",
        variable_type="demographic",
    ),
    SurveyQuestion(
        question_number="S2",
        question_text="What is your age?",
        question_type="SA",
        answer_options=_opts(
            (1, "18-24 years old"),
            (2, "25-34 years old"),
            (3, "35-44 years old"),
            (4, "45-54 years old"),
            (5, "55-64 years old"),
            (6, "65 years old or older"),
        ),
        role="demographics",
        variable_type="demographic",
    ),
    SurveyQuestion(
        question_number="D3",
        question_text="What is your annual household income?",
        question_type="SA",
        answer_options=_opts(
            (1, "Less than $25,000"),
            (2, "$25,000-$49,999"),
            (3, "$50,000-$74,999"),
            (4, "$75,000-$99,999"),
            (5, "$100,000 or more"),
        ),
        role="demographics",
        variable_type="demographic",
    ),
    SurveyQuestion(
        question_number="Q1",
        question_text="How likely are you to purchase this product?",
        question_type="5PT SCALE",
        answer_options=_opts((1, "Definitely would"), (5, "Definitely would not")),
        role="intent_loyalty",
    ),
]


default_banners = _build_default_demographic_banners(questions, language="en")

assert [b.name for b in default_banners] == [
    "Gender",
    "Age Group",
    "Income Level",
], [b.name for b in default_banners]
assert all("기본 인구통계" in b.rationale for b in default_banners), [
    b.rationale for b in default_banners
]

gender = default_banners[0]
assert [p.condition for p in gender.points] == ["S1=1", "S1=2"]

age = default_banners[1]
assert len(age.points) == 3, [p.label for p in age.points]
assert age.points[0].condition == "S2=1,2"
assert age.points[-1].condition == "S2=5,6"

income = default_banners[2]
assert [p.label for p in income.points] == [
    "Lower Income",
    "Middle Income",
    "Higher Income",
]
assert income.points[0].condition == "D3=1,2"
assert income.points[-1].condition == "D3=5"


generated_duplicate = Banner(
    banner_id="A",
    name="Gender",
    category="Demographics",
    points=[
        BannerPoint(point_id="BP_A_1", label="Male", source_question="S1", condition="S1=1"),
        BannerPoint(point_id="BP_A_2", label="Female", source_question="S1", condition="S1=2"),
    ],
)
generated_strategic = Banner(
    banner_id="B",
    name="Purchase Intent",
    category="Intent",
    points=[
        BannerPoint(point_id="BP_B_1", label="High Intent", source_question="Q1", condition="Q1=1,2"),
        BannerPoint(point_id="BP_B_2", label="Low Intent", source_question="Q1", condition="Q1=4,5"),
    ],
)

merged = _merge_default_demographic_banners(
    default_banners,
    [generated_duplicate, generated_strategic],
)

assert [b.banner_id for b in merged] == ["A", "B", "C", "D"]
assert [b.name for b in merged] == ["Gender", "Age Group", "Income Level", "Purchase Intent"]
assert [p.point_id for p in merged[-1].points] == ["BP_D_1", "BP_D_2"]

source = Path("services/table_guide_service.py").read_text(encoding="utf-8")
assert "All `rationale` fields MUST be written in Korean" in source
assert "rationale-style fields must be written in Korean" in source

print("ALL DEFAULT DEMOGRAPHIC BANNER TESTS PASSED")
