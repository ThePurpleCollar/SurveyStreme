import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.spss_condition_service import (
    condition_code_labels,
    condition_source_variables,
    condition_to_spss,
    parse_condition_parts,
)
from services import table_guide_service
from ui import download


parts, warnings = parse_condition_parts("Q1=1,2&Q2='A' OR 'B'")
assert parts == [("Q1", ["1", "2"]), ("Q2", ["A", "B"])]
assert warnings == []

parts, warnings = parse_condition_parts("Q1!=1")
assert parts == [("Q1!", ["1"])]
assert any("Negative condition" in warning for warning in warnings)

source_vars = {"Q1": "AGE", "Q2": "SEG"}
assert condition_to_spss("Q1=1,2&Q2=A", source_vars) == "(AGE = 1 OR AGE = 2) AND SEG = 'A'"
assert condition_source_variables("Q1=1,2&Q2=A&Q1=3", source_vars) == "AGE&SEG"

labels = {"Q1": {"1": "Male", "2": "Female"}, "Q2": {"A": "Segment A"}}
assert condition_code_labels("Q1=1,2&Q2=A", labels) == "Q1 1=Male | Q1 2=Female | Q2 A=Segment A"

# UI and Table Guide service must share the same implementation to avoid
# export/validation drift.
assert table_guide_service._parse_condition_parts is parse_condition_parts
assert download._condition_to_spss is condition_to_spss

print("ALL SPSS CONDITION SERVICE TESTS PASSED")
