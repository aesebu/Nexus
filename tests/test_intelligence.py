from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.intelligence.decision import analyze_decision
from app.schemas import DecisionAssessmentCreate


def test_decision_analysis_is_deterministic_and_keeps_risk_separate():
    request = DecisionAssessmentCreate.model_validate(
        {
            "title": "Deployment choice",
            "objective": "Select an option",
            "criteria": [
                {"name": "quality", "weight": 0.6},
                {"name": "cost", "weight": 0.4},
            ],
            "alternatives": [
                {
                    "name": "Alpha",
                    "scores": {"quality": 50, "cost": 80},
                    "risks": [
                        {"name": "Schedule", "probability": 2, "impact": 2}
                    ],
                },
                {
                    "name": "Beta",
                    "scores": {"quality": 90, "cost": 70},
                    "risks": [
                        {"name": "Availability", "probability": 4, "impact": 5}
                    ],
                },
            ],
        }
    )

    result = analyze_decision(
        request,
        assessment_id="assessment-1",
        actor="analyst",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert [(item.name, item.rank, item.weighted_score) for item in result.alternatives] == [
        ("Beta", 1, 82.0),
        ("Alpha", 2, 62.0),
    ]
    assert result.alternatives[0].risk_score == 20
    assert result.alternatives[0].risk_level == "CRITICAL"
    assert result.alternatives[1].risk_score == 4
    assert result.alternatives[1].risk_level == "LOW"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "title": "Bad weights",
            "objective": "Test",
            "criteria": [{"name": "quality", "weight": 0.6}],
            "alternatives": [
                {"name": "A", "scores": {"quality": 50}},
                {"name": "B", "scores": {"quality": 60}},
            ],
        },
        {
            "title": "Incomplete score matrix",
            "objective": "Test",
            "criteria": [
                {"name": "quality", "weight": 0.5},
                {"name": "cost", "weight": 0.5},
            ],
            "alternatives": [
                {"name": "A", "scores": {"quality": 50}},
                {"name": "B", "scores": {"quality": 60, "cost": 70}},
            ],
        },
    ],
)
def test_assessment_rejects_invalid_weights_and_score_matrices(payload):
    with pytest.raises(ValidationError):
        DecisionAssessmentCreate.model_validate(payload)
