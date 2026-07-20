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

R1B boundary: the whole R1 series is a NON-PUBLISHABLE offline
characterization gate. It carries no covariance model, no covariance
provenance, no displacement ground truth, no typed dynamic-evidence object, and
no physical validation of axes / scale / sign. Therefore NO combination of
contract or candidate booleans can ever authorize publication:
`odom_publication_ready`, `odom_to_base_link_tf_ready`, and `nav2_ready` are
hard `False` invariants and `physical_validation_required` is a hard `True`
invariant for R1/R1A/R1B -- even for a fully-satisfied synthetic contract with
synthetic candidates. `offline_contract_ready` may still report that the input
is processable; that is never permission to publish. R1B also: enforces a
strict `isinstance(candidate, OdometryCandidate)` (a duck-typed fake is
rejected), validates the FULL candidate structure (policies, quaternion norm,
rpy, warnings/errors types), rejects non-mapping adapter input, and rejects
whitespace-only / contradictory contract strings.
"""
import math
from dataclasses import dataclass, field

from .models import OdometryCandidate
from .validation import (
    ALLOWED_SOURCE_CHANNELS,
    COVARIANCE_POLICY,
    FRAME_ID,
    MAX_MESSAGE_NANOSEC,
    TIMESTAMP_POLICY,
    is_bounded_nonnegative_int,
    is_bounded_positive_int,
    is_finite_number,
    normalize_finite_vector,
)

# --- severities (deterministic, ordered most-severe first) -------------------

BLOCKER = "BLOCKER"
WARNING = "WARNING"
OBSERVATION = "OBSERVATION"

_SEVERITY_RANK = {BLOCKER: 0, WARNING: 1, OBSERVATION: 2}

# R1B: the publication capability is structurally withheld by the R1 boundary,
# not merely by the current fixtures. This is a fixed string, never a computed
# "ready" value, so the CLI/tests can assert the boundary is in force.
PUBLICATION_CAPABILITY_WITHHELD = "WITHHELD_BY_R1_BOUNDARY"

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
    # R1B: structurally fixed; publication capability is withheld by the R1
    # boundary regardless of contract/candidate satisfaction.
    publication_capability: str = PUBLICATION_CAPABILITY_WITHHELD

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
            "publication_capability": self.publication_capability,
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
    OdomTfEvidenceContract with strict bool / optional-str fields; else None.

    R1D-R4: closes `POLICY_STRING_SUBCLASS_COMPARISON_CAN_RAISE` for the
    contract's own optional-string fields. `type(contract) is
    OdomTfEvidenceContract` (not `isinstance`) rejects a genuine subclass
    too, not just a duck-typed fake. Every bool/optional-str field is gated
    on `type(value) is bool`/`str` -- an exact-type check -- BEFORE `strip()`,
    membership, or any comparison ever touches it, so a hostile subclass
    (whose own `strip()`/`__eq__` might raise or misbehave) is rejected
    outright. Error messages never interpolate the raw field value.
    """
    if type(contract) is not OdomTfEvidenceContract:
        return f"evidence_contract is not an OdomTfEvidenceContract (got {type(contract).__name__})"
    for name in _CONTRACT_BOOL_FIELDS:
        val = getattr(contract, name, None)
        # Reject truthy non-bool (e.g. "false", 1, 0) -- must be a real bool.
        if type(val) is not bool:
            return f"contract field '{name}' must be bool, got {type(val).__name__}"
    for name in _CONTRACT_OPT_STR_FIELDS:
        val = getattr(contract, name, "__missing__")
        if val is not None and type(val) is not str:
            return f"contract field '{name}' must be str or None, got {type(val).__name__}"

    # --- Fix D (R1B): semantic validation of the optional strings ------------
    # Only reached once both optional-string fields are confirmed `None` or
    # exact `str` above -- `strip()`/membership/comparison below never touch
    # an unvalidated value. A whitespace-only resolved value is not a value;
    # a resolved value present while its resolution flag is false is a
    # contradiction; an authoritative channel that is resolved must be a
    # non-empty allow-listed channel. Messages never interpolate the raw
    # (already-str-typed, but still untrusted-content) field value.
    arb = contract.source_channel_arbitration_resolved
    auth = contract.authoritative_source_channel
    if arb:
        if auth is None or not auth.strip():
            return (
                "source_channel_arbitration_resolved is true but "
                "authoritative_source_channel is empty/whitespace"
            )
        if auth.strip() not in ALLOWED_SOURCE_CHANNELS:
            return (
                "authoritative_source_channel is not in the allow-list "
                f"{ALLOWED_SOURCE_CHANNELS}"
            )
    else:
        # A resolved value present without the flag set is a contradiction.
        if auth is not None and auth.strip():
            return (
                "authoritative_source_channel is set but "
                "source_channel_arbitration_resolved is false (contradiction)"
            )

    child_flag = contract.child_frame_id_resolved
    child_val = contract.resolved_child_frame_id
    if child_flag:
        if child_val is None or not child_val.strip():
            return (
                "child_frame_id_resolved is true but resolved_child_frame_id is "
                "empty/whitespace"
            )
    else:
        if child_val is not None and child_val.strip():
            return (
                "resolved_child_frame_id is set but child_frame_id_resolved is "
                "false (contradiction)"
            )
    return None


def _is_structurally_valid_candidate(c):
    """Full structural check on one candidate.

    R1B: a bare `valid=True` is NOT trusted, and neither is a duck-typed fake
    that merely replicates the attributes -- the object must be an actual
    `OdometryCandidate` instance AND carry a well-formed value in every field
    (policies, quaternion norm, rpy, warnings/errors types). A dataclass
    instance is not assumed valid solely by its type.

    R1D-R3: every check here gates on an EXACT type before any comparison or
    iteration ever touches the untrusted field value: `type(c) is
    OdometryCandidate` (a genuine subclass is rejected too, not just a
    duck-typed fake), the shared numeric/vector helpers (each gated on
    `type(x) is int`/`float`/`list`/`tuple`, so a hostile subclass's own
    comparison/iteration dunders are never invoked), and exact `list`/`str`
    for warnings/errors and their items.

    R1D-R4: reorganizes the checks into a COMMON baseline applied to every
    candidate (valid or not) plus additional STRICTER checks applied only
    when `valid=True`, per the checkpoint's own contract ("estructura común
    para candidatos válidos e inválidos"). The common baseline now also
    covers `timestamp_policy`/`frame_id`/`covariance_policy`/`source_channel`
    (exact `type(...) is str` BEFORE any `!=`/`in` comparison -- closing
    `POLICY_STRING_SUBCLASS_COMPARISON_CAN_RAISE`, which previously let a
    hostile `str` subclass's `__eq__`/`__ne__` run via a bare `!=` on these
    three policy fields), `child_frame_id` (`None` or exact `str`, `strip()`
    never called before this gate), and `receipt_wall_utc_ns` (`None` or a
    bounded, exact int -- closing `RECEIPT_WALL_UTC_NS_NOT_STRUCTURALLY_
    VALIDATED`, which previously left this field completely unchecked). The
    bounded-int helpers (`is_bounded_nonnegative_int`/`is_bounded_positive_int`)
    also close `HUGE_INT`-class issues for every integer field here, matching
    the adapter's own bounds.
    """
    # Fix A (R1B); R1D-R3: exact type, not isinstance -- a genuine
    # OdometryCandidate SUBCLASS is rejected too, not just a duck-typed fake.
    if type(c) is not OdometryCandidate:
        return False

    # --- common baseline: applies to EVERY candidate, valid or not ----------

    # Fixed contract policies: exact `str` type BEFORE any `!=` comparison --
    # a hostile str subclass's `__eq__`/`__ne__` must never run.
    for policy_name, expected in (
        ("timestamp_policy", TIMESTAMP_POLICY),
        ("frame_id", FRAME_ID),
        ("covariance_policy", COVARIANCE_POLICY),
    ):
        val = getattr(c, policy_name)
        if type(val) is not str or val != expected:
            return False

    # source_channel: exact `str` type BEFORE any membership test -- checked
    # here (common to every candidate) so the allow-list membership test
    # below (valid=True only) and any later use of this field never touch an
    # unvalidated value.
    if type(c.source_channel) is not str:
        return False

    # Boolean flags must be exact bools. `bool` cannot be subclassed in
    # Python, so `type(...) is bool` is already an exact-type check here.
    for flag_name in ("valid", "covariance_available", "gyro_reliable",
                      "accel_reliable"):
        if type(getattr(c, flag_name)) is not bool:
            return False

    # warnings / errors: exact `list` of exact `str` items. `type(...) is
    # list` is checked before the collection is ever iterated, so a list
    # subclass with a hostile `__iter__` is rejected without running it.
    for coll_name in ("warnings", "errors"):
        coll = getattr(c, coll_name)
        if type(coll) is not list:
            return False
        if not all(type(item) is str for item in coll):
            return False

    # child_frame_id: None or exact str -- never call strip()/compare on an
    # unvalidated value.
    if c.child_frame_id is not None and type(c.child_frame_id) is not str:
        return False

    # receipt monotonic / timestamps: bounded, exact ints via the shared
    # helpers -- type- and range-gated before any comparison touches the
    # value. Common to every candidate: an invalid candidate's
    # receipt_monotonic_ns may legitimately be 0 (see adapter's `_invalid()`).
    if not is_bounded_nonnegative_int(c.receipt_monotonic_ns):
        return False
    if c.receipt_wall_utc_ns is not None and not is_bounded_nonnegative_int(c.receipt_wall_utc_ns):
        return False
    if not is_bounded_nonnegative_int(c.message_stamp_sec):
        return False
    if not is_bounded_nonnegative_int(c.message_stamp_nanosec) or c.message_stamp_nanosec > MAX_MESSAGE_NANOSEC:
        return False

    # position / velocity / rpy: exactly 3 finite components, normalized in
    # a single pass -- the raw field is never touched again afterward. A
    # zero vector (as an invalid candidate carries) is a valid, finite
    # vector and passes here; the valid=True branch below additionally
    # requires a non-zero quaternion norm.
    if normalize_finite_vector(c.position_xyz, 3) is None:
        return False
    if normalize_finite_vector(c.velocity_xyz, 3) is None:
        return False
    if normalize_finite_vector(c.rpy, 3) is None:
        return False

    # yaw_speed: real finite scalar (bool/subclass/HUGE_INT rejected before
    # any comparison or conversion touches it).
    if not is_finite_number(c.yaw_speed):
        return False

    # quaternion: exactly 4 finite components, normalized in a single pass.
    quaternion_normalized = normalize_finite_vector(c.orientation_quaternion_xyzw, 4)
    if quaternion_normalized is None:
        return False

    # A legitimately invalid adapter output (valid=False) is a real, typed
    # failure -- it is structurally a well-formed OdometryCandidate (the
    # common baseline above) and routes to EMPTY_OR_INVALID_SEQUENCE, not
    # CANDIDATE_STRUCTURE_INVALID. It may carry receipt_monotonic_ns=0, the
    # "<invalid>" source_channel sentinel, and a zero-norm quaternion. The
    # stricter payload checks below apply only to candidates that CLAIM to
    # be valid; a bare valid=True must be backed by a coherent payload.
    if not c.valid:
        return True

    # --- additional checks: valid=True candidates only ----------------------

    if c.source_channel not in ALLOWED_SOURCE_CHANNELS:
        return False
    if not is_bounded_positive_int(c.receipt_monotonic_ns):
        return False
    if c.errors != []:
        return False

    # Non-zero, finite quaternion norm, computed from the SAME canonical
    # tuple `normalize_finite_vector` returns (the raw
    # `orientation_quaternion_xyzw` is never iterated a second time).
    # `math.hypot` avoids the intermediate-overflow risk of a manual
    # sum-of-squares for large-but-finite components, and a non-finite
    # result is explicitly rejected rather than trusted.
    quat_norm = math.hypot(*quaternion_normalized)
    if not math.isfinite(quat_norm) or quat_norm <= 0.0:
        return False

    return True


def _has_numeric_spread(candidates):
    """Report ONLY whether the sequence shows any numeric spread in
    position / yaw / velocity. This is an OBSERVATION, never authority.

    R1B: this must never be treated as proof of dynamic motion. Stationary
    micro-noise, a constant non-zero velocity, a difference between two
    channels, or noise above 1e-6 are NOT dynamic evidence -- only a typed
    dynamic-evidence object with ground truth (introduced by R2) can be. This
    helper therefore does not gate readiness in any way; it exists so a caller
    can note that the numbers are not bit-identical.
    """
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
    # R1D-R4: closes MALFORMED_EVIDENCE_CONTRACT_CAN_RAISE. `_validate_contract`
    # is itself now exception-safe by design (exact-type gates before any
    # comparison), but this narrow boundary -- around ONLY this one call --
    # is defense-in-depth against a genuine unexpected bug there, matching
    # the same per-call pattern already used for candidate structural
    # validation below. The message includes only `type(exc).__name__`,
    # never any raw hostile value. Only ordinary `Exception` is caught;
    # `BaseException` / `KeyboardInterrupt` / `SystemExit` / `GeneratorExit`
    # are never swallowed.
    try:
        contract_error = _validate_contract(evidence_contract)
    except Exception as exc:
        return _fail_closed_report(
            EVIDENCE_CONTRACT_INVALID,
            f"evidence_contract validation raised {type(exc).__name__}; "
            f"treated as invalid input",
        )
    if contract_error is not None:
        return _fail_closed_report(EVIDENCE_CONTRACT_INVALID, contract_error)
    c = evidence_contract

    # --- iterate candidates (fail-closed if not iterable / broken iterator) --
    # R1C: a non-iterable input, or an iterable whose __iter__/__next__ raises an
    # ordinary exception (ValueError, RuntimeError, ...), must fail closed with a
    # bounded message -- never propagate. Only ordinary exceptions are caught;
    # BaseException / KeyboardInterrupt / SystemExit / GeneratorExit propagate.
    try:
        candidate_list = list(candidates)
    except Exception as exc:
        return _fail_closed_report(
            EMPTY_OR_INVALID_SEQUENCE,
            f"candidate sequence is not iterable or its iterator raised "
            f"{type(exc).__name__}",
        )

    candidate_count = len(candidate_list)

    # --- Fix B: structural validation of every candidate ---------------------
    # R1D-R3: a narrow, per-candidate boundary -- ONLY around this one call,
    # never around the rest of report generation. `_is_structurally_valid_
    # candidate` is itself now exception-safe by design (see its docstring),
    # but an unexpected ordinary exception from a genuine programming bug
    # here must still degrade to "structurally invalid" for that one
    # candidate rather than propagate out of the whole assessment. Only
    # ordinary `Exception` is caught; `BaseException` / `KeyboardInterrupt` /
    # `SystemExit` / `GeneratorExit` are never swallowed.
    structural_bad = 0
    for cd in candidate_list:
        try:
            candidate_ok = _is_structurally_valid_candidate(cd)
        except Exception:
            candidate_ok = False
        if not candidate_ok:
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
    # --- Fix A (R1C): channels derived ONLY from VALID candidates, restricted
    # to the allow-list. An invalid candidate may carry source_channel=None (or
    # any non-str), so sorting the raw union of all candidates' channels could
    # raise TypeError on a mixed valid/invalid sequence. Deriving from valid
    # candidates only yields a deterministic tuple[str, ...] with no None/int,
    # and a fully-invalid sequence reports channels=().
    channels = tuple(sorted({
        cd.source_channel for cd in valid_candidates
        if cd.source_channel in ALLOWED_SOURCE_CHANNELS
    }))

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

    # --- Fix E/F/G (R1B): contract/evidence contradictions ------------------
    # A boolean flag can never override the typed evidence. In the R1 series the
    # data model transports NO covariance values or provenance and NO typed
    # dynamic-evidence object with ground truth, so an asserted covariance or
    # dynamic flag is ALWAYS a contradiction here -- a synthetic candidate
    # boolean is not evidence and cannot clear it. This is only cleared by R2
    # introducing versioned evidence models.
    if c.covariance_available:
        blockers.append(OdomTfBlocker(
            COVARIANCE_EVIDENCE_CONTRADICTION, BLOCKER,
            "contract asserts covariance_available but the R1 data model "
            "transports no covariance values or provenance; covariance must be "
            "real or explicitly modeled (R2), never asserted by a lone flag",
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
        # R1B: there is no typed dynamic-evidence object with ground truth yet.
        # Numeric spread (micro-noise, constant velocity, cross-channel deltas)
        # is NOT dynamic proof, so this contradiction always fires in R1B.
        blockers.append(OdomTfBlocker(
            DYNAMIC_EVIDENCE_CONTRADICTION, BLOCKER,
            "contract asserts dynamic_motion_evidence_available but R1 has no "
            "typed dynamic-evidence object with displacement ground truth; "
            "numeric spread is an observation, not dynamic proof (R2 required)",
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

    offline_contract_ready = sequence_ok and invalid_count == 0

    # --- Fix E (R1B): the R1 series is a NON-PUBLISHABLE boundary ------------
    # No combination of contract/candidate booleans -- not even a fully
    # satisfied synthetic contract with synthetic candidates and zero blockers
    # -- can authorize publication in R1/R1A/R1B. The model carries no
    # covariance, no provenance, no displacement ground truth, no typed dynamic
    # evidence, and no physical axis/scale/sign validation. These four are hard
    # invariants, independent of `has_blocker`. R2 must introduce versioned
    # evidence models before any of them can change.
    odom_publication_ready = False
    odom_to_base_link_tf_ready = False
    nav2_ready = False
    physical_validation_required = True

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
