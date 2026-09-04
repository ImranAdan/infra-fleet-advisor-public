from dataclasses import dataclass
from typing import Literal

IntentEvaluationStatus = Literal["satisfied", "divergent", "declared_unverified"]


@dataclass(frozen=True, slots=True)
class IntentEvaluation:
    document_id: str
    proposition_id: str
    category: str
    priority: str | None
    statement: str
    check_key: str | None
    status: IntentEvaluationStatus
    evidence_ids: tuple[str, ...]
    reason: str
