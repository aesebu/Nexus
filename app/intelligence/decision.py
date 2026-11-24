from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

from app.schemas import (
    DecisionAlternativeResult,
    DecisionAssessmentCreate,
    DecisionAssessmentResponse,
    DecisionCriterionResult,
    DecisionRiskResult,
)


def _risk_level(exposure: int) -> str:
    if exposure <= 4:
        return "LOW"
    if exposure <= 9:
        return "MODERATE"
    if exposure <= 16:
        return "HIGH"
    return "CRITICAL"


def analyze_decision(
    request: DecisionAssessmentCreate,
    *,
    assessment_id: str,
    actor: str,
    created_at: datetime,
) -> DecisionAssessmentResponse:
    alternatives: list[tuple[Decimal, DecisionAlternativeResult]] = []
    for alternative in request.alternatives:
        criterion_results = []
        total = Decimal(0)
        for criterion in request.criteria:
            score = alternative.scores[criterion.name]
            weight = Decimal(str(criterion.weight))
            raw_contribution = weight * score
            contribution = raw_contribution.quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
            total += raw_contribution
            criterion_results.append(
                DecisionCriterionResult(
                    name=criterion.name,
                    weight=criterion.weight,
                    score=score,
                    contribution=float(contribution),
                )
            )

        risks = []
        for risk in alternative.risks:
            exposure = risk.probability * risk.impact
            risks.append(
                DecisionRiskResult(
                    name=risk.name,
                    probability=risk.probability,
                    impact=risk.impact,
                    exposure=exposure,
                    level=_risk_level(exposure),
                )
            )
        risk_score = max((risk.exposure for risk in risks), default=0)
        risk_level = _risk_level(risk_score) if risks else "NONE"
        weighted_score = total.quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP,
        )
        alternatives.append(
            (
                weighted_score,
                DecisionAlternativeResult(
                    name=alternative.name,
                    rank=0,
                    weighted_score=float(weighted_score),
                    criteria=criterion_results,
                    risk_score=risk_score,
                    risk_level=risk_level,
                    risks=risks,
                ),
            )
        )

    alternatives.sort(key=lambda result: (-result[0], result[1].name.casefold()))
    ranked = [
        result.model_copy(update={"rank": rank})
        for rank, (_score, result) in enumerate(alternatives, start=1)
    ]
    return DecisionAssessmentResponse(
        id=assessment_id,
        title=request.title,
        objective=request.objective,
        criteria=request.criteria,
        alternatives=ranked,
        created_by=actor,
        created_at=created_at,
    )
