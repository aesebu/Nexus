# Phase 08 - Intelligence Engine

| Field | Value |
|---|---|
| Phase | 08 |
| Name | Intelligence Engine |
| Deliverable | Deterministic decision support and risk assessment |
| Status | VALIDATED |
| Change ID | NEXUS-PHASE-08 |
| Version | 1.0 |

## Specification

Phase 08 MVP accepts a decision objective, weighted criteria, scored
alternatives, and explicit risk factors. It produces a reproducible weighted
ranking and a separate 5x5 risk assessment. Inputs and results are persisted
for review within the authenticated tenant.

## Components

| Component | Implementation | Purpose |
|---|---|---|
| Assessment record | `IntelligenceAssessment` | Persist input/result snapshots and ownership |
| Decision calculation | `app.intelligence.decision` | Decimal-based weighted scoring and stable ranking |
| Risk calculation | 5x5 probability/impact matrix | Classify each risk and report highest per-option exposure |
| Assessment API | `/api/v1/intelligence/assessments` | Create, list, and retrieve tenant assessments |
| Authorization | `nexus.intelligence.analyze/read` | Separate assessment creation from report access |
| Audit | `AuditEvent` | Record counts and calculation method, not decision text |

## Calculation rules

- Each criterion weight is greater than 0 and at most 1; weights must sum to 1
  within a tolerance of 0.000001.
- Each alternative supplies exactly one integer score per criterion in the
  range 0–100.
- Weighted score is the sum of `criterion weight × alternative score`, rounded
  to four decimal places.
- Results sort by descending weighted score, then case-insensitive alternative
  name. Rank positions are unique and deterministic.
- Risk exposure is `probability × impact`, with both inputs on a 1–5 scale.
  Levels are 1–4 LOW, 5–9 MODERATE, 10–16 HIGH, and 17–25 CRITICAL.
- An alternative's `risk_score` is its highest individual exposure (0/NONE
  when it has no declared risks). Risk does not change weighted ranking.

## Security and decision boundary

- Assessment records are tenant-scoped and readable by authorized tenant roles.
- `nexus.intelligence.analyze` is required to create assessments;
  `nexus.intelligence.read` is required to list/read them.
- Audit events exclude objectives, criteria, alternatives, scores, and risk
  descriptions.
- This calculation is decision support, not a prediction, general risk
  classifier, or governance policy.
- NEXUS does not select, approve, or execute an alternative. A human decision
  owner remains responsible for the outcome.
- Assessment input and result snapshots are stored in the application database
  without application-level encryption.

## Acceptance criteria

| ID | Criterion | Evidence |
|---|---|---|
| IE-01 | Weights and score matrices are validated before persistence | Schema/API tests |
| IE-02 | Weighted scores and stable ranking are reproducible | Unit tests |
| IE-03 | Risk exposure and level are calculated independently | Unit tests |
| IE-04 | Assessment records are tenant-scoped | API tests |
| IE-05 | Read and analyze permissions are enforced | API tests |
| IE-06 | Audit evidence omits decision content | API tests |
| IE-07 | Migration applies and rolls back on supported SQLite path | Migration check |

## Out of scope

AI-generated recommendations, predictive modeling, pattern recognition over
datasets, automated policy risk scoring, external data ingestion, and
automated decision execution are not included in this MVP.
