"""MVP-ODOM-TF-R1 / R1A offline readiness gate.

Pure, deterministic, fail-closed assessment of whether the available offline
evidence and contract are sufficient to *prepare* `/odom` and the
`odom -> base_link` TF transform. This module does NOT build ROS messages,
does NOT publish topics, and does NOT declare physical readiness.

Hard invariants (see docs/Arquitectura/ODOM_TF_R1_OFFLINE_READINESS_CONTRACT.md):

  * No ROS (rclpy / nav_msgs / geometry_msgs / tf2_ros), no DDS, no Unitree
    SDK, no sockets, no network, no wall-clock reads inside any function.
  * `nav2_ready` is ALWAYS false in this checkpoint.
  * `odom_publication_ready` and `odom_to_base_link_tf_ready` are false whenever
    any BLOCKER is present; with the current stationary physical evidence they
    are always false.
  * The absence of evidence never silently becomes a permissive default: every
    missing piece is modeled as an explicit BLOCKER (or WARNING/OBSERVATION).

R1A hardening: the gate now validates the SHAPE of both inputs (a malformed
contract or candidate fails closed with a stable blocker instead of raising),
checks contract/evidence COHERENCE (a boolean flag can never override the typed
evidence -- covariance/IMU/dynamic contradictions block), rejects unfiltered
mixed-channel sequences, and verifies receipt-monotonic ordering per channel.
Nothing here trusts a bare `valid=True` or a bare contract boolean.
"""
import math
from dataclasses import dataclass, field

from .validation import ALLOWED_SOURCE_CHANNELS

# --- severities (deterministic, ordered most-severe first) -------------------

BLOCKER = "BLOCKER"
WARNING = "WARNING"
OBSERVATION = "OBSERVATION"

_SEVERITY_RANK = {BLOCKER: 0, WARNING: 1, OBSERVATION: 2}

# --- blocker codes (stable identifiers, never free text for the code) --------

# Input fail-closed
EVIDENCE_CONTRACT_INVALID = "EVIDENCE_CONTRACT_INVALID"
CANDIDATE_STRUCTURE_INVALID = "CANDIDATE_STRUCTURE_INVALID"
EMPTY_OR_INVALID_SEQUENCE = "EMPTY_OR_INVALID_SEQUENCE"

# Contract-driven gaps
DYNAMIC_MOTION_EVIDENCE_MISSING = "DYNAMIC_MOTION_EVIDENCE_MISSING"
SOURCE_CHANNEL_ARBITRATION_UNRESOLVED = "SOURCE_CHANNEL_ARBITRATION_UNRESOLVED"
SOURCE_FRAME_SEMANTICS_UNVERIFIED = "SOURCE_FRAME_SEMANTICS_UNVERIFIED"
CHILD_FRAME_ID_UNRESOLVED = "CHILD_FRAME_ID_UNRESOLVED"
AXIS_CONVENTION_UNVERIFIED = "AXIS_CONVENTION_UNVERIFIED"
SCALE_AND_SIGN_UNVERIFIED = "SCALE_AND_SIGN_UNVERIFIED"
MESSAGE_TIMESTAMP_ZERO = "MESSAGE_TIMESTAMP_ZERO"
RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED = "RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED"
COVARIANCE_UNAVAILABLE = "COVARIANCE_UNAVAILABLE"
IMU_CROSSCHECK_UNAVAILABLE = "IMU_CROSSCHECK_UNAVAILABLE"
RESET_AND_DISCONTINUITY_BEHAVIOR_UNVERIFIED = "RESET_AND_DISCONTINUITY_BEHAVIOR_UNVERIFIED"

# Coherence (R1A): fire only when a contract ASSERTS something the typed
# evidence contradicts, or when the sequence itself is incoherent.
AUTHORITATIVE_CHANNEL_NOT_PRESENT = "AUTHORITATIVE_CHANNEL_NOT_PRESENT"
MIXED_CHANNEL_SEQUENCE_REQUIRES_FILTERING = "MIXED_CHANNEL_SEQUENCE_REQUIRES_FILTERING"
RECEIPT_MONOTONIC_ORDER_INVALID = "RECEIPT_MONOTONIC_ORDER_INVALID"
COVARIANCE_EVIDENCE_CONTRADICTION = "COVARIANCE_EVIDENCE_CONTRADICTION"
IMU_EVIDENCE_CONTRADICTION = "IMU_EVIDENCE_CONTRADICTION"
DYNAMIC_EVIDENCE_CONTRADICTION = "DYNAMIC_EVIDENCE_CONTRADICTION"

# Non-blocking notes
RATE_DIFFERENCE_BETWEEN_CHANNELS = "RATE_DIFFERENCE_BETWEEN_CHANNELS"
IMU_ZERO_IN_CAPTURE = "IMU_ZERO_IN_CAPTURE"
MULTIPLE_CANDIDATE_CHANNELS_PRESENT = "MULTIPLE_CANDIDATE_CHANNELS_PRESENT"

# Canonical ordering of every code the gate can emit. Reports sort by
# (severity_rank, index-in-this-tuple, code-text, message) so output is stable
# regardless of check execution order. Any code NOT listed here still sorts
# deterministically by its own text (Fix H).
_CODE_ORDER = (
    # input fail-closed (hardest first)
    EVIDENCE_CONTRACT_INVALID,
    CANDIDATE_STRUCTURE_INVALID,
    EMPTY_OR_INVALID_SEQUENCE,
    # the eleven current-fixture gaps, in their required published order
    DYNAMIC_MOTION_EVIDENCE_MISSING,
    SOURCE_CHANNEL_ARBITRATION_UNRESOLVED,
    SOURCE_FRAME_SEMANTICS_UNVERIFIED,
    CHILD_FRAME_ID_UNRESOLVED,
    AXIS_CONVENTION_UNVERIFIED,
    SCALE_AND_SIGN_UNVERIFIED,
    MESSAGE_TIMESTAMP_ZERO,
    RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED,
    COVARIANCE_UNAVAILABLE,
    IMU_CROSSCHECK_UNAVAILABLE,
    RESET_AND_DISCONTINUITY_BEHAVIOR_UNVERIFIED,
    # coherence blockers (after the gaps)
    AUTHORITATIVE_CHANNEL_NOT_PRESENT,
    MIXED_CHANNEL_SEQUENCE_REQUIRES_FILTERING,
    RECEIPT_MONOTONIC_ORDER_INVALID,
    COVARIANCE_EVIDENCE_CONTRADICTION,
    IMU_EVIDENCE_CONTRADICTION,
    DYNAMIC_EVIDENCE_CONTRADICTION,
    # non-blocking notes
    RATE_DIFFERENCE_BETWEEN_CHANNELS,
    IMU_ZERO_IN_CAPTURE,
    MULTIPLE_CANDIDATE_CHANNELS_PRESENT,
)

_CODE_INDEX = {code: i for i, code in enumerate(_CODE_ORDER)}
# Unknown codes sort after all known codes; ties broken by the code text itself
# (Fix H: never rely on insertion order).
_UNKNOWN_CODE_INDEX = len(_CODE_ORDER)


def _code_index(code):
    return _CODE_INDEX.get(code, _UNKNOWN_CODE_INDEX)


@dataclass(frozen=True)
class OdomTfBlocker:
    """One reason readiness is withheld (or a non-blocking note).

    `severity` is BLOCKER / WARNING / OBSERVATION. Only BLOCKER entries gate
    publication; WARNING and OBSERVATION are recorded for traceability and
    never silently suppressed.
    """
    code: str
    severity: str
    message: str

    def to_dict(self):
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass(frozen=True)
class OdomTfEvidenceContract:
    """Explicit statement of what has been established offline.

    Every field defaults to the CONSERVATIVE (unverified / unavailable) value.
    Nothing here is inferred from the candidate samples: the caller must
    positively assert that a given gap has been resolved. Anything left at its
    default blocks publication. This is the mechanism that prevents "absence of
    evidence" from silently becoming a permissive default.

    R1A: every boolean field must be an actual `bool` (not a truthy string /
    int). `assess_odom_tf_readiness` validates this and fails closed on a
    malformed contract rather than trusting a truthy value.
    """
    dynamic_motion_evidence_available: bool = False
    source_channel_arbitration_resolved: bool = False
    authoritative_source_channel: "str | None" = None
    source_frame_semantics_verified: bool = False
    child_frame_id_resolved: bool = False
    resolved_child_frame_id: "str | None" = None
    axis_convention_verified: bool = False
    scale_and_sign_verified: bool = False
    receipt_to_ros_time_mapping_resolved: bool = False
    covariance_available: bool = False
    imu_crosscheck_available: bool = False
    reset_and_discontinuity_behavior_verified: bool = False

    def to_dict(self):
        return {
            "dynamic_motion_evidence_available": self.dynamic_motion_evidence_available,
            "source_channel_arbitration_resolved": self.source_channel_arbitration_resolved,
            "authoritative_source_channel": self.authoritative_source_channel,
            "source_frame_semantics_verified": self.source_frame_semantics_verified,
            "child_frame_id_resolved": self.child_frame_id_resolved,
            "resolved_child_frame_id": self.resolved_child_frame_id,
            "axis_convention_verified": self.axis_convention_verified,
            "scale_and_sign_verified": self.scale_and_sign_verified,
            "receipt_to_ros_time_mapping_resolved": self.receipt_to_ros_time_mapping_resolved,
            "covariance_available": self.covariance_available,
            "imu_crosscheck_available": self.imu_crosscheck_available,
            "reset_and_discontinuity_behavior_verified": self.reset_and_discontinuity_behavior_verified,
        }


# Boolean and optional-string field names on the contract, for shape validation.
_CONTRACT_BOOL_FIELDS = (
    "dynamic_motion_evidence_available",
    "source_channel_arbitration_resolved",
    "source_frame_semantics_verified",
    "child_frame_id_resolved",
    "axis_convention_verified",
    "scale_and_sign_verified",
    "receipt_to_ros_time_mapping_resolved",
    "covariance_available",
    "imu_crosscheck_available",
    "reset_and_discontinuity_behavior_verified",
)
_CONTRACT_OPT_STR_FIELDS = (
    "authoritative_source_channel",
    "resolved_child_frame_id",
)


@dataclass(frozen=True)
class OdomTfReadinessReport:
    """Immutable result of a readiness assessment.

    `classification` is the single stable label describing the overall outcome.
    The four readiness booleans separate the distinct questions the checkpoint
    requires be kept apart; `physical_validation_required` is true whenever any
    of them is withheld.
    """
    classification: str
    offline_contract_ready: bool
    odom_publication_ready: bool
    odom_to_base_link_tf_ready: bool
    physical_validation_required: bool
    nav2_ready: bool
    candidate_count: int
    candidate_invalid_count: int
    channels: "tuple[str, ...]"
    blockers: "tuple[OdomTfBlocker, ...]" = field(default_factory=tuple)

    @property
    def blocker_count(self):
        return sum(1 for b in self.blockers if b.severity == BLOCKER)

    def blocker_codes(self):
        """Ordered tuple of BLOCKER-severity codes only (deterministic)."""
        return tuple(b.code for b in self.blockers if b.severity == BLOCKER)

    def to_dict(self):
        """Deterministic, JSON-serializable representation."""
        return {
            "classification": self.classification,
            "offline_contract_ready": self.offline_contract_ready,
            "odom_publication_ready": self.odom_publication_ready,
            "odom_to_base_link_tf_ready": self.odom_to_base_link_tf_ready,
            "physical_validation_required": self.physical_validation_required,
            "nav2_ready": self.nav2_ready,
            "candidate_count": self.candidate_count,
            "candidate_invalid_count": self.candidate_invalid_count,
            "channels": list(self.channels),
            "blocker_count": self.blocker_count,
            "blocker_codes": list(self.blocker_codes()),
            "blockers": [b.to_dict() for b in self.blockers],
        }


# --- classifications ---------------------------------------------------------

CLASSIFICATION_CONTRACT_READY = (
    "MVP_ODOM_TF_R1_OFFLINE_CONTRACT_READY_PHYSICAL_VALIDATION_REQUIRED"
)
CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT = (
    "MVP_ODOM_TF_R1_FAIL_CLOSED_INVALID_INPUT"
)


def _sorted_blockers(blockers):
    """Stable ordering: severity (BLOCKER<WARNING<OBSERVATION), then canonical
    code index, then code text, then message. Fully deterministic and
    input-order independent, including for codes not in the canonical list."""
    return tuple(
        sorted(
            blockers,
            key=lambda b: (
                _SEVERITY_RANK.get(b.severity, 99),
                _code_index(b.code),
                b.code,
                b.message,
            ),
        )
    )


def _fail_closed_report(code, message, candidate_count=0, invalid_count=0,
                        channels=()):
    return OdomTfReadinessReport(
        classification=CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT,
        offline_contract_ready=False,
        odom_publication_ready=False,
        odom_to_base_link_tf_ready=False,
        physical_validation_required=True,
        nav2_ready=False,
        candidate_count=candidate_count,
        candidate_invalid_count=invalid_count,
        channels=tuple(channels),
        blockers=(OdomTfBlocker(code, BLOCKER, message),),
    )


def _validate_contract(contract):
    """Return an error message if the contract is not a well-formed
    OdomTfEvidenceContract with strict bool / optional-str fields; else None."""
    if not isinstance(contract, OdomTfEvidenceContract):
        return f"evidence_contract is not an OdomTfEvidenceContract (got {type(contract).__name__})"
    for name in _CONTRACT_BOOL_FIELDS:
        val = getattr(contract, name, None)
        # Reject truthy non-bool (e.g. "false", 1, 0) -- must be a real bool.
        if not isinstance(val, bool):
            return f"contract field '{name}' must be bool, got {type(val).__name__}"
    for name in _CONTRACT_OPT_STR_FIELDS:
        val = getattr(contract, name, "__missing__")
        if val is not None and not isinstance(val, str):
            return f"contract field '{name}' must be str or None, got {type(val).__name__}"
    return None


def _is_structurally_valid_candidate(c):
    """Structural check on one candidate. A bare `valid=True` is NOT trusted:
    the object must be shaped like a real OdometryCandidate."""
    # Required attributes.
    required = (
        "valid", "source_channel", "receipt_monotonic_ns",
        "message_stamp_sec", "message_stamp_nanosec",
        "position_xyz", "velocity_xyz", "yaw_speed",
        "covariance_available", "gyro_reliable", "accel_reliable",
    )
    for attr in required:
        if not hasattr(c, attr):
            return False
    if not isinstance(c.valid, bool):
        return False
    if not isinstance(c.covariance_available, bool):
        return False
    if not isinstance(c.gyro_reliable, bool) or not isinstance(c.accel_reliable, bool):
        return False
    if c.source_channel not in ALLOWED_SOURCE_CHANNELS:
        return False
    # receipt monotonic: positive int (not bool).
    rm = c.receipt_monotonic_ns
    if not isinstance(rm, int) or isinstance(rm, bool) or rm <= 0:
        return False
    # timestamps: ints in range.
    for ts_name in ("message_stamp_sec", "message_stamp_nanosec"):
        ts = getattr(c, ts_name)
        if not isinstance(ts, int) or isinstance(ts, bool) or ts < 0:
            return False
    if c.message_stamp_nanosec >= 1_000_000_000:
        return False
    # vectors: 3 finite components.
    for vec_name, length in (("position_xyz", 3), ("velocity_xyz", 3)):
        vec = getattr(c, vec_name)
        if not isinstance(vec, (list, tuple)) or len(vec) != length:
            return False
        try:
            if not all(math.isfinite(v) for v in vec):
                return False
        except TypeError:
            return False
    try:
        if not math.isfinite(c.yaw_speed):
            return False
    except TypeError:
        return False
    return True


def _has_observable_variation(candidates):
    """True if position / velocity / yaw / rpy vary across the sequence -- a
    single sample or a perfectly static sequence has no observable dynamics."""
    if len(candidates) < 2:
        return False

    def spread(vals):
        return max(vals) - min(vals) if vals else 0.0

    xs = [c.position_xyz[0] for c in candidates]
    ys = [c.position_xyz[1] for c in candidates]
    zs = [c.position_xyz[2] for c in candidates]
    yaws = [c.yaw_speed for c in candidates]
    vmax = max(
        (abs(c.velocity_xyz[0]) + abs(c.velocity_xyz[1]) + abs(c.velocity_xyz[2]))
        for c in candidates
    )
    # Any meaningful spread in position or a non-trivial velocity magnitude.
    return (
        spread(xs) > 1e-6 or spread(ys) > 1e-6 or spread(zs) > 1e-6
        or spread(yaws) > 1e-6 or vmax > 1e-3
    )


def assess_odom_tf_readiness(candidates, evidence_contract):
    """Assess offline readiness to prepare `/odom` and `odom -> base_link`.

    Parameters
    ----------
    candidates:
        A sequence of OdometryCandidate (from the pure adapter). May be empty.
    evidence_contract:
        An OdomTfEvidenceContract describing what has been established offline.

    Returns
    -------
    OdomTfReadinessReport (immutable). Never raises on malformed input --
    a bad contract or malformed candidate fails closed via an explicit blocker.

    Behavior contract:
      * nav2_ready is always False.
      * odom_publication_ready / odom_to_base_link_tf_ready are False whenever
        any BLOCKER is present.
      * physical_validation_required is True whenever publication is withheld.
      * An empty / all-invalid / structurally-malformed sequence fails closed.
      * A boolean contract flag can never override typed evidence (coherence).
    """
    # --- Fix A: contract shape fail-closed (before touching candidates) ------
    contract_error = _validate_contract(evidence_contract)
    if contract_error is not None:
        return _fail_closed_report(EVIDENCE_CONTRACT_INVALID, contract_error)
    c = evidence_contract

    # --- iterate candidates (fail-closed if not iterable) --------------------
    try:
        candidate_list = list(candidates)
    except TypeError:
        return _fail_closed_report(
            EMPTY_OR_INVALID_SEQUENCE, "candidate sequence is not iterable"
        )

    candidate_count = len(candidate_list)

    # --- Fix B: structural validation of every candidate ---------------------
    structural_bad = 0
    for cd in candidate_list:
        if not _is_structurally_valid_candidate(cd):
            structural_bad += 1
    if structural_bad > 0:
        return _fail_closed_report(
            CANDIDATE_STRUCTURE_INVALID,
            f"{structural_bad}/{candidate_count} candidates are not well-formed "
            f"OdometryCandidate instances (a bare valid=True is not trusted)",
            candidate_count=candidate_count,
            invalid_count=structural_bad,
        )

    invalid_count = sum(1 for cd in candidate_list if not cd.valid)
    valid_candidates = [cd for cd in candidate_list if cd.valid]
    channels = tuple(sorted({cd.source_channel for cd in candidate_list}))

    blockers = []

    sequence_ok = candidate_count > 0 and len(valid_candidates) > 0
    if not sequence_ok:
        msg = (
            "candidate sequence is empty" if candidate_count == 0 else
            f"candidate sequence has no valid candidates "
            f"({invalid_count}/{candidate_count} invalid)"
        )
        blockers.append(OdomTfBlocker(EMPTY_OR_INVALID_SEQUENCE, BLOCKER, msg))
    elif invalid_count > 0:
        blockers.append(OdomTfBlocker(
            EMPTY_OR_INVALID_SEQUENCE, BLOCKER,
            f"{invalid_count}/{candidate_count} candidates are invalid; "
            f"publication requires an all-valid sequence",
        ))

    # --- contract-driven gap blockers (absence never becomes a default) -----
    if not c.dynamic_motion_evidence_available:
        blockers.append(OdomTfBlocker(
            DYNAMIC_MOTION_EVIDENCE_MISSING, BLOCKER,
            "no dynamic (moving-robot) capture is available; only stationary "
            "evidence exists, which cannot validate odometry integration or drift",
        ))

    if not c.source_channel_arbitration_resolved or not c.authoritative_source_channel:
        blockers.append(OdomTfBlocker(
            SOURCE_CHANNEL_ARBITRATION_UNRESOLVED, BLOCKER,
            "no single source channel has been arbitrated as authoritative; "
            "a higher sample rate is NOT authority and channel rates are not "
            "fixed constants",
        ))

    if not c.source_frame_semantics_verified:
        blockers.append(OdomTfBlocker(
            SOURCE_FRAME_SEMANTICS_UNVERIFIED, BLOCKER,
            "source frame semantics unverified; 'unitree_odom_candidate' is not "
            "known to be equivalent to a ROS 'odom' frame",
        ))

    if not c.child_frame_id_resolved or not c.resolved_child_frame_id:
        blockers.append(OdomTfBlocker(
            CHILD_FRAME_ID_UNRESOLVED, BLOCKER,
            "child_frame_id for the odom->base_link TF edge is unresolved",
        ))

    if not c.axis_convention_verified:
        blockers.append(OdomTfBlocker(
            AXIS_CONVENTION_UNVERIFIED, BLOCKER,
            "axis convention (handedness / forward axis / REP-103 compliance) "
            "is unverified",
        ))

    if not c.scale_and_sign_verified:
        blockers.append(OdomTfBlocker(
            SCALE_AND_SIGN_UNVERIFIED, BLOCKER,
            "scale and sign of position/velocity/yaw are unverified",
        ))

    # message-stamp-zero: evidence-derived from valid candidates.
    any_zero_stamp = any(
        cd.message_stamp_sec == 0 and cd.message_stamp_nanosec == 0
        for cd in valid_candidates
    )
    if any_zero_stamp:
        blockers.append(OdomTfBlocker(
            MESSAGE_TIMESTAMP_ZERO, BLOCKER,
            "message stamp is zero in the capture; a ROS header stamp cannot be "
            "sourced from the sensor timestamp",
        ))

    if not c.receipt_to_ros_time_mapping_resolved:
        blockers.append(OdomTfBlocker(
            RECEIPT_TIME_TO_ROS_TIME_UNRESOLVED, BLOCKER,
            "receipt-monotonic-time to ROS-time mapping is unresolved",
        ))

    if not c.covariance_available:
        blockers.append(OdomTfBlocker(
            COVARIANCE_UNAVAILABLE, BLOCKER,
            "no covariance is available from the source (documented gap); "
            "covariance values must never be invented",
        ))

    if not c.imu_crosscheck_available:
        blockers.append(OdomTfBlocker(
            IMU_CROSSCHECK_UNAVAILABLE, BLOCKER,
            "no independent IMU cross-check available; gyro/accel read all-zero "
            "in the stationary capture",
        ))

    if not c.reset_and_discontinuity_behavior_verified:
        blockers.append(OdomTfBlocker(
            RESET_AND_DISCONTINUITY_BEHAVIOR_UNVERIFIED, BLOCKER,
            "reset / discontinuity / wraparound behavior of the source is "
            "uncharacterized",
        ))

    # --- Fix C: authoritative-channel & mixed-channel coherence -------------
    # Only meaningful once arbitration is asserted resolved.
    if c.source_channel_arbitration_resolved and c.authoritative_source_channel:
        auth = c.authoritative_source_channel
        auth_in_allowlist = auth in ALLOWED_SOURCE_CHANNELS
        auth_has_valid = any(
            cd.source_channel == auth for cd in valid_candidates
        )
        if not auth_in_allowlist or not auth_has_valid:
            blockers.append(OdomTfBlocker(
                AUTHORITATIVE_CHANNEL_NOT_PRESENT, BLOCKER,
                f"authoritative channel '{auth}' is not in the adapter allowlist "
                f"or has no valid candidate in this sequence",
            ))
        # A sequence mixing both channels cannot be published even if one is
        # named authoritative: a future stage must pass a filtered sequence.
        if len(channels) >= 2:
            blockers.append(OdomTfBlocker(
                MIXED_CHANNEL_SEQUENCE_REQUIRES_FILTERING, BLOCKER,
                f"sequence mixes {len(channels)} channels; publication requires a "
                f"sequence explicitly filtered to the selected channel",
            ))

    # --- Fix D: receipt-monotonic order per channel -------------------------
    for ch in channels:
        receipts = [
            cd.receipt_monotonic_ns for cd in valid_candidates
            if cd.source_channel == ch
        ]
        if any(receipts[i] > receipts[i + 1] for i in range(len(receipts) - 1)):
            blockers.append(OdomTfBlocker(
                RECEIPT_MONOTONIC_ORDER_INVALID, BLOCKER,
                f"receipt_monotonic_ns is not non-decreasing for channel '{ch}'",
            ))

    # --- Fix E: contract/evidence contradictions ----------------------------
    # A boolean flag can never override the typed evidence.
    if c.covariance_available:
        # Model carries no covariance values; a bare flag cannot clear it.
        candidate_cov = all(
            cd.covariance_available for cd in valid_candidates
        ) if valid_candidates else False
        if not candidate_cov:
            blockers.append(OdomTfBlocker(
                COVARIANCE_EVIDENCE_CONTRADICTION, BLOCKER,
                "contract asserts covariance_available but the typed candidates "
                "carry no covariance evidence (model has no covariance values)",
            ))

    if c.imu_crosscheck_available:
        imu_unreliable = any(
            (not cd.gyro_reliable) or (not cd.accel_reliable)
            for cd in valid_candidates
        )
        if imu_unreliable or not valid_candidates:
            blockers.append(OdomTfBlocker(
                IMU_EVIDENCE_CONTRADICTION, BLOCKER,
                "contract asserts imu_crosscheck_available but selected candidates "
                "have unreliable gyro/accel",
            ))

    if c.dynamic_motion_evidence_available:
        if len(valid_candidates) < 2 or not _has_observable_variation(valid_candidates):
            blockers.append(OdomTfBlocker(
                DYNAMIC_EVIDENCE_CONTRADICTION, BLOCKER,
                "contract asserts dynamic_motion_evidence_available but the "
                "sequence shows no observable variation (single/static samples)",
            ))

    # --- non-blocking, evidence-derived notes (never suppressed) ------------
    if len(channels) >= 2:
        blockers.append(OdomTfBlocker(
            MULTIPLE_CANDIDATE_CHANNELS_PRESENT, OBSERVATION,
            f"{len(channels)} candidate channels present ({', '.join(channels)}); "
            f"both preserved, neither selected in this checkpoint",
        ))
        blockers.append(OdomTfBlocker(
            RATE_DIFFERENCE_BETWEEN_CHANNELS, OBSERVATION,
            "sample-rate difference between channels is an observation only; it "
            "does not select an authoritative source and rates are not constants",
        ))

    imu_zero = any(
        (not cd.gyro_reliable) or (not cd.accel_reliable)
        for cd in valid_candidates
    )
    if imu_zero:
        blockers.append(OdomTfBlocker(
            IMU_ZERO_IN_CAPTURE, OBSERVATION,
            "IMU gyroscope/accelerometer read all-zero (or missing) in the "
            "capture (consistent with a non-moving robot)",
        ))

    sorted_blockers = _sorted_blockers(blockers)
    has_blocker = any(b.severity == BLOCKER for b in sorted_blockers)

    offline_contract_ready = sequence_ok and invalid_count == 0

    odom_publication_ready = offline_contract_ready and not has_blocker
    odom_to_base_link_tf_ready = odom_publication_ready and (
        c.child_frame_id_resolved and bool(c.resolved_child_frame_id)
    )
    nav2_ready = False  # invariant for this checkpoint
    physical_validation_required = not (
        odom_publication_ready and odom_to_base_link_tf_ready and nav2_ready
    )

    classification = (
        CLASSIFICATION_CONTRACT_READY if offline_contract_ready
        else CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT
    )

    return OdomTfReadinessReport(
        classification=classification,
        offline_contract_ready=offline_contract_ready,
        odom_publication_ready=odom_publication_ready,
        odom_to_base_link_tf_ready=odom_to_base_link_tf_ready,
        physical_validation_required=physical_validation_required,
        nav2_ready=nav2_ready,
        candidate_count=candidate_count,
        candidate_invalid_count=invalid_count,
        channels=channels,
        blockers=sorted_blockers,
    )
