"""L3 用户画像候选的领域类型与技术中立契约。"""

from .contracts import PersonaStore
from .activation_policy import (
    PersonaActivationAction,
    PersonaActivationDecision,
    PersonaActivationReason,
    PersonaEvidenceSummary,
    PersonaRiskAssessment,
    decide_persona_activation,
)
from .models import (
    PersonaBasis,
    PersonaGenerationAudit,
    PersonaKind,
    PersonaLifecycleAction,
    PersonaLifecycleEvent,
    PersonaMemory,
    PersonaResolvedSource,
    PersonaReview,
    PersonaReviewDecision,
    PersonaSource,
    PersonaSourceLayer,
    PersonaStatus,
)
from .proposals import (
    PersonaProposal,
    PersonaProposalError,
    PersonaProposalEvidence,
    PersonaProposalInput,
    PersonaProposalProducer,
)

__all__ = [
    "PersonaActivationAction", "PersonaActivationDecision", "PersonaActivationReason",
    "PersonaEvidenceSummary", "PersonaRiskAssessment", "decide_persona_activation",
    "PersonaBasis", "PersonaGenerationAudit", "PersonaKind",
    "PersonaLifecycleAction", "PersonaLifecycleEvent", "PersonaMemory",
    "PersonaResolvedSource", "PersonaReview", "PersonaReviewDecision",
    "PersonaSource", "PersonaSourceLayer", "PersonaStatus", "PersonaStore",
    "PersonaProposal", "PersonaProposalError", "PersonaProposalEvidence",
    "PersonaProposalInput", "PersonaProposalProducer",
]
