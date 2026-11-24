# Intelligence Engine

The Intelligence Engine MVP provides reproducible, human-reviewed multi-criteria
decision support. It is deterministic and does not call an AI provider. Apply
schema changes with `alembic upgrade head`.

## Permissions

| Permission | Actions |
|---|---|
| `nexus.intelligence.analyze` | Create and persist an assessment |
| `nexus.intelligence.read` | List and retrieve tenant assessments |

Owner and operator roles can analyze and read; viewers can read. Assessment
records are shared within a tenant.

## Create an assessment

```http
POST /api/v1/intelligence/assessments
Authorization: Bearer <JWT>
X-Tenant-ID: <tenant-id>
Content-Type: application/json

{
  "title": "Deployment choice",
  "objective": "Choose a deployment option for the service",
  "criteria": [
    {"name": "security", "weight": 0.7},
    {"name": "cost", "weight": 0.3}
  ],
  "alternatives": [
    {
      "name": "Managed",
      "scores": {"security": 90, "cost": 60},
      "risks": [
        {"name": "Vendor lock-in", "probability": 3, "impact": 4}
      ]
    },
    {
      "name": "Self-hosted",
      "scores": {"security": 80, "cost": 75},
      "risks": []
    }
  ]
}
```

Weights must sum to 1. Scores are integers from 0 to 100. Probabilities and
impacts are integers from 1 to 5. The response includes each criterion's
contribution, a weighted score, rank, and risk breakdown. The weighted score
determines rank; risk is presented separately and is not converted into an
arbitrary score penalty.

Retrieve assessment summaries at `GET /api/v1/intelligence/assessments` and a
full input/result snapshot at `GET /api/v1/intelligence/assessments/{id}`.

Assessments preserve user-submitted objectives and risk data in the database.
Audit events contain only assessment ID, counts, and calculation method.
Review access controls and retention requirements before storing sensitive
decision material.

This feature does not make predictions, provide an AI-generated recommendation,
approve a decision, or execute an alternative. The human decision owner must
review the inputs and results.
