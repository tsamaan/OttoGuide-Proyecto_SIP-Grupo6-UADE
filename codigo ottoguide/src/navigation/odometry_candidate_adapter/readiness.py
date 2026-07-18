"""MVP-ODOM-TF-R1 offline readiness gate.

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

The gate consumes the typed OdometryCandidate sequence produced by the existing
pure adapter, plus an explicit evidence contract describing what has (and has
not) been established offline. It never invents frame names, covariance values,
axis semantics, scale, sign, reset behavior, timestamp conversion, or dynamic
accuracy -- anything not explicitly asserted in the contract is treated as
unverified and blocks publication.
"""
from dataclasses import dataclass, field

# --- severities (deterministic, ordered most-severe first) -------------------

BLOCKER = "BLOCKER"
WARNING = "WARNING"
OBSERVATION = "OBSERVATION"

_SEVERITY_RANK = {BLOCKER: 0, WARNING: 1, OBSERVATION: 2}

# --- blocker codes (stable identifiers, never free text for the code) --------

EMPTY_OR_INVALID_SEQUENCE = "EMPTY_OR_INVALID_SEQUENCE"
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

# Deterministic canonical ordering of every blocker code the gate can emit.
# Reports sort by (severity_rank, index-in-this-tuple) so output is stable
# regardless of the order checks happen to run.
_BLOCKER_CODE_ORDER = (
    EMPTY_OR_INVALID_SEQUENCE,
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
)

# Some codes are also emitted as WARNING/OBSERVATION variants (e.g. a rate
# difference is only ever an OBSERVATION). Non-blocker codes get an order index
# after the blocker codes so they still sort deterministically.
RATE_DIFFERENCE_BETWEEN_CHANNELS = "RATE_DIFFERENCE_BETWEEN_CHANNELS"
STATIONARY_ONLY_CAPTURE = "STATIONARY_ONLY_CAPTURE"
IMU_ZERO_IN_CAPTURE = "IMU_ZERO_IN_CAPTURE"
MULTIPLE_CANDIDATE_CHANNELS_PRESENT = "MULTIPLE_CANDIDATE_CHANNELS_PRESENT"

_NON_BLOCKER_CODE_ORDER = (
    RATE_DIFFERENCE_BETWEEN_CHANNELS,
    STATIONARY_ONLY_CAPTURE,
    IMU_ZERO_IN_CAPTURE,
    MULTIPLE_CANDIDATE_CHANNELS_PRESENT,
)


def _code_index(code):
    if code in _BLOCKER_CODE_ORDER:
        return _BLOCKER_CODE_ORDER.index(code)
    if code in _NON_BLOCKER_CODE_ORDER:
        return len(_BLOCKER_CODE_ORDER) + _NON_BLOCKER_CODE_ORDER.index(code)
    # Unknown codes sort last but still deterministically (by code text).
    return len(_BLOCKER_CODE_ORDER) + len(_NON_BLOCKER_CODE_ORDER)


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
    """
    # Has a dynamic (moving-robot) capture been provided and validated?
    dynamic_motion_evidence_available: bool = False
    # Has exactly one source channel been arbitrated as authoritative, with a
    # documented reason (never "the faster one")?
    source_channel_arbitration_resolved: bool = False
    authoritative_source_channel: "str | None" = None
    # Has the physical meaning of the source frame been verified against a ROS
    # `odom` frame (origin, drift semantics, continuity)?
    source_frame_semantics_verified: bool = False
    # Has the child frame (e.g. base_link) been resolved for the TF edge?
    child_frame_id_resolved: bool = False
    resolved_child_frame_id: "str | None" = None
    # Has the axis convention (REP-103 / handedness / forward axis) been verified?
    axis_convention_verified: bool = False
    # Have scale and sign of position/velocity/yaw been verified?
    scale_and_sign_verified: bool = False
    # Has a receipt-monotonic -> ROS-time mapping been defined and validated?
    receipt_to_ros_time_mapping_resolved: bool = False
    # Is a real covariance available from the source (documented, not invented)?
    covariance_available: bool = False
    # Is an independent IMU cross-check available (gyro/accel non-zero, usable)?
    imu_crosscheck_available: bool = False
    # Has reset / discontinuity / wraparound behavior been characterized?
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
    code index, then message text. Fully deterministic and input-order
    independent."""
    return tuple(
        sorted(
            blockers,
            key=lambda b: (
                _SEVERITY_RANK.get(b.severity, 99),
                _code_index(b.code),
                b.message,
            ),
        )
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
    OdomTfReadinessReport (immutable). Never raises on malformed candidate
    content -- invalid candidates fail closed via an explicit blocker.

    Behavior contract:
      * nav2_ready is always False.
      * odom_publication_ready / odom_to_base_link_tf_ready are False whenever
        any BLOCKER is present.
      * physical_validation_required is True whenever publication is withheld.
      * An empty or all-invalid sequence fails closed.
    """
    blockers = []

    # --- fail-closed input validation ---------------------------------------
    try:
        candidate_list = list(candidates)
    except TypeError:
        # Not iterable at all -> hardest fail-closed.
        report = OdomTfReadinessReport(
            classification=CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT,
            offline_contract_ready=False,
            odom_publication_ready=False,
            odom_to_base_link_tf_ready=False,
            physical_validation_required=True,
            nav2_ready=False,
            candidate_count=0,
            candidate_invalid_count=0,
            channels=(),
            blockers=(OdomTfBlocker(
                EMPTY_OR_INVALID_SEQUENCE, BLOCKER,
                "candidate sequence is not iterable",
            ),),
        )
        return report

    candidate_count = len(candidate_list)
    invalid_count = sum(1 for c in candidate_list if not getattr(c, "valid", False))
    valid_candidates = [c for c in candidate_list if getattr(c, "valid", False)]
    channels = tuple(sorted({
        getattr(c, "source_channel", None)
        for c in candidate_list
        if getattr(c, "source_channel", None)
    }))

    sequence_ok = candidate_count > 0 and len(valid_candidates) > 0
    if not sequence_ok:
        if candidate_count == 0:
            msg = "candidate sequence is empty"
        else:
            msg = (
                f"candidate sequence has no valid candidates "
                f"({invalid_count}/{candidate_count} invalid)"
            )
        blockers.append(OdomTfBlocker(EMPTY_OR_INVALID_SEQUENCE, BLOCKER, msg))
    elif invalid_count > 0:
        # Some invalid among valid: not a hard empty failure, but a blocker --
        # a publication path cannot include candidates that failed adapter
        # validation.
        blockers.append(OdomTfBlocker(
            EMPTY_OR_INVALID_SEQUENCE, BLOCKER,
            f"{invalid_count}/{candidate_count} candidates are invalid; "
            f"publication requires an all-valid sequence",
        ))

    # --- contract-driven blockers (absence never becomes a default) ---------
    c = evidence_contract

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

    # --- message-stamp-zero: derived from the candidates themselves ---------
    # If any valid candidate carries a zero message stamp, publication cannot
    # rely on the sensor timestamp. This is evidence-derived, not contract-
    # asserted, so it is checked against the actual candidates.
    any_zero_stamp = any(
        getattr(cd, "message_stamp_sec", 0) == 0
        and getattr(cd, "message_stamp_nanosec", 0) == 0
        for cd in valid_candidates
    )
    if any_zero_stamp:
        blockers.append(OdomTfBlocker(
            MESSAGE_TIMESTAMP_ZERO, BLOCKER,
            "message stamp is zero in the capture; a ROS header stamp cannot be "
            "sourced from the sensor timestamp",
        ))

    # --- non-blocking, evidence-derived notes (never suppressed) ------------
    if len(channels) >= 2:
        blockers.append(OdomTfBlocker(
            MULTIPLE_CANDIDATE_CHANNELS_PRESENT, OBSERVATION,
            f"{len(channels)} candidate channels present ({', '.join(channels)}); "
            f"both preserved, neither selected in this checkpoint",
        ))
        # A rate difference between channels is only ever an observation, never
        # a basis for selecting a source.
        blockers.append(OdomTfBlocker(
            RATE_DIFFERENCE_BETWEEN_CHANNELS, OBSERVATION,
            "sample-rate difference between channels is an observation only; it "
            "does not select an authoritative source and rates are not constants",
        ))

    # IMU-all-zero surfaced as an observation in addition to the blocker above,
    # for traceability of *why* the cross-check is unavailable.
    imu_zero = any(
        not getattr(cd, "gyro_reliable", False) or not getattr(cd, "accel_reliable", False)
        for cd in valid_candidates
    )
    if imu_zero:
        blockers.append(OdomTfBlocker(
            IMU_ZERO_IN_CAPTURE, OBSERVATION,
            "IMU gyroscope/accelerometer read all-zero in the stationary "
            "capture (consistent with a non-moving robot)",
        ))

    sorted_blockers = _sorted_blockers(blockers)
    has_blocker = any(b.severity == BLOCKER for b in sorted_blockers)

    # offline_contract_ready: the gate itself ran and the input was processable
    # (a non-empty, all-valid candidate sequence). It does NOT mean publication
    # is permitted -- that is the separate publication/TF readiness axis.
    offline_contract_ready = sequence_ok and invalid_count == 0

    odom_publication_ready = offline_contract_ready and not has_blocker
    odom_to_base_link_tf_ready = odom_publication_ready and (
        c.child_frame_id_resolved and bool(c.resolved_child_frame_id)
    )
    nav2_ready = False  # invariant for this checkpoint
    physical_validation_required = not (
        odom_publication_ready and odom_to_base_link_tf_ready and nav2_ready
    )

    if not offline_contract_ready:
        classification = CLASSIFICATION_FAIL_CLOSED_INVALID_INPUT
    else:
        classification = CLASSIFICATION_CONTRACT_READY

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
