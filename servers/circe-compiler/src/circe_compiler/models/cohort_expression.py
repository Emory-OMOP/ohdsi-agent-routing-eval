"""
Pydantic models for the OHDSI CIRCE cohort definition JSON schema.

These models represent the complete structure of an ATLAS/CIRCE cohort definition,
enabling parsing, validation, and compilation of cohort definitions to SQL.

Reference: https://github.com/OHDSI/circe-be
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ───────────────────────────────────────────────────────────────────


class ResultLimitType(str, Enum):
    FIRST = "First"
    ALL = "All"
    LAST = "Last"


class OccurrenceType(int, Enum):
    EXACTLY = 0
    AT_MOST = 1
    AT_LEAST = 2


class CriteriaGroupType(str, Enum):
    ALL = "ALL"
    ANY = "ANY"
    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"


class CollapseType(str, Enum):
    ERA = "ERA"


# ─── Concept primitives ─────────────────────────────────────────────────────


class Concept(BaseModel):
    """An OMOP vocabulary concept."""
    CONCEPT_ID: int
    CONCEPT_NAME: Optional[str] = None
    STANDARD_CONCEPT: Optional[str] = None
    STANDARD_CONCEPT_CAPTION: Optional[str] = None
    INVALID_REASON: Optional[str] = None
    INVALID_REASON_CAPTION: Optional[str] = None
    CONCEPT_CODE: Optional[str] = None
    DOMAIN_ID: Optional[str] = None
    VOCABULARY_ID: Optional[str] = None
    CONCEPT_CLASS_ID: Optional[str] = None


class ConceptSetItem(BaseModel):
    """A single item in a concept set expression."""
    model_config = ConfigDict(populate_by_name=True)

    concept: Concept = Field(alias="concept")
    isExcluded: bool = False
    includeDescendants: bool = False
    includeMapped: bool = False


class ConceptSetExpression(BaseModel):
    """A named concept set with its expression items."""
    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str
    expression: ConceptSetExpressionDetail


class ConceptSetExpressionDetail(BaseModel):
    """The items array within a concept set."""
    items: list[ConceptSetItem] = []


# ─── Numeric/Date Range types ───────────────────────────────────────────────


class NumericRange(BaseModel):
    """A numeric comparison: Value op Extent (e.g., gte 5)."""
    Value: Optional[float] = None
    Extent: Optional[float] = None
    Op: Optional[str] = None  # lt, lte, gt, gte, eq, neq, bt (between)


class DateRange(BaseModel):
    """A date comparison."""
    Value: Optional[str] = None
    Extent: Optional[str] = None
    Op: Optional[str] = None


class Period(BaseModel):
    """A date period for user-defined windows."""
    StartDate: Optional[str] = None
    EndDate: Optional[str] = None


class TextFilter(BaseModel):
    """A text comparison."""
    Text: Optional[str] = None
    Op: Optional[str] = None  # contains, startsWith, endsWith, eq


# ─── Window types ────────────────────────────────────────────────────────────


class WindowEndpoint(BaseModel):
    """One end of a temporal window."""
    Days: Optional[int] = None
    Coeff: int = 1  # 1 = after, -1 = before


class Window(BaseModel):
    """A temporal window defined by start/end endpoints."""
    Start: WindowEndpoint
    End: WindowEndpoint
    UseIndexEnd: Optional[bool] = False
    UseEventEnd: Optional[bool] = False


class Occurrence(BaseModel):
    """Occurrence count constraint (exactly / at most / at least N)."""
    Type: int = 2  # 0=exactly, 1=at_most, 2=at_least (OHDSI/Capr standard)
    Count: int = 0
    IsDistinct: Optional[bool] = False
    CountColumn: Optional[str] = None


# ─── Domain criteria ─────────────────────────────────────────────────────────


class ConditionOccurrence(BaseModel):
    """Criteria for condition_occurrence table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None
    ConditionType: Optional[list[Concept]] = None
    ConditionTypeExclude: Optional[bool] = None
    StopReason: Optional[TextFilter] = None
    ConditionSourceConcept: Optional[int] = None
    ConditionStatus: Optional[list[Concept]] = None
    ConditionStatusExclude: Optional[bool] = None
    ProviderSpecialty: Optional[list[Concept]] = None
    VisitType: Optional[list[Concept]] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    OccurrenceCount: Optional[NumericRange] = None


class DrugExposure(BaseModel):
    """Criteria for drug_exposure table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None
    DrugType: Optional[list[Concept]] = None
    DrugTypeExclude: Optional[bool] = None
    StopReason: Optional[TextFilter] = None
    Refills: Optional[NumericRange] = None
    Quantity: Optional[NumericRange] = None
    DaysSupply: Optional[NumericRange] = None
    RouteConcept: Optional[list[Concept]] = None
    EffectiveDrugDose: Optional[NumericRange] = None
    DoseUnit: Optional[list[Concept]] = None
    LotNumber: Optional[TextFilter] = None
    DrugSourceConcept: Optional[int] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    ProviderSpecialty: Optional[list[Concept]] = None
    VisitType: Optional[list[Concept]] = None


class ProcedureOccurrence(BaseModel):
    """Criteria for procedure_occurrence table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None
    ProcedureType: Optional[list[Concept]] = None
    ProcedureTypeExclude: Optional[bool] = None
    Modifier: Optional[list[Concept]] = None
    Quantity: Optional[NumericRange] = None
    ProcedureSourceConcept: Optional[int] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    ProviderSpecialty: Optional[list[Concept]] = None
    VisitType: Optional[list[Concept]] = None


class Measurement(BaseModel):
    """Criteria for measurement table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    MeasurementType: Optional[list[Concept]] = None
    MeasurementTypeExclude: Optional[bool] = None
    Operator: Optional[list[Concept]] = None
    ValueAsNumber: Optional[NumericRange] = None
    ValueAsConcept: Optional[list[Concept]] = None
    Unit: Optional[list[Concept]] = None
    RangeLow: Optional[NumericRange] = None
    RangeHigh: Optional[NumericRange] = None
    RangeLowRatio: Optional[NumericRange] = None
    RangeHighRatio: Optional[NumericRange] = None
    Abnormal: Optional[bool] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    ProviderSpecialty: Optional[list[Concept]] = None
    VisitType: Optional[list[Concept]] = None
    MeasurementSourceConcept: Optional[int] = None


class Observation(BaseModel):
    """Criteria for observation table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    ObservationType: Optional[list[Concept]] = None
    ObservationTypeExclude: Optional[bool] = None
    ValueAsNumber: Optional[NumericRange] = None
    ValueAsString: Optional[TextFilter] = None
    ValueAsConcept: Optional[list[Concept]] = None
    QualifierConcept: Optional[list[Concept]] = None
    Unit: Optional[list[Concept]] = None
    ObservationSourceConcept: Optional[int] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    ProviderSpecialty: Optional[list[Concept]] = None
    VisitType: Optional[list[Concept]] = None


class VisitOccurrence(BaseModel):
    """Criteria for visit_occurrence table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None
    VisitType: Optional[list[Concept]] = None
    VisitTypeExclude: Optional[bool] = None
    VisitSourceConcept: Optional[int] = None
    VisitLength: Optional[NumericRange] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    ProviderSpecialty: Optional[list[Concept]] = None


class VisitDetail(BaseModel):
    """Criteria for visit_detail table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None
    VisitDetailType: Optional[list[Concept]] = None
    VisitDetailTypeExclude: Optional[bool] = None
    VisitDetailSourceConcept: Optional[int] = None
    VisitDetailLength: Optional[NumericRange] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None


class ConditionEra(BaseModel):
    """Criteria for condition_era table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    EraStartDate: Optional[DateRange] = None
    EraEndDate: Optional[DateRange] = None
    EraLength: Optional[NumericRange] = None
    AgeAtStart: Optional[NumericRange] = None
    AgeAtEnd: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    OccurrenceCount: Optional[NumericRange] = None


class DrugEra(BaseModel):
    """Criteria for drug_era table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    EraStartDate: Optional[DateRange] = None
    EraEndDate: Optional[DateRange] = None
    EraLength: Optional[NumericRange] = None
    AgeAtStart: Optional[NumericRange] = None
    AgeAtEnd: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    OccurrenceCount: Optional[NumericRange] = None
    GapDays: Optional[NumericRange] = None


class DoseEra(BaseModel):
    """Criteria for dose_era table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    EraStartDate: Optional[DateRange] = None
    EraEndDate: Optional[DateRange] = None
    Unit: Optional[list[Concept]] = None
    DoseValue: Optional[NumericRange] = None
    EraLength: Optional[NumericRange] = None
    AgeAtStart: Optional[NumericRange] = None
    AgeAtEnd: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None


class Death(BaseModel):
    """Criteria for death table."""
    CodesetId: Optional[int] = None
    OccurrenceStartDate: Optional[DateRange] = None
    DeathType: Optional[list[Concept]] = None
    DeathTypeExclude: Optional[bool] = None
    DeathSourceConcept: Optional[int] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None


class DeviceExposure(BaseModel):
    """Criteria for device_exposure table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None
    DeviceType: Optional[list[Concept]] = None
    DeviceTypeExclude: Optional[bool] = None
    UniqueDeviceId: Optional[TextFilter] = None
    Quantity: Optional[NumericRange] = None
    DeviceSourceConcept: Optional[int] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    ProviderSpecialty: Optional[list[Concept]] = None
    VisitType: Optional[list[Concept]] = None


class Specimen(BaseModel):
    """Criteria for specimen table."""
    CodesetId: Optional[int] = None
    First: Optional[bool] = None
    OccurrenceStartDate: Optional[DateRange] = None
    SpecimenType: Optional[list[Concept]] = None
    SpecimenTypeExclude: Optional[bool] = None
    Quantity: Optional[NumericRange] = None
    Unit: Optional[list[Concept]] = None
    AnatomicSite: Optional[list[Concept]] = None
    DiseaseStatus: Optional[list[Concept]] = None
    SourceId: Optional[TextFilter] = None
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None


class ObservationPeriod(BaseModel):
    """Criteria for observation_period table."""
    First: Optional[bool] = None
    PeriodStartDate: Optional[DateRange] = None
    PeriodEndDate: Optional[DateRange] = None
    PeriodType: Optional[list[Concept]] = None
    PeriodLength: Optional[NumericRange] = None
    AgeAtStart: Optional[NumericRange] = None
    AgeAtEnd: Optional[NumericRange] = None
    UserDefinedPeriod: Optional[Period] = None


class PayerPlanPeriod(BaseModel):
    """Criteria for payer_plan_period table."""
    PeriodStartDate: Optional[DateRange] = None
    PeriodEndDate: Optional[DateRange] = None
    UserDefinedPeriod: Optional[Period] = None
    PeriodLength: Optional[NumericRange] = None
    AgeAtStart: Optional[NumericRange] = None
    AgeAtEnd: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    PayerConcept: Optional[list[Concept]] = None
    PlanConcept: Optional[list[Concept]] = None
    SponsorConcept: Optional[list[Concept]] = None
    StopReasonConcept: Optional[list[Concept]] = None
    PayerSourceConcept: Optional[int] = None
    PlanSourceConcept: Optional[int] = None
    SponsorSourceConcept: Optional[int] = None
    StopReasonSourceConcept: Optional[int] = None


class LocationRegion(BaseModel):
    """Criteria for location_region."""
    CodesetId: Optional[int] = None
    StartDate: Optional[DateRange] = None
    EndDate: Optional[DateRange] = None


class DemographicCriteria(BaseModel):
    """Demographic criteria (age, gender, race, ethnicity)."""
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    Race: Optional[list[Concept]] = None
    Ethnicity: Optional[list[Concept]] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None


# ─── Criteria wrapper (union type) ──────────────────────────────────────────

# Type aliases to avoid Pydantic 2.10+ error when field names shadow type names
# (e.g. ``ConditionOccurrence: Optional[ConditionOccurrence]``).
_ConditionOccurrence = ConditionOccurrence
_DrugExposure = DrugExposure
_ProcedureOccurrence = ProcedureOccurrence
_Measurement = Measurement
_Observation = Observation
_VisitOccurrence = VisitOccurrence
_VisitDetail = VisitDetail
_ConditionEra = ConditionEra
_DrugEra = DrugEra
_DoseEra = DoseEra
_Death = Death
_DeviceExposure = DeviceExposure
_Specimen = Specimen
_ObservationPeriod = ObservationPeriod
_PayerPlanPeriod = PayerPlanPeriod
_LocationRegion = LocationRegion


class Criteria(BaseModel):
    """
    A wrapper holding exactly one domain criterion.
    CIRCE JSON uses the domain class name as the key.
    """
    ConditionOccurrence: Optional[_ConditionOccurrence] = None
    DrugExposure: Optional[_DrugExposure] = None
    ProcedureOccurrence: Optional[_ProcedureOccurrence] = None
    Measurement: Optional[_Measurement] = None
    Observation: Optional[_Observation] = None
    VisitOccurrence: Optional[_VisitOccurrence] = None
    VisitDetail: Optional[_VisitDetail] = None
    ConditionEra: Optional[_ConditionEra] = None
    DrugEra: Optional[_DrugEra] = None
    DoseEra: Optional[_DoseEra] = None
    Death: Optional[_Death] = None
    DeviceExposure: Optional[_DeviceExposure] = None
    Specimen: Optional[_Specimen] = None
    ObservationPeriod: Optional[_ObservationPeriod] = None
    PayerPlanPeriod: Optional[_PayerPlanPeriod] = None
    LocationRegion: Optional[_LocationRegion] = None

    def get_active(self) -> tuple[str, BaseModel]:
        """Return (domain_name, criteria) for the single active criterion."""
        for field_name in self.__class__.model_fields:
            value = getattr(self, field_name)
            if value is not None:
                return (field_name, value)
        raise ValueError("Criteria has no active domain criterion")


# ─── Correlated criteria ────────────────────────────────────────────────────

_Criteria = Criteria
_Occurrence = Occurrence


class CorelatedCriteria(BaseModel):
    """A criterion correlated to the primary event with temporal/occurrence constraints."""
    Criteria: _Criteria
    StartWindow: Window
    EndWindow: Optional[Window] = None
    RestrictVisit: Optional[bool] = False
    IgnoreObservationPeriod: Optional[bool] = False
    Occurrence: _Occurrence


class DemographicCriteriaWrapper(BaseModel):
    """Wrapper for demographic criteria in a criteria group."""
    Age: Optional[NumericRange] = None
    Gender: Optional[list[Concept]] = None
    Race: Optional[list[Concept]] = None
    Ethnicity: Optional[list[Concept]] = None
    OccurrenceStartDate: Optional[DateRange] = None
    OccurrenceEndDate: Optional[DateRange] = None


class CriteriaGroup(BaseModel):
    """A group of criteria combined with ALL/ANY/AT_LEAST/AT_MOST logic."""
    Type: str = "ALL"  # ALL, ANY, AT_LEAST, AT_MOST
    Count: Optional[int] = None
    CriteriaList: list[CorelatedCriteria] = []
    DemographicCriteriaList: list[DemographicCriteria] = []
    Groups: list[CriteriaGroup] = []


# ─── Primary criteria ───────────────────────────────────────────────────────


class ObservationWindow(BaseModel):
    """Required observation before/after entry event."""
    PriorDays: int = 0
    PostDays: int = 0


class ResultLimit(BaseModel):
    """Limits on result set (First/All)."""
    Type: str = "First"


_ObservationWindow = ObservationWindow


class PrimaryCriteria(BaseModel):
    """The initial event criteria defining cohort entry."""
    CriteriaList: list[_Criteria] = []
    ObservationWindow: _ObservationWindow = _ObservationWindow()
    PrimaryCriteriaLimit: ResultLimit = ResultLimit()


# ─── Inclusion rules ────────────────────────────────────────────────────────


class InclusionRule(BaseModel):
    """A named inclusion rule with criteria expression."""
    name: str = ""
    description: Optional[str] = None
    expression: CriteriaGroup


# ─── End strategies ──────────────────────────────────────────────────────────


class DateOffsetStrategy(BaseModel):
    """End date = index date + offset days."""
    DateField: str = "StartDate"  # StartDate or EndDate
    Offset: int = 0


class CustomEraStrategy(BaseModel):
    """End at the end of a continuous drug era."""
    DrugCodesetId: Optional[int] = None
    GapDays: int = 0
    Offset: int = 0
    DaysSupplyOverride: Optional[int] = None


class EndStrategy(BaseModel):
    """How cohort membership ends. Null = end of continuous observation."""
    DateOffset: Optional[DateOffsetStrategy] = None
    CustomEra: Optional[CustomEraStrategy] = None


# ─── Collapse settings ──────────────────────────────────────────────────────


class CollapseSettings(BaseModel):
    """How to collapse multiple entry events into eras."""
    CollapseType: str = "ERA"
    EraPad: int = 0


# ─── Top-level cohort expression ────────────────────────────────────────────


_PrimaryCriteria = PrimaryCriteria
_EndStrategy = EndStrategy
_CollapseSettings = CollapseSettings


class CohortExpression(BaseModel):
    """
    The complete OHDSI CIRCE cohort definition.

    This is the top-level object serialized as JSON in ATLAS cohort definitions
    and stored in the OHDSI Phenotype Library.
    """
    cdmVersionRange: Optional[str] = ">=5.0.0"
    ConceptSets: list[ConceptSetExpression] = []
    PrimaryCriteria: _PrimaryCriteria
    AdditionalCriteria: Optional[CriteriaGroup] = None
    QualifiedLimit: ResultLimit = ResultLimit(Type="First")
    ExpressionLimit: ResultLimit = ResultLimit(Type="All")
    InclusionRules: list[InclusionRule] = []
    EndStrategy: Optional[_EndStrategy] = None
    CensoringCriteria: list[_Criteria] = []
    CollapseSettings: _CollapseSettings = _CollapseSettings()

    model_config = ConfigDict(populate_by_name=True)


# ─── Rebuild forward references ─────────────────────────────────────────────

# ConceptSetExpression depends on ConceptSetExpressionDetail which is defined
# before it, so we rebuild to resolve the forward reference.
CriteriaGroup.model_rebuild()
CohortExpression.model_rebuild()
