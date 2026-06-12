"""Tests for the cohort definition builder.

Validates that simplified specs produce valid CIRCE JSON that passes
validation and can be compiled to SQL.
"""

import json
from pathlib import Path

from circe_compiler.builder.cohort_builder import (
    build_cohort_definition_from_spec,
    CohortDefinitionSpec,
)
from circe_compiler.models.cohort_expression import CohortExpression
from circe_compiler.mcp.server import compile_cohort, _rewrite_as_cte_select


FIXTURE_DIR = Path(__file__).parent / "fixtures"
BUILDER_SPECS_DIR = FIXTURE_DIR / "builder_specs"


def load_builder_spec(name: str) -> dict:
    with open(BUILDER_SPECS_DIR / name) as f:
        return json.load(f)


# ─── Simple construction tests ────────────────────────────────────────────


def test_build_simple_condition():
    """Minimal: 1 concept set + primary criteria → valid CIRCE JSON."""
    spec = load_builder_spec("simple_condition.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True
    assert result["validation"]["is_valid"] is True

    cohort = result["cohort_json"]
    assert len(cohort["ConceptSets"]) == 1
    assert cohort["ConceptSets"][0]["name"] == "Type 2 Diabetes"
    assert cohort["ConceptSets"][0]["id"] == 0
    assert cohort["ConceptSets"][0]["expression"]["items"][0]["concept"]["CONCEPT_ID"] == 201826
    assert cohort["ConceptSets"][0]["expression"]["items"][0]["includeDescendants"] is True

    # Primary criteria
    pc = cohort["PrimaryCriteria"]
    assert len(pc["CriteriaList"]) == 1
    assert "ConditionOccurrence" in pc["CriteriaList"][0]
    assert pc["CriteriaList"][0]["ConditionOccurrence"]["CodesetId"] == 0
    assert pc["ObservationWindow"]["PriorDays"] == 365

    # Concept set mapping
    assert result["concept_set_mapping"] == {"Type 2 Diabetes": 0}


def test_build_with_inclusion_rule():
    """Temporal window Coeff mapping, Occurrence type mapping."""
    spec = load_builder_spec("with_inclusion.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    assert len(cohort["InclusionRules"]) == 1

    rule = cohort["InclusionRules"][0]
    assert rule["name"] == "Prior Metformin"

    # Check the correlated criteria
    cc = rule["expression"]["CriteriaList"][0]
    assert "DrugExposure" in cc["Criteria"]
    assert cc["Criteria"]["DrugExposure"]["CodesetId"] == 1

    # Temporal window: 365 days before to 0 days before
    window = cc["StartWindow"]
    assert window["Start"]["Days"] == 365
    assert window["Start"]["Coeff"] == -1
    assert window["End"]["Days"] == 0
    assert window["End"]["Coeff"] == -1

    # Occurrence: at_least 1 → Type=2, Count=1
    occ = cc["Occurrence"]
    assert occ["Type"] == 2
    assert occ["Count"] == 1


def test_build_with_exclusion():
    """Exclusion → InclusionRule with Occurrence(Type=0, Count=0)."""
    spec = load_builder_spec("with_exclusion.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    assert len(cohort["InclusionRules"]) == 1

    rule = cohort["InclusionRules"][0]
    assert rule["name"] == "No Heart Failure"

    cc = rule["expression"]["CriteriaList"][0]
    assert "ConditionOccurrence" in cc["Criteria"]
    assert cc["Criteria"]["ConditionOccurrence"]["CodesetId"] == 1

    # Exclusion: exactly 0 → Type=0, Count=0
    occ = cc["Occurrence"]
    assert occ["Type"] == 0
    assert occ["Count"] == 0

    # Default temporal: all time prior (99999 days before)
    window = cc["StartWindow"]
    assert window["Start"]["Days"] == 99999
    assert window["Start"]["Coeff"] == -1


def test_build_with_demographics():
    """Age range → NumericRange, gender → Concept list."""
    spec = load_builder_spec("with_demographics.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    rule = cohort["InclusionRules"][0]

    # DemographicCriteriaList should have one entry
    demo_list = rule["expression"]["DemographicCriteriaList"]
    assert len(demo_list) == 1

    demo = demo_list[0]
    # Age: between 18 and 65
    assert demo["Age"]["Value"] == 18
    assert demo["Age"]["Extent"] == 65
    assert demo["Age"]["Op"] == "bt"

    # Gender: Male (8507) and Female (8532)
    genders = demo["Gender"]
    assert len(genders) == 2
    gender_ids = {g["CONCEPT_ID"] for g in genders}
    assert gender_ids == {8507, 8532}


def test_build_end_strategy_date_offset():
    """DateOffset.Offset mapping."""
    spec = load_builder_spec("t2dm_full.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    assert cohort["EndStrategy"] is not None
    assert cohort["EndStrategy"]["DateOffset"]["DateField"] == "StartDate"
    assert cohort["EndStrategy"]["DateOffset"]["Offset"] == 365


def test_build_round_trip_t2dm():
    """Full T2DM spec → structural equivalence with fixture."""
    spec = load_builder_spec("t2dm_full.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]

    # Structural checks matching t2dm_metformin_no_hf.json fixture
    assert len(cohort["ConceptSets"]) == 3
    assert cohort["ConceptSets"][0]["name"] == "Type 2 Diabetes"
    assert cohort["ConceptSets"][1]["name"] == "Metformin"
    assert cohort["ConceptSets"][2]["name"] == "Heart Failure"

    # Primary criteria: ConditionOccurrence CodesetId=0
    pc = cohort["PrimaryCriteria"]["CriteriaList"][0]
    assert pc["ConditionOccurrence"]["CodesetId"] == 0

    # 2 inclusion rules (1 inclusion + 1 exclusion-as-inclusion)
    assert len(cohort["InclusionRules"]) == 2
    assert cohort["InclusionRules"][0]["name"] == "Has prior metformin exposure"
    assert cohort["InclusionRules"][1]["name"] == "No prior heart failure"

    # Metformin rule: DrugExposure CodesetId=1, at_least 1
    met_cc = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]
    assert met_cc["Criteria"]["DrugExposure"]["CodesetId"] == 1
    assert met_cc["Occurrence"]["Type"] == 2
    assert met_cc["Occurrence"]["Count"] == 1

    # Heart failure exclusion: ConditionOccurrence CodesetId=2, exactly 0
    hf_cc = cohort["InclusionRules"][1]["expression"]["CriteriaList"][0]
    assert hf_cc["Criteria"]["ConditionOccurrence"]["CodesetId"] == 2
    assert hf_cc["Occurrence"]["Type"] == 0
    assert hf_cc["Occurrence"]["Count"] == 0

    # End strategy
    assert cohort["EndStrategy"]["DateOffset"]["Offset"] == 365

    # Can parse back into CohortExpression
    expr = CohortExpression.model_validate(cohort)
    assert len(expr.ConceptSets) == 3


def test_build_output_compiles():
    """Build → pass to compile_cohort() → success=True."""
    spec = load_builder_spec("t2dm_full.json")
    build_result = build_cohort_definition_from_spec(spec)

    assert build_result["success"] is True

    compile_result = compile_cohort(
        build_result["cohort_json"],
        dialect="postgres",
        cdm_schema="cdm",
        results_schema="results",
    )

    assert compile_result["success"] is True
    assert compile_result["sql"]  # Non-empty SQL
    assert "condition_occurrence" in compile_result["sql"].lower()
    assert "drug_exposure" in compile_result["sql"].lower()


def test_build_invalid_name_ref():
    """Bad concept_set reference → structured error, not exception."""
    spec = load_builder_spec("invalid_name_ref.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is False
    assert "error" in result
    assert "Nonexistent Set" in result["error"]
    assert "not found" in result["error"]


def test_concept_minimal_metadata():
    """Only concept_id → valid CIRCE JSON (other fields optional)."""
    spec = {
        "concept_sets": [
            {
                "name": "Minimal",
                "domain": "Condition",
                "concepts": [{"concept_id": 12345}],
            }
        ],
        "primary_criteria": {
            "concept_set": "Minimal",
            "first_occurrence": True,
        },
    }
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True
    concept = result["cohort_json"]["ConceptSets"][0]["expression"]["items"][0]["concept"]
    assert concept["CONCEPT_ID"] == 12345


def test_build_from_json_string():
    """Accepts a JSON string as input."""
    spec_dict = load_builder_spec("simple_condition.json")
    spec_str = json.dumps(spec_dict)

    result = build_cohort_definition_from_spec(spec_str)
    assert result["success"] is True
    assert len(result["cohort_json"]["ConceptSets"]) == 1


# ─── Attribute tests ──────────────────────────────────────────────────────


def test_build_measurement_with_value():
    """HbA1c >= 9.0 → ValueAsNumber on Measurement criteria."""
    spec = load_builder_spec("measurement_value.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    rule = cohort["InclusionRules"][0]
    criteria = rule["expression"]["CriteriaList"][0]["Criteria"]

    assert "Measurement" in criteria
    meas = criteria["Measurement"]
    assert meas["CodesetId"] == 1
    assert meas["ValueAsNumber"]["Op"] == "gte"
    assert meas["ValueAsNumber"]["Value"] == 9.0


def test_build_measurement_with_unit():
    """HbA1c >= 9.0 with unit=percent → ValueAsNumber + Unit."""
    spec = load_builder_spec("measurement_unit.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    meas = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]

    assert meas["ValueAsNumber"]["Op"] == "gte"
    assert meas["ValueAsNumber"]["Value"] == 9.0

    assert len(meas["Unit"]) == 1
    assert meas["Unit"][0]["CONCEPT_ID"] == 8713


def test_build_measurement_between():
    """HbA1c bt(7.5, 9.0) → Op='bt', Value and Extent set."""
    spec = load_builder_spec("measurement_between.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    meas = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]

    assert meas["ValueAsNumber"]["Op"] == "bt"
    assert meas["ValueAsNumber"]["Value"] == 7.5
    assert meas["ValueAsNumber"]["Extent"] == 9.0


def test_build_drug_days_supply():
    """Metformin DaysSupply >= 90 → DaysSupply on DrugExposure."""
    spec = load_builder_spec("drug_days_supply.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    drug = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["DrugExposure"]

    assert drug["CodesetId"] == 1
    assert drug["DaysSupply"]["Op"] == "gte"
    assert drug["DaysSupply"]["Value"] == 90


def test_build_drug_multiple_attrs():
    """DaysSupply + Refills on same criteria → both fields set."""
    spec = load_builder_spec("drug_multiple_attrs.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    drug = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["DrugExposure"]

    assert drug["DaysSupply"]["Op"] == "gte"
    assert drug["DaysSupply"]["Value"] == 30
    assert drug["Refills"]["Op"] == "gte"
    assert drug["Refills"]["Value"] == 2


def test_build_with_visit_type_attr():
    """Condition constrained to inpatient visit → VisitType set."""
    spec = load_builder_spec("with_visit_type.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    cond = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["ConditionOccurrence"]

    assert len(cond["VisitType"]) == 1
    assert cond["VisitType"][0]["CONCEPT_ID"] == 9201


def test_build_with_age_per_criteria():
    """Age on Measurement criteria (not demographics) → Age NumericRange."""
    spec = load_builder_spec("with_age_attr.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    meas = cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]

    assert meas["ValueAsNumber"]["Op"] == "gte"
    assert meas["ValueAsNumber"]["Value"] == 9.0
    assert meas["Age"]["Op"] == "gte"
    assert meas["Age"]["Value"] == 18


def test_build_invalid_attr_for_domain():
    """ValueAsNumber on Condition → validation error."""
    spec = {
        "concept_sets": [
            {
                "name": "T2DM",
                "domain": "Condition",
                "concepts": [{"concept_id": 201826, "include_descendants": True}],
            }
        ],
        "primary_criteria": {"concept_set": "T2DM", "first_occurrence": True},
        "inclusion_rules": [
            {
                "name": "Bad rule",
                "concept_set": "T2DM",
                "attributes": [
                    {"type": "value_as_number", "op": "gte", "value": 9.0}
                ],
            }
        ],
    }
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is False
    assert "value_as_number" in result["error"]
    assert "Condition" in result["error"]


def test_build_attributes_backward_compat():
    """All existing fixtures still pass with attributes=[] default."""
    for fixture in ["simple_condition.json", "with_inclusion.json",
                     "with_exclusion.json", "with_demographics.json",
                     "t2dm_full.json"]:
        spec = load_builder_spec(fixture)
        result = build_cohort_definition_from_spec(spec)
        assert result["success"] is True, f"Backward compat failed for {fixture}"


def test_build_attributes_compile_round_trip():
    """Build with attrs → compile → SQL includes domain-specific attribute filters."""
    spec = load_builder_spec("measurement_value.json")
    build_result = build_cohort_definition_from_spec(spec)

    assert build_result["success"] is True

    # Verify CIRCE JSON has the attribute set
    meas = build_result["cohort_json"]["InclusionRules"][0]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]
    assert meas["ValueAsNumber"]["Op"] == "gte"

    compile_result = compile_cohort(
        build_result["cohort_json"],
        dialect="postgres",
        cdm_schema="cdm",
        results_schema="results",
    )

    assert compile_result["success"] is True
    sql_lower = compile_result["sql"].lower()
    assert "measurement" in sql_lower
    assert "value_as_number" in sql_lower


def test_build_primary_criteria_with_attrs():
    """Attributes on primary criteria entry event."""
    spec = load_builder_spec("primary_with_attrs.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    pc = cohort["PrimaryCriteria"]["CriteriaList"][0]

    assert "Measurement" in pc
    meas = pc["Measurement"]
    assert meas["ValueAsNumber"]["Op"] == "gte"
    assert meas["ValueAsNumber"]["Value"] == 6.5
    assert len(meas["Unit"]) == 1
    assert meas["Unit"][0]["CONCEPT_ID"] == 8713


def test_build_exclusion_with_attrs():
    """Attributes on exclusion criteria + Occurrence exactly=0."""
    spec = load_builder_spec("exclusion_with_attrs.json")
    result = build_cohort_definition_from_spec(spec)

    assert result["success"] is True

    cohort = result["cohort_json"]
    assert len(cohort["InclusionRules"]) == 1

    rule = cohort["InclusionRules"][0]
    assert rule["name"] == "No high-dose Metformin"

    cc = rule["expression"]["CriteriaList"][0]
    drug = cc["Criteria"]["DrugExposure"]
    assert drug["Quantity"]["Op"] == "gte"
    assert drug["Quantity"]["Value"] == 1000

    # Exclusion → exactly 0
    assert cc["Occurrence"]["Type"] == 0
    assert cc["Occurrence"]["Count"] == 0


# ─── Build → compile → CTE rewrite chain ────────────────────────────────


def test_build_compile_cte_rewrite_chain():
    """Build T2DM spec → compile → CTE rewrite produces executable SELECT."""
    spec = load_builder_spec("t2dm_full.json")
    build_result = build_cohort_definition_from_spec(spec)
    assert build_result["success"] is True

    compile_result = compile_cohort(
        build_result["cohort_json"],
        dialect="duckdb",
        cdm_schema="main_cdm",
        vocab_schema="main_vocab",
        results_schema="results",
    )
    assert compile_result["success"] is True

    rewritten = _rewrite_as_cte_select(compile_result["segments"])

    upper = rewritten.upper()
    assert rewritten.strip().upper().startswith("WITH ")
    assert "CREATE TEMP TABLE" not in upper
    assert "INSERT INTO" not in upper
    assert "SELECT" in upper

    # Verify key domain tables from the T2DM definition
    lower = rewritten.lower()
    assert "condition_occurrence" in lower
    assert "drug_exposure" in lower
