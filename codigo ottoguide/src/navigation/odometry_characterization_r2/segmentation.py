"""Phase-based segmentation of NormalizedOdomSample streams (section 25).

Groups an ordered sample stream into contiguous phase runs and maps each run
to a named, valid/invalid motion segment. Never treats UNMARKED as ground
truth, never concatenates across a phase-run gap that spans an invalidated
interval, and never concatenates across a session/boot boundary (the caller
is responsible for never passing samples from more than one session/boot
into a single call).

R4B's raw recorder tags each contiguous interval with the SAME phase string
for both a first (often invalidated/superseded) attempt and a later "valid
retry" -- the string alone does not disambiguate them. This module resolves
that ambiguity by ORDER of occurrence within the session, cross-checked
against the operator's own phase-marker notes (R4B_PHASE_MARKERS.jsonl) and
verified directly against the raw contiguous-phase-run sequence: the first
R4B_FORWARD_X_2M run (5078 samples) is the NOT_EXECUTED_ALIGNMENT setup-only
attempt, the second (2338 samples, after a long R4B_STANDING_BASELINE
repositioning pause) is forward_x_valid_retry. R4B_YAW_CCW_90 occurs exactly
ONCE (left_90_first) and R4B_YAW_CW_180 occurs exactly once
(left_180_operator_corrected, mislabeled direction). R4B_YAW_CCW_90_RETURN
occurs TWICE: the first run (4924 samples) is left_90_return_invalidated
(operators reported unintended additional movement, explicitly invalidated
by a later marker), the second run (1817 samples, after an intervening
R4B_STANDING_BASELINE pause) is left_90_valid_retry_local_baseline.
"""
from src.navigation.odometry_evidence_r2.validation import EvidenceValidationError

R3C_VALID_DYNAMIC_PHASES = ("ROUTE_ACTIVE",)
R3C_STATIONARY_PHASES = ("PRE_ROUTE_STATIONARY", "POST_ROUTE_STATIONARY")

# (raw_phase_label, occurrence_index [1-based]) -> (segment_name, valid, ground_truth_mode, movement_type)
R4B_SEGMENT_MAP = {
    ("R4B_FORWARD_X_2M", 1): ("forward_x_setup_not_executed", False, "INVALID", "OPERATOR_ALIGNMENT_SETUP_ONLY"),
    ("R4B_FORWARD_X_2M", 2): ("forward_x_valid_retry", True, "BEST_EFFORT_MEASURED", "OPERATOR_FORWARD_TRANSLATION"),
    ("R4B_FORWARD_Y_1M", 1): ("forward_y", True, "BEST_EFFORT_MEASURED", "OPERATOR_FORWARD_TRANSLATION"),
    ("R4B_YAW_CCW_90", 1): ("left_90_first", True, "BEST_EFFORT_MEASURED", "OPERATOR_YAW_TURN_LEFT"),
    ("R4B_YAW_CW_180", 1): ("left_180_operator_corrected", True, "BEST_EFFORT_MEASURED", "OPERATOR_YAW_TURN_LEFT"),
    ("R4B_YAW_CCW_90_RETURN", 1): ("left_90_return_invalidated", False, "INVALID", "OPERATOR_UNINTENDED_ADDITIONAL_MOVEMENT"),
    ("R4B_YAW_CCW_90_RETURN", 2): ("left_90_valid_retry_local_baseline", True, "BEST_EFFORT_MEASURED", "OPERATOR_YAW_TURN_LEFT"),
}
R4B_NON_MOTION_PHASES = frozenset({
    "UNMARKED", "SYNC_START", "SYNC_END", "R4B_STANDING_BASELINE", "R4B_FINAL_STATIONARY",
    "R4B_CAPTURE_COMPLETE", "R4B_FORWARD_X_2M_STOP", "R4B_FORWARD_Y_1M_STOP",
    "R4B_YAW_CCW_90_STOP", "R4B_YAW_CCW_90_RETURN_STOP", "R4B_YAW_CW_180_STOP",
})
R4B_STATIONARY_PHASES = ("R4B_STANDING_BASELINE", "R4B_FINAL_STATIONARY")


def contiguous_phase_runs(samples):
    """Split an already sequence-sorted sample tuple into contiguous runs of
    identical `.phase`. Returns a list of (phase, run_samples) in stream order."""
    runs = []
    current_phase = None
    current_run = []
    for sample in samples:
        if sample.phase != current_phase:
            if current_run:
                runs.append((current_phase, tuple(current_run)))
            current_phase = sample.phase
            current_run = [sample]
        else:
            current_run.append(sample)
    if current_run:
        runs.append((current_phase, tuple(current_run)))
    return runs


def group_by_phase(samples):
    by_phase = {}
    for sample in samples:
        by_phase.setdefault(sample.phase, []).append(sample)
    return {phase: tuple(group) for phase, group in by_phase.items()}


def r4b_named_segments(samples):
    """Resolve R4B's raw phase runs into (segment_name, valid, ground_truth_mode,
    movement_type, run_samples) per the ORDER-based disambiguation documented
    above. Runs whose phase is not a recognized motion phase (UNMARKED, the
    *_STOP markers, SYNC markers, standing baselines) are skipped here --
    they are not dynamic motion segments."""
    occurrence_counts = {}
    resolved = []
    for phase, run_samples in contiguous_phase_runs(samples):
        if phase in R4B_NON_MOTION_PHASES:
            continue
        occurrence_counts[phase] = occurrence_counts.get(phase, 0) + 1
        key = (phase, occurrence_counts[phase])
        if key not in R4B_SEGMENT_MAP:
            raise EvidenceValidationError(
                f"unrecognized R4B phase occurrence {key!r}: no documented segment mapping "
                "(refusing to guess rather than silently treat an unknown motion interval as valid)"
            )
        segment_name, valid, ground_truth_mode, movement_type = R4B_SEGMENT_MAP[key]
        resolved.append((segment_name, valid, ground_truth_mode, movement_type, run_samples))
    return resolved


def r4b_stationary_windows(samples):
    by_phase = group_by_phase(samples)
    return {phase: by_phase[phase] for phase in R4B_STATIONARY_PHASES if phase in by_phase}
