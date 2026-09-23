"""Integration: key analysis, documented synthetic bridge, unified model."""

from .keys import (
    KeyAnalysis,
    KeyCandidate,
    VERDICT_COINCIDENTAL,
    VERDICT_NONE,
    VERDICT_VALID,
    analyze_key_candidates,
    describe_key,
    demographic_consistency,
)
from .synthetic import (
    SyntheticLayer,
    EXERCISE_TO_WORKOUT_TYPE,
    SYNTHETIC_COMPONENTS,
    SYNTHETIC_METHOD,
    synthesize_activity_calendar,
    synthetic_ground_truth_note,
    validate_synthetic_layer,
)
from .integrator import IntegrationResult, integrate_sources, integration_summary_frame

__all__ = [
    "KeyAnalysis",
    "KeyCandidate",
    "VERDICT_COINCIDENTAL",
    "VERDICT_NONE",
    "VERDICT_VALID",
    "analyze_key_candidates",
    "describe_key",
    "demographic_consistency",
    "SyntheticLayer",
    "EXERCISE_TO_WORKOUT_TYPE",
    "SYNTHETIC_COMPONENTS",
    "SYNTHETIC_METHOD",
    "synthesize_activity_calendar",
    "synthetic_ground_truth_note",
    "validate_synthetic_layer",
    "IntegrationResult",
    "integrate_sources",
    "integration_summary_frame",
]
