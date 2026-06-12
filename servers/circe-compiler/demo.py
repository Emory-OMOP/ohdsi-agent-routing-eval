#!/usr/bin/env python3
"""
Self-contained demo of the CIRCE cohort compiler.
No external dependencies — uses only Python stdlib.

This demonstrates the core compilation logic. The production version
(in src/circe_compiler/) uses Pydantic for validation and SQLGlot for
AST-based optimization and dialect transpilation.

Run: python3 demo.py
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── Domain → OMOP table mappings ───────────────────────────────────────────

DOMAIN_TABLE_MAP = {
    "ConditionOccurrence": "condition_occurrence",
    "DrugExposure": "drug_exposure",
    "ProcedureOccurrence": "procedure_occurrence",
    "Measurement": "measurement",
    "Observation": "observation",
    "VisitOccurrence": "visit_occurrence",
    "ConditionEra": "condition_era",
    "DrugEra": "drug_era",
    "Death": "death",
    "DeviceExposure": "device_exposure",
}

DOMAIN_COLUMNS = {
    "ConditionOccurrence": {
        "concept_id": "condition_concept_id",
        "start_date": "condition_start_date",
        "end_date": "condition_end_date",
        "person_id": "person_id",
        "visit_occurrence_id": "visit_occurrence_id",
    },
    "DrugExposure": {
        "concept_id": "drug_concept_id",
        "start_date": "drug_exposure_start_date",
        "end_date": "drug_exposure_end_date",
        "person_id": "person_id",
        "visit_occurrence_id": "visit_occurrence_id",
    },
    "ProcedureOccurrence": {
        "concept_id": "procedure_concept_id",
        "start_date": "procedure_date",
        "end_date": "procedure_date",
        "person_id": "person_id",
        "visit_occurrence_id": "visit_occurrence_id",
    },
    "Measurement": {
        "concept_id": "measurement_concept_id",
        "start_date": "measurement_date",
        "end_date": "measurement_date",
        "person_id": "person_id",
        "visit_occurrence_id": "visit_occurrence_id",
    },
    "Observation": {
        "concept_id": "observation_concept_id",
        "start_date": "observation_date",
        "end_date": "observation_date",
        "person_id": "person_id",
        "visit_occurrence_id": "visit_occurrence_id",
    },
    "VisitOccurrence": {
        "concept_id": "visit_concept_id",
        "start_date": "visit_start_date",
        "end_date": "visit_end_date",
        "person_id": "person_id",
        "visit_occurrence_id": "visit_occurrence_id",
    },
    "Death": {
        "concept_id": "cause_concept_id",
        "start_date": "death_date",
        "end_date": "death_date",
        "person_id": "person_id",
    },
}


# ─── Compilation result ─────────────────────────────────────────────────────

@dataclass
class CompilationTrace:
    domain: str
    reason: str
    codeset_id: Optional[int] = None

@dataclass
class CompilationResult:
    sql: str
    segments: list
    tables_scanned: list
    trace: list
    warnings: list
    concept_set_count: int = 0
    inclusion_rule_count: int = 0
    total_concepts: int = 0


# ─── Core compiler ───────────────────────────────────────────────────────────

class CohortCompiler:
    def __init__(self, cdm_schema="cdm", results_schema="results",
                 vocab_schema="cdm", cohort_id=1):
        self.cdm = cdm_schema
        self.results = results_schema
        self.vocab = vocab_schema
        self.cohort_id = cohort_id
        self._warnings = []
        self._trace = []
        self._tables = set()

    def compile(self, definition: dict) -> CompilationResult:
        """Compile a cohort definition dict to SQL."""
        self._warnings = []
        self._trace = []
        self._tables = set()
        segments = []

        # 1. Concept sets
        cs_sql = self._build_codesets(definition.get("ConceptSets", []))
        if cs_sql:
            segments.append(cs_sql)

        # 2. Primary events
        pe_sql = self._build_primary_events(definition["PrimaryCriteria"])
        segments.append(pe_sql)

        # 3. Inclusion rules
        for i, rule in enumerate(definition.get("InclusionRules", [])):
            rule_sql = self._build_inclusion_rule(rule, i)
            segments.append(rule_sql)

        # 4. Final cohort
        final_sql = self._build_final(definition)
        segments.append(final_sql)

        full_sql = "\n\n".join(segments)

        total_concepts = sum(
            len(cs.get("expression", {}).get("items", []))
            for cs in definition.get("ConceptSets", [])
        )

        return CompilationResult(
            sql=full_sql,
            segments=segments,
            tables_scanned=sorted(self._tables),
            trace=self._trace,
            warnings=self._warnings,
            concept_set_count=len(definition.get("ConceptSets", [])),
            inclusion_rule_count=len(definition.get("InclusionRules", [])),
            total_concepts=total_concepts,
        )

    def _build_codesets(self, concept_sets: list) -> Optional[str]:
        if not concept_sets:
            return None

        unions = []
        for cs in concept_sets:
            cs_id = cs["id"]
            items = cs.get("expression", {}).get("items", [])
            self._trace.append(CompilationTrace(
                "codeset", f"concept_set_{cs_id}", cs_id
            ))

            for item in items:
                if item.get("isExcluded", False):
                    continue
                cid = item["concept"]["CONCEPT_ID"]

                # Direct concept
                unions.append(f"  SELECT {cs_id} AS codeset_id, {cid} AS concept_id")

                # Descendant expansion
                if item.get("includeDescendants", False):
                    unions.append(
                        f"  SELECT {cs_id} AS codeset_id, ca.descendant_concept_id AS concept_id\n"
                        f"  FROM {self.vocab}.concept_ancestor ca\n"
                        f"  WHERE ca.ancestor_concept_id = {cid}"
                    )

                # Mapped concepts
                if item.get("includeMapped", False):
                    unions.append(
                        f"  SELECT {cs_id} AS codeset_id, cr.concept_id_1 AS concept_id\n"
                        f"  FROM {self.vocab}.concept_relationship cr\n"
                        f"  WHERE cr.concept_id_2 = {cid}\n"
                        f"    AND cr.relationship_id = 'Maps to'\n"
                        f"    AND cr.invalid_reason IS NULL"
                    )

        if not unions:
            return None

        return (
            "-- [CIRCE:segment=codeset_build]\n"
            "CREATE TEMP TABLE codesets AS\n"
            "SELECT DISTINCT codeset_id, concept_id FROM (\n"
            + "\n  UNION ALL\n".join(unions)
            + "\n) raw_codesets;"
        )

    def _build_primary_events(self, pc: dict) -> str:
        criteria_sqls = []
        for crit in pc.get("CriteriaList", []):
            domain_name, domain_crit = self._get_active_domain(crit)
            sql = self._domain_query(domain_name, domain_crit)
            criteria_sqls.append(sql)

        events = "\n  UNION ALL\n".join(f"  ({q})" for q in criteria_sqls)

        obs = pc.get("ObservationWindow", {})
        prior = obs.get("PriorDays", 0)
        post = obs.get("PostDays", 0)
        limit = pc.get("PrimaryCriteriaLimit", {}).get("Type", "First")

        parts = [
            "-- [CIRCE:segment=primary_events]",
            "CREATE TEMP TABLE primary_events AS",
            "SELECT pe.person_id, pe.start_date, pe.end_date,",
            "       pe.visit_occurrence_id, pe.op_start_date, pe.op_end_date",
            "FROM (",
            "  SELECT e.person_id, e.start_date, e.end_date, e.visit_occurrence_id,",
            "         op.observation_period_start_date AS op_start_date,",
            "         op.observation_period_end_date AS op_end_date",
        ]

        if limit == "First":
            parts.append(
                "         , ROW_NUMBER() OVER (PARTITION BY e.person_id ORDER BY e.start_date) AS rn"
            )

        parts.extend([
            "  FROM (",
            events,
            "  ) e",
            f"  JOIN {self.cdm}.observation_period op",
            "    ON e.person_id = op.person_id",
            "    AND e.start_date >= op.observation_period_start_date",
            "    AND e.start_date <= op.observation_period_end_date",
        ])

        if prior > 0:
            parts.append(
                f"    AND e.start_date >= op.observation_period_start_date + {prior}"
            )
        if post > 0:
            parts.append(
                f"    AND e.start_date + {post} <= op.observation_period_end_date"
            )

        parts.append(") pe")
        if limit == "First":
            parts.append("WHERE pe.rn = 1;")
        else:
            parts[-1] += ";"

        return "\n".join(parts)

    def _domain_query(self, domain_name: str, crit: dict) -> str:
        table = DOMAIN_TABLE_MAP.get(domain_name)
        cols = DOMAIN_COLUMNS.get(domain_name, {})
        if not table:
            self._warnings.append(f"Unsupported domain: {domain_name}")
            return f"-- Unsupported: {domain_name}"

        self._tables.add(table)
        self._trace.append(CompilationTrace(domain_name, "primary_criteria",
                                             crit.get("CodesetId")))

        sc = cols["start_date"]
        ec = cols.get("end_date", sc)
        pc = cols["person_id"]
        cc = cols["concept_id"]
        vc = cols.get("visit_occurrence_id")
        visit_expr = f"t.{vc}" if vc else "CAST(NULL AS INTEGER)"

        codeset_id = crit.get("CodesetId")
        if codeset_id is not None:
            join = f"\n    JOIN codesets cs ON cs.concept_id = t.{cc} AND cs.codeset_id = {codeset_id}"
        else:
            join = ""

        return (
            f"SELECT t.{pc} AS person_id,\n"
            f"       t.{sc} AS start_date,\n"
            f"       COALESCE(t.{ec}, t.{sc}) AS end_date,\n"
            f"       {visit_expr} AS visit_occurrence_id\n"
            f"    FROM {self.cdm}.{table} t{join}"
        )

    def _build_inclusion_rule(self, rule: dict, index: int) -> str:
        name = rule.get("name", f"rule_{index}")
        expr = rule.get("expression", {})
        group_type = expr.get("Type", "ALL")

        self._trace.append(CompilationTrace("inclusion_rule", f"rule_{index}_{name}"))

        correlated_parts = []
        for cc in expr.get("CriteriaList", []):
            sub = self._build_correlated(cc)
            correlated_parts.append(sub)

        # Demographic criteria
        for dc in expr.get("DemographicCriteriaList", []):
            sub = self._build_demographic(dc)
            correlated_parts.append(sub)

        if not correlated_parts:
            where = "1=1"
        elif group_type == "ALL":
            where = "\n  AND ".join(correlated_parts)
        elif group_type == "ANY":
            where = "\n  OR ".join(f"({p})" for p in correlated_parts)
        else:
            where = "\n  AND ".join(correlated_parts)

        prev_table = f"inclusion_rule_{index - 1}" if index > 0 else "primary_events"

        return (
            f"-- [CIRCE:segment=inclusion_rule, rule_index={index}, rule_name=\"{name}\"]\n"
            f"CREATE TEMP TABLE inclusion_rule_{index} AS\n"
            f"SELECT pe.person_id, pe.start_date, pe.end_date,\n"
            f"       pe.visit_occurrence_id, pe.op_start_date, pe.op_end_date\n"
            f"FROM {prev_table} pe\n"
            f"WHERE {where};"
        )

    def _build_correlated(self, cc: dict) -> str:
        criteria = cc.get("Criteria", {})
        domain_name, domain_crit = self._get_active_domain(criteria)
        table = DOMAIN_TABLE_MAP.get(domain_name)
        cols = DOMAIN_COLUMNS.get(domain_name, {})

        if not table:
            return "1=1"

        self._tables.add(table)

        sc = cols["start_date"]
        cc_col = cols["concept_id"]
        pc = cols["person_id"]

        conditions = [f"a.{pc} = pe.person_id"]

        codeset_id = domain_crit.get("CodesetId")
        if codeset_id is not None:
            conditions.append(
                f"a.{cc_col} IN (SELECT concept_id FROM codesets WHERE codeset_id = {codeset_id})"
            )

        # Temporal window
        window = cc.get("StartWindow", {})
        start = window.get("Start", {})
        end = window.get("End", {})

        s_days = start.get("Days")
        s_coeff = start.get("Coeff", 1)
        e_days = end.get("Days")
        e_coeff = end.get("Coeff", 1)

        if s_days is not None:
            offset = s_days * s_coeff
            if s_coeff == -1:
                conditions.append(f"a.{sc} >= (pe.start_date - {s_days})")
            else:
                conditions.append(f"a.{sc} >= (pe.start_date + {offset})")

        if e_days is not None:
            offset = e_days * e_coeff
            if e_coeff == -1:
                conditions.append(f"a.{sc} <= (pe.start_date - {e_days})")
            else:
                conditions.append(f"a.{sc} <= (pe.start_date + {offset})")

        # Observation period
        if not cc.get("IgnoreObservationPeriod", False):
            conditions.append(
                f"a.{sc} >= pe.op_start_date AND a.{sc} <= pe.op_end_date"
            )

        where = " AND ".join(conditions)

        # Occurrence
        occ = cc.get("Occurrence", {})
        occ_type = occ.get("Type", 0)
        count = occ.get("Count", 0)
        distinct = "DISTINCT " if occ.get("IsDistinct") else ""

        subquery = f"SELECT COUNT({distinct}*) FROM {self.cdm}.{table} a WHERE {where}"

        ops = {0: ">=", 1: "<=", 2: "="}
        op = ops.get(occ_type, ">=")

        return f"({subquery}) {op} {count}"

    def _build_demographic(self, dc: dict) -> str:
        conditions = ["p.person_id = pe.person_id"]

        age = dc.get("Age")
        if age and age.get("Op"):
            ops = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "="}
            op = ops.get(age["Op"], ">=")
            conditions.append(
                f"EXTRACT(YEAR FROM pe.start_date) - p.year_of_birth {op} {age['Value']}"
            )

        gender = dc.get("Gender")
        if gender:
            ids = ", ".join(str(g["CONCEPT_ID"]) for g in gender)
            conditions.append(f"p.gender_concept_id IN ({ids})")

        race = dc.get("Race")
        if race:
            ids = ", ".join(str(r["CONCEPT_ID"]) for r in race)
            conditions.append(f"p.race_concept_id IN ({ids})")

        where = " AND ".join(conditions)
        return f"EXISTS (SELECT 1 FROM {self.cdm}.person p WHERE {where})"

    def _build_final(self, definition: dict) -> str:
        n_rules = len(definition.get("InclusionRules", []))
        source = f"inclusion_rule_{n_rules - 1}" if n_rules > 0 else "primary_events"

        end_strategy = definition.get("EndStrategy")
        if end_strategy and end_strategy.get("DateOffset"):
            off = end_strategy["DateOffset"]
            field = "src.start_date" if off.get("DateField") == "StartDate" else "src.end_date"
            offset = off.get("Offset", 0)
            end_expr = f"({field} + {offset})" if offset else field
        else:
            end_expr = "src.op_end_date"

        qual_limit = definition.get("QualifiedLimit", {}).get("Type", "First")
        era_pad = definition.get("CollapseSettings", {}).get("EraPad", 0)

        if qual_limit == "First":
            return (
                f"-- [CIRCE:segment=final_cohort, era_pad={era_pad}]\n"
                f"INSERT INTO {self.results}.cohort\n"
                f"SELECT {self.cohort_id} AS cohort_definition_id,\n"
                f"       src.person_id AS subject_id,\n"
                f"       src.start_date AS cohort_start_date,\n"
                f"       {end_expr} AS cohort_end_date\n"
                f"FROM (\n"
                f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY start_date) AS rn\n"
                f"  FROM {source}\n"
                f") src\n"
                f"WHERE src.rn = 1;"
            )
        else:
            return (
                f"-- [CIRCE:segment=final_cohort, era_pad={era_pad}]\n"
                f"INSERT INTO {self.results}.cohort\n"
                f"SELECT {self.cohort_id} AS cohort_definition_id,\n"
                f"       src.person_id AS subject_id,\n"
                f"       src.start_date AS cohort_start_date,\n"
                f"       {end_expr} AS cohort_end_date\n"
                f"FROM {source} src;"
            )

    def _get_active_domain(self, criteria: dict) -> tuple:
        for key in DOMAIN_TABLE_MAP:
            if key in criteria:
                return (key, criteria[key])
        raise ValueError(f"No active domain in criteria: {list(criteria.keys())}")


# ─── Validator ───────────────────────────────────────────────────────────────

def validate(definition: dict) -> dict:
    """Validate a cohort definition for semantic correctness."""
    issues = []
    valid_ids = {cs["id"] for cs in definition.get("ConceptSets", [])}

    # Check primary criteria exist
    pc = definition.get("PrimaryCriteria", {})
    if not pc.get("CriteriaList"):
        issues.append({"severity": "error", "code": "NO_PRIMARY_CRITERIA",
                       "message": "No primary criteria defined"})

    # Check codeset references
    for i, crit in enumerate(pc.get("CriteriaList", [])):
        for domain in DOMAIN_TABLE_MAP:
            if domain in crit:
                csid = crit[domain].get("CodesetId")
                if csid is not None and csid not in valid_ids:
                    issues.append({
                        "severity": "error",
                        "code": "INVALID_CODESET_REF",
                        "message": f"Primary criterion {i} refs CodesetId={csid}, valid: {sorted(valid_ids)}"
                    })

    # Check inclusion rules
    for i, rule in enumerate(definition.get("InclusionRules", [])):
        for j, cc in enumerate(rule.get("expression", {}).get("CriteriaList", [])):
            criteria = cc.get("Criteria", {})
            for domain in DOMAIN_TABLE_MAP:
                if domain in criteria:
                    csid = criteria[domain].get("CodesetId")
                    if csid is not None and csid not in valid_ids:
                        issues.append({
                            "severity": "error",
                            "code": "INVALID_CODESET_REF",
                            "message": f"Rule '{rule.get('name')}' criterion {j} refs CodesetId={csid}"
                        })

    # Check empty concept sets
    for cs in definition.get("ConceptSets", []):
        items = cs.get("expression", {}).get("items", [])
        if not items:
            issues.append({
                "severity": "warning",
                "code": "EMPTY_CONCEPT_SET",
                "message": f"Concept set '{cs['name']}' (id={cs['id']}) is empty"
            })

    has_errors = any(i["severity"] == "error" for i in issues)
    return {"is_valid": not has_errors, "issues": issues}


# ─── Demo ────────────────────────────────────────────────────────────────────

def main():
    fixture_path = Path(__file__).parent / "tests" / "fixtures" / "t2dm_metformin_no_hf.json"
    with open(fixture_path) as f:
        definition = json.load(f)

    print("=" * 70)
    print("CIRCE Compiler Demo — OHDSI Cohort Definition → SQL")
    print("=" * 70)
    print()

    # 1. Describe what we're compiling
    print(f"Cohort: Type 2 Diabetes with Metformin, excluding Heart Failure")
    print(f"CDM Version: {definition['cdmVersionRange']}")
    print(f"Concept Sets: {len(definition['ConceptSets'])}")
    for cs in definition["ConceptSets"]:
        items = cs.get("expression", {}).get("items", [])
        desc = [f"  • {item['concept']['CONCEPT_NAME']} ({item['concept']['CONCEPT_ID']})"
                + (" + descendants" if item.get("includeDescendants") else "")
                for item in items]
        print(f"  [{cs['id']}] {cs['name']}: {len(items)} concept(s)")
        for d in desc:
            print(d)

    print(f"Inclusion Rules: {len(definition['InclusionRules'])}")
    for rule in definition["InclusionRules"]:
        print(f"  • {rule['name']}")
    print()

    # 2. Validate
    print("─── Validation ───")
    val = validate(definition)
    print(f"Valid: {val['is_valid']}")
    for issue in val["issues"]:
        print(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
    if not val["issues"]:
        print("  No issues found")
    print()

    # 3. Compile
    print("─── Compilation ───")
    compiler = CohortCompiler(cdm_schema="cdm", results_schema="results", cohort_id=42)
    result = compiler.compile(definition)

    print(f"SQL Segments: {len(result.segments)}")
    print(f"Tables Scanned: {', '.join(result.tables_scanned)}")
    print(f"Concept Sets: {result.concept_set_count}")
    print(f"Inclusion Rules: {result.inclusion_rule_count}")
    print(f"Total Source Concepts: {result.total_concepts}")
    print()

    print("─── Compilation Trace ───")
    for t in result.trace:
        cs_info = f" (codeset_id={t.codeset_id})" if t.codeset_id is not None else ""
        print(f"  [{t.domain}] {t.reason}{cs_info}")
    print()

    if result.warnings:
        print("─── Warnings ───")
        for w in result.warnings:
            print(f"  ! {w}")
        print()

    # 4. Print generated SQL
    print("─── Generated SQL ───")
    print()
    for i, segment in enumerate(result.segments):
        print(f"/* ── Segment {i + 1} of {len(result.segments)} ── */")
        print(segment)
        print()

    # 5. Validation of invalid definition
    print("─── Invalid Definition Test ───")
    broken = json.loads(json.dumps(definition))
    broken["PrimaryCriteria"]["CriteriaList"][0]["ConditionOccurrence"]["CodesetId"] = 999
    val2 = validate(broken)
    print(f"Valid: {val2['is_valid']}")
    for issue in val2["issues"]:
        print(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
    print()

    print("=" * 70)
    print("Demo complete. The production version adds:")
    print("  - Pydantic models for full CIRCE JSON schema validation")
    print("  - SQLGlot AST-based optimization and dialect transpilation")
    print("  - MCP server (tools: compile, validate, dry_run, transpile)")
    print("  - FastOMOP/OMCP ecosystem compatibility")
    print("=" * 70)

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
