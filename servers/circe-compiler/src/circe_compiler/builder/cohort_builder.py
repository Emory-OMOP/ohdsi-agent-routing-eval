"""Cohort definition builder: simplified spec → valid CIRCE JSON.

Provides a Pydantic-validated input spec that abstracts CIRCE's internal
complexity (CodesetIds, Coeff notation, Occurrence type codes) behind
intuitive fields. Inspired by Capr (R, HADES) — adapted for LLM tool calling.

Usage:
    spec = CohortDefinitionSpec(...)
    result = build_cohort_definition_from_spec(spec)
    # result["cohort_json"] is valid CIRCE JSON ready for compile_cohort_definition
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from circe_compiler.models.cohort_expression import (
    CohortExpression,
    CollapseSettings,
    Concept,
    ConceptSetExpression,
    ConceptSetExpressionDetail,
    ConceptSetItem,
    CorelatedCriteria,
    Criteria,
    CriteriaGroup,
    DateOffsetStrategy,
    CustomEraStrategy,
    DemographicCriteria,
    EndStrategy,
    InclusionRule,
    NumericRange,
    ObservationWindow,
    Occurrence,
    PrimaryCriteria,
    ResultLimit,
    Window,
    WindowEndpoint,
)
from circe_compiler.models.cohort_expression import (
    ConditionOccurrence,
    DrugExposure,
    ProcedureOccurrence,
    Measurement,
    Observation,
    VisitOccurrence,
    VisitDetail,
    ConditionEra,
    DrugEra,
    DoseEra,
    Death,
    DeviceExposure,
    Specimen,
    ObservationPeriod,
)
from circe_compiler.validation.validator import CohortValidator

logger = logging.getLogger(__name__)


# ─── Domain mapping ──────────────────────────────────────────────────────────

DOMAIN_TO_CRITERIA_TYPE: dict[str, str] = {
    "Condition": "ConditionOccurrence",
    "Drug": "DrugExposure",
    "Procedure": "ProcedureOccurrence",
    "Measurement": "Measurement",
    "Observation": "Observation",
    "Visit": "VisitOccurrence",
    "Visit Detail": "VisitDetail",
    "Condition Era": "ConditionEra",
    "Drug Era": "DrugEra",
    "Dose Era": "DoseEra",
    "Death": "Death",
    "Device": "DeviceExposure",
    "Specimen": "Specimen",
    "Observation Period": "ObservationPeriod",
}

CRITERIA_TYPE_TO_CLASS: dict[str, type] = {
    "ConditionOccurrence": ConditionOccurrence,
    "DrugExposure": DrugExposure,
    "ProcedureOccurrence": ProcedureOccurrence,
    "Measurement": Measurement,
    "Observation": Observation,
    "VisitOccurrence": VisitOccurrence,
    "VisitDetail": VisitDetail,
    "ConditionEra": ConditionEra,
    "DrugEra": DrugEra,
    "DoseEra": DoseEra,
    "Death": Death,
    "DeviceExposure": DeviceExposure,
    "Specimen": Specimen,
    "ObservationPeriod": ObservationPeriod,
}

OCCURRENCE_TYPE_MAP: dict[str, int] = {
    "exactly": 0,
    "at_most": 1,
    "at_least": 2,
}

ATTRIBUTE_DOMAIN_ALLOWLIST: dict[str, set[str]] = {
    "value_as_number": {"Measurement", "Observation"},
    "value_as_concept": {"Measurement", "Observation"},
    "unit": {"Measurement", "Observation", "DoseEra", "Specimen"},
    "days_supply": {"DrugExposure"},
    "quantity": {"DrugExposure", "ProcedureOccurrence", "DeviceExposure", "Specimen"},
    "refills": {"DrugExposure"},
    "visit_type": {
        "ConditionOccurrence", "DrugExposure", "ProcedureOccurrence",
        "Measurement", "Observation", "DeviceExposure",
    },
    "age": {
        "ConditionOccurrence", "DrugExposure", "ProcedureOccurrence",
        "Measurement", "Observation", "VisitOccurrence", "VisitDetail",
        "Death", "DeviceExposure", "Specimen",
    },
    "gender": {
        "ConditionOccurrence", "DrugExposure", "ProcedureOccurrence",
        "Measurement", "Observation", "VisitOccurrence", "VisitDetail",
        "Death", "DeviceExposure", "Specimen", "ConditionEra", "DrugEra",
        "DoseEra",
    },
}


# ─── Simplified input models ─────────────────────────────────────────────────


class ConceptSpec(BaseModel):
    """A single OMOP concept with optional metadata."""

    concept_id: int
    concept_name: Optional[str] = None
    domain_id: Optional[str] = None
    vocabulary_id: Optional[str] = None
    concept_class_id: Optional[str] = None
    concept_code: Optional[str] = None
    standard_concept: Optional[str] = None
    include_descendants: bool = False
    include_mapped: bool = False
    is_excluded: bool = False


class ConceptSetSpec(BaseModel):
    """A named set of concepts belonging to a clinical domain."""

    name: str
    domain: str = Field(
        description="Clinical domain: Condition, Drug, Procedure, Measurement, "
        "Observation, Visit, Death, Device, Specimen, etc."
    )
    concepts: list[ConceptSpec] = Field(min_length=1)


class TemporalSpec(BaseModel):
    """Intuitive temporal window: days_before/days_after relative to index."""

    days_before: int = 0
    days_after: int = 0


class OccurrenceSpec(BaseModel):
    """Occurrence count constraint."""

    type: Literal["at_least", "at_most", "exactly"] = "at_least"
    count: int = 1


# ─── Attribute spec models ───────────────────────────────────────────────────


class _NumericAttributeBase(BaseModel):
    """Shared fields and validation for numeric attribute specs."""

    op: Literal["gt", "gte", "lt", "lte", "eq", "bt"]
    value: float
    extent: Optional[float] = None

    @model_validator(mode="after")
    def _validate_between(self) -> _NumericAttributeBase:
        if self.op == "bt" and self.extent is None:
            raise ValueError(
                f"extent is required when op='bt' for '{self.type}' attribute"
            )
        return self


class ValueAsNumberSpec(_NumericAttributeBase):
    """Numeric value constraint (e.g., HbA1c >= 9.0)."""
    type: Literal["value_as_number"] = "value_as_number"


class ValueAsConceptSpec(BaseModel):
    """Categorical value constraint (e.g., positive/negative result)."""
    type: Literal["value_as_concept"] = "value_as_concept"
    concept_ids: list[int] = Field(min_length=1)


class UnitSpec(BaseModel):
    """Unit constraint (e.g., percent, mg/dL)."""
    type: Literal["unit"] = "unit"
    concept_ids: list[int] = Field(min_length=1)


class DaysSupplySpec(_NumericAttributeBase):
    """Days supply constraint on drug exposures."""
    type: Literal["days_supply"] = "days_supply"


class QuantitySpec(_NumericAttributeBase):
    """Quantity constraint (drug, procedure, device, specimen)."""
    type: Literal["quantity"] = "quantity"


class RefillsSpec(_NumericAttributeBase):
    """Refills constraint on drug exposures."""
    type: Literal["refills"] = "refills"


class VisitTypeSpec(BaseModel):
    """Visit type constraint (e.g., inpatient, outpatient)."""
    type: Literal["visit_type"] = "visit_type"
    concept_ids: list[int] = Field(min_length=1)


class AgeSpec(_NumericAttributeBase):
    """Age at event constraint."""
    type: Literal["age"] = "age"


class GenderSpec(BaseModel):
    """Gender constraint."""
    type: Literal["gender"] = "gender"
    concept_ids: list[int] = Field(min_length=1)


AttributeSpec = Annotated[
    Union[
        ValueAsNumberSpec, ValueAsConceptSpec, UnitSpec,
        DaysSupplySpec, QuantitySpec, RefillsSpec,
        VisitTypeSpec, AgeSpec, GenderSpec,
    ],
    Field(discriminator="type"),
]


class DemographicSpec(BaseModel):
    """Optional demographic filters."""

    age_min: Optional[int] = None
    age_max: Optional[int] = None
    gender_concept_ids: Optional[list[int]] = None


class InclusionRuleSpec(BaseModel):
    """A named inclusion rule with temporal and occurrence constraints."""

    name: str
    concept_set: str = Field(description="Name reference to a concept set")
    temporal: Optional[TemporalSpec] = None
    occurrence: Optional[OccurrenceSpec] = None
    demographic: Optional[DemographicSpec] = None
    attributes: list[AttributeSpec] = Field(
        default=[],
        description="Domain-specific attribute constraints (e.g., value_as_number, days_supply)",
    )


class ExclusionCriterionSpec(BaseModel):
    """An exclusion criterion — converted to InclusionRule with Occurrence(exactly, 0)."""

    name: str
    concept_set: str = Field(description="Name reference to a concept set")
    temporal: Optional[TemporalSpec] = None
    attributes: list[AttributeSpec] = Field(
        default=[],
        description="Domain-specific attribute constraints",
    )


class EndStrategySpec(BaseModel):
    """How cohort membership ends."""

    type: Literal["observation_end", "date_offset", "drug_era"] = "observation_end"
    offset_days: int = 0
    date_field: str = "StartDate"
    drug_concept_set: Optional[str] = None
    gap_days: int = 0


class PrimaryCriteriaSpec(BaseModel):
    """The entry event for the cohort."""

    concept_set: str = Field(description="Name reference to a concept set")
    first_occurrence: bool = True
    attributes: list[AttributeSpec] = Field(
        default=[],
        description="Domain-specific attribute constraints on the entry event",
    )


class CohortDefinitionSpec(BaseModel):
    """Top-level cohort definition specification.

    Simplified input format that maps to valid CIRCE JSON.
    All concept_set fields are name references resolved against concept_sets.
    """

    concept_sets: list[ConceptSetSpec] = Field(min_length=1)
    primary_criteria: PrimaryCriteriaSpec
    inclusion_rules: list[InclusionRuleSpec] = []
    exclusion_criteria: list[ExclusionCriterionSpec] = []
    observation_window: Optional[TemporalSpec] = None
    end_strategy: Optional[EndStrategySpec] = None
    qualified_limit: Literal["First", "All", "Last"] = "First"
    collapse_era_pad: int = 0

    @model_validator(mode="after")
    def validate_name_refs(self) -> CohortDefinitionSpec:
        """Ensure all concept_set name references resolve."""
        valid_names = {cs.name for cs in self.concept_sets}

        # Primary criteria
        if self.primary_criteria.concept_set not in valid_names:
            raise ValueError(
                f"primary_criteria.concept_set '{self.primary_criteria.concept_set}' "
                f"not found in concept_sets. Available: {sorted(valid_names)}"
            )

        # Inclusion rules
        for rule in self.inclusion_rules:
            if rule.concept_set not in valid_names:
                raise ValueError(
                    f"inclusion_rules['{rule.name}'].concept_set '{rule.concept_set}' "
                    f"not found in concept_sets. Available: {sorted(valid_names)}"
                )

        # Exclusion criteria
        for exc in self.exclusion_criteria:
            if exc.concept_set not in valid_names:
                raise ValueError(
                    f"exclusion_criteria['{exc.name}'].concept_set '{exc.concept_set}' "
                    f"not found in concept_sets. Available: {sorted(valid_names)}"
                )

        # End strategy drug_concept_set
        if (
            self.end_strategy
            and self.end_strategy.type == "drug_era"
            and self.end_strategy.drug_concept_set
            and self.end_strategy.drug_concept_set not in valid_names
        ):
            raise ValueError(
                f"end_strategy.drug_concept_set '{self.end_strategy.drug_concept_set}' "
                f"not found in concept_sets. Available: {sorted(valid_names)}"
            )

        return self

    @model_validator(mode="after")
    def validate_attributes(self) -> CohortDefinitionSpec:
        """Validate that attributes are compatible with their concept set's domain."""
        cs_domain_map = {cs.name: cs.domain for cs in self.concept_sets}

        def _check_attrs(
            concept_set_name: str, attributes: list, location: str
        ) -> None:
            domain = cs_domain_map.get(concept_set_name)
            if domain is None:
                return  # name ref validation handles this
            criteria_type = DOMAIN_TO_CRITERIA_TYPE.get(domain)
            if criteria_type is None:
                return  # domain validation handles this
            for attr in attributes:
                allowed = ATTRIBUTE_DOMAIN_ALLOWLIST.get(attr.type, set())
                if criteria_type not in allowed:
                    raise ValueError(
                        f"{location}: attribute '{attr.type}' is not valid for "
                        f"domain '{domain}' (criteria type '{criteria_type}'). "
                        f"Valid criteria types for '{attr.type}': {sorted(allowed)}"
                    )

        _check_attrs(
            self.primary_criteria.concept_set,
            self.primary_criteria.attributes,
            "primary_criteria",
        )
        for rule in self.inclusion_rules:
            _check_attrs(
                rule.concept_set,
                rule.attributes,
                f"inclusion_rules['{rule.name}']",
            )
        for exc in self.exclusion_criteria:
            _check_attrs(
                exc.concept_set,
                exc.attributes,
                f"exclusion_criteria['{exc.name}']",
            )

        return self


# ─── Builder ──────────────────────────────────────────────────────────────────


def _build_concept(spec: ConceptSpec) -> Concept:
    """Convert a ConceptSpec to a CIRCE Concept."""
    return Concept(
        CONCEPT_ID=spec.concept_id,
        CONCEPT_NAME=spec.concept_name,
        DOMAIN_ID=spec.domain_id,
        VOCABULARY_ID=spec.vocabulary_id,
        CONCEPT_CLASS_ID=spec.concept_class_id,
        CONCEPT_CODE=spec.concept_code,
        STANDARD_CONCEPT=spec.standard_concept,
    )


def _build_concept_sets(
    specs: list[ConceptSetSpec],
) -> tuple[list[ConceptSetExpression], dict[str, int]]:
    """Build CIRCE ConceptSetExpressions and return name→CodesetId map."""
    concept_sets: list[ConceptSetExpression] = []
    name_to_id: dict[str, int] = {}

    for idx, cs_spec in enumerate(specs):
        name_to_id[cs_spec.name] = idx

        items = [
            ConceptSetItem(
                concept=_build_concept(c),
                isExcluded=c.is_excluded,
                includeDescendants=c.include_descendants,
                includeMapped=c.include_mapped,
            )
            for c in cs_spec.concepts
        ]

        concept_sets.append(
            ConceptSetExpression(
                id=idx,
                name=cs_spec.name,
                expression=ConceptSetExpressionDetail(items=items),
            )
        )

    return concept_sets, name_to_id


def _resolve_criteria_type(domain: str) -> str:
    """Map a domain string to CIRCE criteria type name."""
    criteria_type = DOMAIN_TO_CRITERIA_TYPE.get(domain)
    if criteria_type is None:
        raise ValueError(
            f"Unknown domain '{domain}'. "
            f"Supported: {sorted(DOMAIN_TO_CRITERIA_TYPE.keys())}"
        )
    return criteria_type


def _apply_attributes(domain_instance: Any, attributes: list) -> None:
    """Apply attribute specs to a CIRCE domain criteria instance.

    Maps each AttributeSpec to the corresponding field on the domain object
    (e.g., ValueAsNumberSpec → domain_instance.ValueAsNumber = NumericRange(...)).
    """
    for attr in attributes:
        if attr.type == "value_as_number":
            domain_instance.ValueAsNumber = NumericRange(
                Op=attr.op, Value=attr.value, Extent=attr.extent,
            )
        elif attr.type == "value_as_concept":
            domain_instance.ValueAsConcept = [
                Concept(CONCEPT_ID=cid) for cid in attr.concept_ids
            ]
        elif attr.type == "unit":
            domain_instance.Unit = [
                Concept(CONCEPT_ID=cid) for cid in attr.concept_ids
            ]
        elif attr.type == "days_supply":
            domain_instance.DaysSupply = NumericRange(
                Op=attr.op, Value=attr.value, Extent=attr.extent,
            )
        elif attr.type == "quantity":
            domain_instance.Quantity = NumericRange(
                Op=attr.op, Value=attr.value, Extent=attr.extent,
            )
        elif attr.type == "refills":
            domain_instance.Refills = NumericRange(
                Op=attr.op, Value=attr.value, Extent=attr.extent,
            )
        elif attr.type == "visit_type":
            domain_instance.VisitType = [
                Concept(CONCEPT_ID=cid) for cid in attr.concept_ids
            ]
        elif attr.type == "age":
            domain_instance.Age = NumericRange(
                Op=attr.op, Value=attr.value, Extent=attr.extent,
            )
        elif attr.type == "gender":
            domain_instance.Gender = [
                Concept(CONCEPT_ID=cid) for cid in attr.concept_ids
            ]


def _build_domain_criteria(
    criteria_type: str,
    codeset_id: int,
    first: bool = False,
    attributes: list | None = None,
) -> Criteria:
    """Build a Criteria wrapper with the appropriate domain field set."""
    cls = CRITERIA_TYPE_TO_CLASS.get(criteria_type)
    if cls is None:
        raise ValueError(f"Unknown criteria type '{criteria_type}'")

    kwargs: dict[str, Any] = {"CodesetId": codeset_id}
    if first and hasattr(cls, "First"):
        kwargs["First"] = True

    domain_instance = cls(**kwargs)
    if attributes:
        _apply_attributes(domain_instance, attributes)
    return Criteria(**{criteria_type: domain_instance})


def _build_temporal_window(temporal: TemporalSpec | None) -> Window:
    """Convert TemporalSpec to CIRCE Window with Coeff notation."""
    if temporal is None:
        temporal = TemporalSpec(days_before=99999, days_after=0)

    return Window(
        Start=WindowEndpoint(Days=temporal.days_before, Coeff=-1),
        End=WindowEndpoint(Days=temporal.days_after, Coeff=1 if temporal.days_after > 0 else -1),
        UseIndexEnd=False,
        UseEventEnd=False,
    )


def _build_occurrence(occurrence: OccurrenceSpec | None) -> Occurrence:
    """Convert OccurrenceSpec to CIRCE Occurrence."""
    if occurrence is None:
        occurrence = OccurrenceSpec(type="at_least", count=1)

    return Occurrence(
        Type=OCCURRENCE_TYPE_MAP[occurrence.type],
        Count=occurrence.count,
        IsDistinct=False,
    )


def _build_demographic_criteria(demographic: DemographicSpec | None) -> list[DemographicCriteria]:
    """Convert DemographicSpec to CIRCE DemographicCriteria list."""
    if demographic is None:
        return []

    kwargs: dict[str, Any] = {}

    if demographic.age_min is not None or demographic.age_max is not None:
        age_range: dict[str, Any] = {}
        if demographic.age_min is not None and demographic.age_max is not None:
            age_range = {"Value": demographic.age_min, "Extent": demographic.age_max, "Op": "bt"}
        elif demographic.age_min is not None:
            age_range = {"Value": demographic.age_min, "Op": "gte"}
        elif demographic.age_max is not None:
            age_range = {"Value": demographic.age_max, "Op": "lte"}
        kwargs["Age"] = NumericRange(**age_range)

    if demographic.gender_concept_ids:
        kwargs["Gender"] = [
            Concept(CONCEPT_ID=gid) for gid in demographic.gender_concept_ids
        ]

    if kwargs:
        return [DemographicCriteria(**kwargs)]
    return []


def _build_inclusion_rule(
    rule_spec: InclusionRuleSpec,
    name_to_id: dict[str, int],
    concept_sets: list[ConceptSetSpec],
) -> InclusionRule:
    """Convert an InclusionRuleSpec to a CIRCE InclusionRule."""
    codeset_id = name_to_id[rule_spec.concept_set]
    cs_spec = next(cs for cs in concept_sets if cs.name == rule_spec.concept_set)
    criteria_type = _resolve_criteria_type(cs_spec.domain)

    criteria = _build_domain_criteria(
        criteria_type, codeset_id, attributes=rule_spec.attributes or None,
    )
    window = _build_temporal_window(rule_spec.temporal)
    occurrence = _build_occurrence(rule_spec.occurrence)
    demographics = _build_demographic_criteria(rule_spec.demographic)

    return InclusionRule(
        name=rule_spec.name,
        expression=CriteriaGroup(
            Type="ALL",
            CriteriaList=[
                CorelatedCriteria(
                    Criteria=criteria,
                    StartWindow=window,
                    Occurrence=occurrence,
                )
            ],
            DemographicCriteriaList=demographics,
            Groups=[],
        ),
    )


def _build_exclusion_as_inclusion(
    exc_spec: ExclusionCriterionSpec,
    name_to_id: dict[str, int],
    concept_sets: list[ConceptSetSpec],
) -> InclusionRule:
    """Convert an ExclusionCriterionSpec to a CIRCE InclusionRule with exactly 0 occurrences."""
    codeset_id = name_to_id[exc_spec.concept_set]
    cs_spec = next(cs for cs in concept_sets if cs.name == exc_spec.concept_set)
    criteria_type = _resolve_criteria_type(cs_spec.domain)

    criteria = _build_domain_criteria(
        criteria_type, codeset_id, attributes=exc_spec.attributes or None,
    )

    # Default temporal for exclusions: all time prior
    if exc_spec.temporal:
        window = _build_temporal_window(exc_spec.temporal)
    else:
        window = Window(
            Start=WindowEndpoint(Days=99999, Coeff=-1),
            End=WindowEndpoint(Days=0, Coeff=-1),
            UseIndexEnd=False,
            UseEventEnd=False,
        )

    return InclusionRule(
        name=exc_spec.name,
        expression=CriteriaGroup(
            Type="ALL",
            CriteriaList=[
                CorelatedCriteria(
                    Criteria=criteria,
                    StartWindow=window,
                    Occurrence=Occurrence(Type=0, Count=0, IsDistinct=False),
                )
            ],
            DemographicCriteriaList=[],
            Groups=[],
        ),
    )


def _build_end_strategy(
    strategy: EndStrategySpec | None,
    name_to_id: dict[str, int],
) -> EndStrategy | None:
    """Convert EndStrategySpec to CIRCE EndStrategy."""
    if strategy is None or strategy.type == "observation_end":
        return None

    if strategy.type == "date_offset":
        return EndStrategy(
            DateOffset=DateOffsetStrategy(
                DateField=strategy.date_field,
                Offset=strategy.offset_days,
            )
        )

    if strategy.type == "drug_era":
        drug_codeset_id = None
        if strategy.drug_concept_set:
            drug_codeset_id = name_to_id[strategy.drug_concept_set]
        return EndStrategy(
            CustomEra=CustomEraStrategy(
                DrugCodesetId=drug_codeset_id,
                GapDays=strategy.gap_days,
                Offset=strategy.offset_days,
            )
        )

    return None


def _build_error_hints(error_str: str) -> str:
    """Return contextual hints for common builder spec mistakes."""
    hints: list[str] = []
    err = error_str.lower()

    # CIRCE field names used instead of simplified spec fields
    if any(kw in err for kw in ("criteria", "codeset", "criterialist", "codesetid")):
        hints.append(
            "Hint: Use simplified spec fields, not raw CIRCE field names. "
            "Use 'concept_set' (a name reference like \"Type 2 Diabetes\"), "
            "not 'CodesetId' or 'CriteriaList'."
        )

    # Exclusion pattern mistakes
    if any(kw in err for kw in ("exclusion", "exclude")):
        hints.append(
            "Hint: Exclusion criteria use ExclusionCriterionSpec shape: "
            '{"name": "No prior CKD", "concept_set": "CKD"} '
            "(with optional 'temporal' and 'attributes'). "
            "Place them in the top-level 'exclusion_criteria' list."
        )

    # Demographic / age / gender pattern mistakes
    if any(kw in err for kw in ("demographic", "age", "gender")):
        hints.append(
            "Hint: Demographics go inside an InclusionRuleSpec via the "
            "'demographic' field: "
            '{"age_min": 18, "age_max": 65, "gender_concept_ids": [8507]}. '
            "They are NOT a top-level spec field."
        )

    # Inclusion rule shape mistakes
    if "inclusion" in err and any(kw in err for kw in ("concept_set", "field")):
        hints.append(
            "Hint: InclusionRuleSpec shape: "
            '{"name": str, "concept_set": "<name>", '
            '"temporal": {"days_before": int, "days_after": int}, '
            '"occurrence": {"type": "at_least", "count": 1}, '
            '"demographic": {"age_min": int, "age_max": int}}.'
        )

    # Concept set name resolution failures
    if "not found in concept_sets" in err or "not found in concept_set" in err:
        hints.append(
            "Hint: The 'concept_set' field must exactly match a 'name' in "
            "the top-level 'concept_sets' list (case-sensitive)."
        )

    return " ".join(hints)


def build_cohort_definition_from_spec(
    spec: CohortDefinitionSpec | dict | str,
) -> dict[str, Any]:
    """Build a valid CIRCE cohort definition JSON from a simplified spec.

    Args:
        spec: A CohortDefinitionSpec, dict, or JSON string.

    Returns:
        Dict with keys:
            success: bool
            cohort_json: dict (the CIRCE JSON) — present on success
            validation: dict with is_valid, summary, issues
            concept_set_mapping: dict of name → CodesetId
            summary: str — human-readable summary
        On failure:
            success: False
            error: str
            validation: dict (if validation ran)
    """
    # Parse input
    try:
        if isinstance(spec, str):
            spec = CohortDefinitionSpec.model_validate_json(spec)
        elif isinstance(spec, dict):
            spec = CohortDefinitionSpec.model_validate(spec)
    except Exception as e:
        error_msg = f"Invalid spec: {e}"
        hints = _build_error_hints(str(e))
        if hints:
            error_msg = f"{error_msg} | {hints}"
        return {
            "success": False,
            "error": error_msg,
        }

    try:
        # Step 1: Build concept sets and name→id mapping
        concept_sets, name_to_id = _build_concept_sets(spec.concept_sets)

        # Step 2: Build primary criteria
        pc_cs_spec = next(
            cs for cs in spec.concept_sets
            if cs.name == spec.primary_criteria.concept_set
        )
        pc_criteria_type = _resolve_criteria_type(pc_cs_spec.domain)
        pc_codeset_id = name_to_id[spec.primary_criteria.concept_set]
        pc_criteria = _build_domain_criteria(
            pc_criteria_type,
            pc_codeset_id,
            first=spec.primary_criteria.first_occurrence,
            attributes=spec.primary_criteria.attributes or None,
        )

        obs_window = ObservationWindow(
            PriorDays=spec.observation_window.days_before if spec.observation_window else 0,
            PostDays=spec.observation_window.days_after if spec.observation_window else 0,
        )

        primary_criteria = PrimaryCriteria(
            CriteriaList=[pc_criteria],
            ObservationWindow=obs_window,
            PrimaryCriteriaLimit=ResultLimit(Type="First" if spec.primary_criteria.first_occurrence else "All"),
        )

        # Step 3: Build inclusion rules
        inclusion_rules: list[InclusionRule] = []
        for rule_spec in spec.inclusion_rules:
            inclusion_rules.append(
                _build_inclusion_rule(rule_spec, name_to_id, spec.concept_sets)
            )

        # Step 4: Convert exclusion criteria to inclusion rules
        for exc_spec in spec.exclusion_criteria:
            inclusion_rules.append(
                _build_exclusion_as_inclusion(exc_spec, name_to_id, spec.concept_sets)
            )

        # Step 5: Build end strategy
        end_strategy = _build_end_strategy(spec.end_strategy, name_to_id)

        # Step 6: Assemble CohortExpression
        expression = CohortExpression(
            ConceptSets=concept_sets,
            PrimaryCriteria=primary_criteria,
            QualifiedLimit=ResultLimit(Type=spec.qualified_limit),
            ExpressionLimit=ResultLimit(Type="All"),
            InclusionRules=inclusion_rules,
            EndStrategy=end_strategy,
            CensoringCriteria=[],
            CollapseSettings=CollapseSettings(
                CollapseType="ERA",
                EraPad=spec.collapse_era_pad,
            ),
        )

        # Step 7: Validate
        validator = CohortValidator()
        validation = validator.validate(expression)

        # Step 8: Serialize to JSON-compatible dict
        cohort_json = json.loads(expression.model_dump_json(by_alias=True, exclude_none=True))

        validation_dict = {
            "is_valid": validation.is_valid,
            "summary": validation.summary,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "message": issue.message,
                    "path": issue.path,
                }
                for issue in validation.issues
            ],
        }

        if not validation.is_valid:
            return {
                "success": False,
                "error": "Built definition failed validation",
                "cohort_json": cohort_json,
                "validation": validation_dict,
                "concept_set_mapping": name_to_id,
            }

        # Build summary
        n_inclusion = len(spec.inclusion_rules)
        n_exclusion = len(spec.exclusion_criteria)
        summary_parts = [
            f"Built cohort definition with {len(spec.concept_sets)} concept set(s)",
            f"Primary event: {pc_criteria_type} from '{spec.primary_criteria.concept_set}'",
        ]
        if n_inclusion:
            summary_parts.append(f"{n_inclusion} inclusion rule(s)")
        if n_exclusion:
            summary_parts.append(f"{n_exclusion} exclusion criterion/criteria")
        if end_strategy:
            if end_strategy.DateOffset:
                summary_parts.append(
                    f"End strategy: {end_strategy.DateOffset.DateField} + {end_strategy.DateOffset.Offset} days"
                )
            elif end_strategy.CustomEra:
                summary_parts.append("End strategy: drug era")
        else:
            summary_parts.append("End strategy: end of continuous observation")

        return {
            "success": True,
            "cohort_json": cohort_json,
            "validation": validation_dict,
            "concept_set_mapping": name_to_id,
            "summary": ". ".join(summary_parts) + ".",
        }

    except Exception as e:
        error_msg = str(e)
        hints = _build_error_hints(error_msg)
        if hints:
            error_msg = f"{error_msg} | {hints}"
        return {
            "success": False,
            "error": error_msg,
        }
