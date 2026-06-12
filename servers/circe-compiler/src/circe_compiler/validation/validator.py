"""
Validation service for OHDSI cohort definitions.

Goes beyond JSON schema validation to catch semantic errors:
  - Concept sets referencing non-existent codeset IDs
  - Temporal logic that's impossible to satisfy
  - Missing required fields that CIRCE silently ignores
  - Complexity warnings for definitions likely to cause performance issues
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from circe_compiler.models.cohort_expression import (
    CohortExpression,
    CriteriaGroup,
    CorelatedCriteria,
)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    severity: Severity
    code: str
    message: str
    path: str = ""  # JSON path to the problematic element


@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    summary: str = ""

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]


class CohortValidator:
    """Validates a CohortExpression for semantic correctness."""

    def validate(self, expr: CohortExpression) -> ValidationResult:
        issues: list[ValidationIssue] = []

        # 1. CDM version check
        if expr.cdmVersionRange and "5.0" not in expr.cdmVersionRange and "5" not in expr.cdmVersionRange:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="CDM_VERSION",
                message=f"CDM version range '{expr.cdmVersionRange}' may not be supported",
                path="cdmVersionRange",
            ))

        # 2. Primary criteria must exist
        if not expr.PrimaryCriteria.CriteriaList:
            issues.append(ValidationIssue(
                severity=Severity.ERROR,
                code="NO_PRIMARY_CRITERIA",
                message="PrimaryCriteria.CriteriaList is empty — no entry events defined",
                path="PrimaryCriteria.CriteriaList",
            ))

        # 3. Validate each primary criterion has an active domain
        for i, crit in enumerate(expr.PrimaryCriteria.CriteriaList):
            try:
                domain_name, domain_crit = crit.get_active()
            except ValueError:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    code="EMPTY_CRITERIA",
                    message=f"Primary criterion {i} has no active domain",
                    path=f"PrimaryCriteria.CriteriaList[{i}]",
                ))
                continue

            # Check CodesetId references
            codeset_id = getattr(domain_crit, "CodesetId", None)
            if codeset_id is not None:
                valid_ids = {cs.id for cs in expr.ConceptSets}
                if codeset_id not in valid_ids:
                    issues.append(ValidationIssue(
                        severity=Severity.ERROR,
                        code="INVALID_CODESET_REF",
                        message=(
                            f"Primary criterion {i} ({domain_name}) references "
                            f"CodesetId={codeset_id} which doesn't exist in ConceptSets. "
                            f"Available IDs: {sorted(valid_ids)}"
                        ),
                        path=f"PrimaryCriteria.CriteriaList[{i}].{domain_name}.CodesetId",
                    ))

        # 4. Validate concept sets
        for cs in expr.ConceptSets:
            if not cs.expression or not cs.expression.items:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    code="EMPTY_CONCEPT_SET",
                    message=f"Concept set '{cs.name}' (id={cs.id}) has no items",
                    path=f"ConceptSets[{cs.id}]",
                ))
                continue

            # Check for concept sets that are entirely excluded
            all_excluded = all(item.isExcluded for item in cs.expression.items)
            if all_excluded:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    code="ALL_EXCLUDED_CONCEPT_SET",
                    message=(
                        f"Concept set '{cs.name}' (id={cs.id}) has all items excluded — "
                        f"this will match zero concepts"
                    ),
                    path=f"ConceptSets[{cs.id}]",
                ))

            # Large concept set warning
            n_items = len(cs.expression.items)
            n_descendants = sum(1 for i in cs.expression.items if i.includeDescendants)
            if n_items > 100:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    code="LARGE_CONCEPT_SET",
                    message=(
                        f"Concept set '{cs.name}' has {n_items} items. "
                        f"Large concept sets may cause performance issues."
                    ),
                    path=f"ConceptSets[{cs.id}]",
                ))
            if n_descendants > 50:
                issues.append(ValidationIssue(
                    severity=Severity.WARNING,
                    code="MANY_DESCENDANT_EXPANSIONS",
                    message=(
                        f"Concept set '{cs.name}' has {n_descendants} descendant expansions. "
                        f"This can produce very large intermediate result sets."
                    ),
                    path=f"ConceptSets[{cs.id}]",
                ))

        # 5. Validate inclusion rules
        all_codeset_ids = {cs.id for cs in expr.ConceptSets}
        for i, rule in enumerate(expr.InclusionRules):
            self._validate_criteria_group(
                rule.expression,
                all_codeset_ids,
                f"InclusionRules[{i}]({rule.name})",
                issues,
            )

        # 6. Validate additional criteria
        if expr.AdditionalCriteria:
            self._validate_criteria_group(
                expr.AdditionalCriteria,
                all_codeset_ids,
                "AdditionalCriteria",
                issues,
            )

        # 7. Validate end strategy
        if expr.EndStrategy:
            if expr.EndStrategy.CustomEra:
                era = expr.EndStrategy.CustomEra
                if era.DrugCodesetId is not None and era.DrugCodesetId not in all_codeset_ids:
                    issues.append(ValidationIssue(
                        severity=Severity.ERROR,
                        code="INVALID_ERA_CODESET",
                        message=(
                            f"CustomEra end strategy references DrugCodesetId={era.DrugCodesetId} "
                            f"which doesn't exist in ConceptSets"
                        ),
                        path="EndStrategy.CustomEra.DrugCodesetId",
                    ))

        # 8. Observation window sanity
        obs = expr.PrimaryCriteria.ObservationWindow
        if obs.PriorDays > 3650:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="EXTREME_PRIOR_OBSERVATION",
                message=(
                    f"PriorDays={obs.PriorDays} (>{obs.PriorDays // 365} years) — "
                    f"this will exclude most patients"
                ),
                path="PrimaryCriteria.ObservationWindow.PriorDays",
            ))

        # Build result
        has_errors = any(i.severity == Severity.ERROR for i in issues)
        n_errors = sum(1 for i in issues if i.severity == Severity.ERROR)
        n_warnings = sum(1 for i in issues if i.severity == Severity.WARNING)

        return ValidationResult(
            is_valid=not has_errors,
            issues=issues,
            summary=f"{n_errors} errors, {n_warnings} warnings",
        )

    def _validate_criteria_group(
        self,
        group: CriteriaGroup,
        valid_codeset_ids: set[int],
        path: str,
        issues: list[ValidationIssue],
    ):
        """Recursively validate a CriteriaGroup."""
        for j, cc in enumerate(group.CriteriaList):
            try:
                domain_name, domain_crit = cc.Criteria.get_active()
            except ValueError:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    code="EMPTY_CORRELATED_CRITERIA",
                    message=f"Correlated criterion {j} in {path} has no active domain",
                    path=f"{path}.CriteriaList[{j}]",
                ))
                continue

            codeset_id = getattr(domain_crit, "CodesetId", None)
            if codeset_id is not None and codeset_id not in valid_codeset_ids:
                issues.append(ValidationIssue(
                    severity=Severity.ERROR,
                    code="INVALID_CODESET_REF",
                    message=(
                        f"Correlated criterion {j} in {path} ({domain_name}) "
                        f"references CodesetId={codeset_id} not in ConceptSets"
                    ),
                    path=f"{path}.CriteriaList[{j}].{domain_name}.CodesetId",
                ))

            # Validate window makes sense
            self._validate_window(cc, f"{path}.CriteriaList[{j}]", issues)

        # Recurse into nested groups
        for k, sub_group in enumerate(group.Groups):
            self._validate_criteria_group(
                sub_group, valid_codeset_ids, f"{path}.Groups[{k}]", issues
            )

    def _validate_window(
        self, cc: CorelatedCriteria, path: str, issues: list[ValidationIssue]
    ):
        """Check for impossible temporal windows."""
        w = cc.StartWindow
        start_days = (w.Start.Days or 0) * w.Start.Coeff
        end_days = (w.End.Days or 0) * w.End.Coeff

        # If start > end, the window is impossible
        if start_days > end_days:
            issues.append(ValidationIssue(
                severity=Severity.WARNING,
                code="IMPOSSIBLE_WINDOW",
                message=(
                    f"Temporal window at {path} may be impossible: "
                    f"start offset ({start_days}) > end offset ({end_days})"
                ),
                path=f"{path}.StartWindow",
            ))
