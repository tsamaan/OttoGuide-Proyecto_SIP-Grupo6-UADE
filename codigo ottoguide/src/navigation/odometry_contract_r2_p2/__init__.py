"""R2-P2 frame semantics and covariance contract (pure, offline, fail-closed)."""

from .models import (
    P2_SCHEMA_VERSION,
    ContractValidationError,
    CovarianceEvidence,
    FrameClassification,
    FrameSemanticsContract,
    FrameVocabularyEntry,
    ProvenanceRef,
    ReadinessContract,
    ValidationContext,
    validate_covariance_matrix,
)
from .readiness import assess_p2_readiness

__all__ = [
    "P2_SCHEMA_VERSION",
    "ContractValidationError",
    "CovarianceEvidence",
    "FrameClassification",
    "FrameSemanticsContract",
    "FrameVocabularyEntry",
    "ProvenanceRef",
    "ReadinessContract",
    "ValidationContext",
    "assess_p2_readiness",
    "validate_covariance_matrix",
]
