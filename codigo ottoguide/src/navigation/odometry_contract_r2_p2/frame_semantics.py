"""Frame vocabulary and context-specific semantic contracts."""

from __future__ import annotations

from .models import (
    FrameClassification,
    FrameSemanticsContract,
    FrameVocabularyEntry,
    ProvenanceRef,
    ValidationContext,
)


SOURCE_FRAME_LABEL = "unitree_odom_candidate"
CONFIGURED_PARENT_FRAME_NAME = "odom"
CONFIGURED_CHILD_FRAME_NAME = "base_link"
CONFIGURED_SENSOR_FRAME_NAME = "utlidar_lidar"


def _provenance(
    source_id: str,
    relative_path: str,
    context: ValidationContext,
    strength: str,
    *limitations: str,
) -> ProvenanceRef:
    return ProvenanceRef(
        source_id=source_id,
        relative_path=relative_path,
        validation_context=context,
        claim_strength=strength,
        limitations=tuple(limitations),
    )


def physical_frame_contract() -> FrameSemanticsContract:
    context = ValidationContext.PHYSICAL_EVIDENCE
    return FrameSemanticsContract(
        source_frame_label=SOURCE_FRAME_LABEL,
        configured_parent_frame_name=CONFIGURED_PARENT_FRAME_NAME,
        configured_child_frame_name=CONFIGURED_CHILD_FRAME_NAME,
        configured_sensor_frame_name=CONFIGURED_SENSOR_FRAME_NAME,
        source_frame_semantics_status="PARTIAL",
        child_frame_semantics_status="UNRESOLVED",
        transform_direction_status="PARTIAL_SOURCE_CHANGE_OBSERVED",
        axis_convention_status="PARTIAL_SIGN_ONLY",
        handedness_status="UNRESOLVED",
        translation_unit_status="SOURCE_UNITS_UNRESOLVED",
        yaw_unit_status="YAW_SPEED_RAD_S_ONLY_YAW_ANGLE_UNRESOLVED",
        translation_scale_status="UNRESOLVED",
        yaw_scale_status="UNRESOLVED",
        origin_policy="LOCAL_SESSION_OR_SEGMENT_BASELINE_NOT_GLOBAL_ORIGIN",
        reset_policy="PER_BOOT_RESET_DISCONTINUITY_OBSERVED",
        boot_domain_policy="PER_BOOT_NO_CROSS_BOOT_CONCATENATION",
        time_domain_policy="UNRESOLVED_FOR_ROS_HEADER",
        source_channel_status="UNRESOLVED",
        validation_context=context,
        provenance=(
            _provenance(
                "r2-p1a",
                "inputs/R2_P1A_RESULT.json",
                context,
                "PRESERVED_PHYSICAL_EVIDENCE",
                "No new hardware access.",
                "Configured frame names are not physical verification.",
            ),
        ),
    )


def replay_frame_contract() -> FrameSemanticsContract:
    context = ValidationContext.OFFLINE_REPLAY
    return FrameSemanticsContract(
        source_frame_label=SOURCE_FRAME_LABEL,
        configured_parent_frame_name=CONFIGURED_PARENT_FRAME_NAME,
        configured_child_frame_name=CONFIGURED_CHILD_FRAME_NAME,
        configured_sensor_frame_name=CONFIGURED_SENSOR_FRAME_NAME,
        source_frame_semantics_status="REPLAY_SOURCE_LABEL_BOUND",
        child_frame_semantics_status="REPLAY_CONFIGURED_NAME_ONLY",
        transform_direction_status="REPLAY_CONTRACT_EXPLICIT",
        axis_convention_status="PRESERVE_SOURCE_AXES_NO_SI_PROMOTION",
        handedness_status="PRESERVE_SOURCE_UNRESOLVED",
        translation_unit_status="SOURCE_UNITS_UNRESOLVED",
        yaw_unit_status="YAW_SPEED_RAD_S_ONLY_YAW_ANGLE_UNRESOLVED",
        translation_scale_status="UNRESOLVED",
        yaw_scale_status="UNRESOLVED",
        origin_policy="PER_REPLAY_SESSION_LOCAL_ORIGIN",
        reset_policy="RESET_AT_REPLAY_SESSION_BOUNDARY",
        boot_domain_policy="NO_CROSS_BOOT_CONCATENATION",
        time_domain_policy="PRESERVE_RECORDED_ORDER_NO_ROS_STAMP",
        source_channel_status="EXPLICIT_INPUT_REQUIRED_NO_AUTO_ARBITRATION",
        validation_context=context,
        provenance=(
            _provenance(
                "mapping-workspace",
                "mapping/MAPPING_FRAME_AND_TOPIC_INVENTORY.json",
                context,
                "READ_ONLY_MAPPING_REFERENCE",
                "Mapping names are not promoted to physical truth.",
            ),
        ),
    )


def simulation_frame_contract() -> FrameSemanticsContract:
    context = ValidationContext.SIMULATION
    return FrameSemanticsContract(
        source_frame_label=SOURCE_FRAME_LABEL,
        configured_parent_frame_name=CONFIGURED_PARENT_FRAME_NAME,
        configured_child_frame_name=CONFIGURED_CHILD_FRAME_NAME,
        configured_sensor_frame_name=CONFIGURED_SENSOR_FRAME_NAME,
        source_frame_semantics_status="SIMULATION_MODEL_EXPLICIT",
        child_frame_semantics_status="SIMULATION_MODEL_EXPLICIT",
        transform_direction_status="SIMULATION_ODOM_TO_BASE_EXPLICIT",
        axis_convention_status="ROS_REP_103_SIMULATION_POLICY",
        handedness_status="RIGHT_HANDED_SIMULATION_POLICY",
        translation_unit_status="METERS_SIMULATION_ONLY",
        yaw_unit_status="RADIANS_SIMULATION_ONLY",
        translation_scale_status="UNITY_SIMULATION_ONLY",
        yaw_scale_status="UNITY_SIMULATION_ONLY",
        origin_policy="SIMULATION_WORLD_START",
        reset_policy="RESET_AT_SIMULATION_EPISODE_BOUNDARY",
        boot_domain_policy="SIMULATION_EPISODE_ONLY",
        time_domain_policy="SIMULATION_CLOCK_DEFERRED_TO_P3",
        source_channel_status="SYNTHETIC_SIMULATION_SOURCE_ONLY",
        validation_context=context,
        provenance=(
            _provenance(
                "mapping-simulation",
                "mapping/simulated_frame_tree_plan.json",
                context,
                "SIMULATION_MODEL_REFERENCE",
                "SIMULATION_ONLY=true",
                "PHYSICAL_VALIDATION_CLAIM=false",
            ),
        ),
    )


def frame_vocabulary() -> tuple[FrameVocabularyEntry, ...]:
    rows = (
        (
            "map",
            (FrameClassification.MAPPING_REFERENCE, FrameClassification.ROS_OUTPUT_CANDIDATE),
            ValidationContext.OFFLINE_REPLAY,
            ("mapping/maps", "docs/Arquitectura/ODOM_BRIDGE_CONTRACT.md"),
            "MAPPING_AND_DOCUMENTATION",
            "No physical map frame validated.",
        ),
        (
            "odom",
            (FrameClassification.CONFIGURED_NAME, FrameClassification.ROS_OUTPUT_CANDIDATE),
            ValidationContext.STRUCTURAL_ONLY,
            ("src/navigation/odom_bridge_contract.py",),
            "CONFIGURED_ONLY",
            "Configured output name is not source-frame equivalence.",
        ),
        (
            "base_link",
            (FrameClassification.CONFIGURED_NAME, FrameClassification.ROS_OUTPUT_CANDIDATE),
            ValidationContext.STRUCTURAL_ONLY,
            ("src/navigation/odom_bridge_contract.py",),
            "CONFIGURED_ONLY",
            "Child semantics remain unresolved.",
        ),
        (
            SOURCE_FRAME_LABEL,
            (FrameClassification.SOURCE_LABEL, FrameClassification.OFFLINE_REPLAY_REFERENCE),
            ValidationContext.PHYSICAL_EVIDENCE,
            ("src/navigation/odometry_candidate_adapter/validation.py",),
            "PARTIAL",
            "Label is intentionally not odom.",
        ),
        (
            "utlidar_lidar",
            (
                FrameClassification.CONFIGURED_NAME,
                FrameClassification.PHYSICAL_EVIDENCE_REFERENCE,
                FrameClassification.MAPPING_REFERENCE,
            ),
            ValidationContext.PHYSICAL_EVIDENCE,
            ("docs/Arquitectura/ROBOT_FACTORY_BASELINE_AND_OTTOGUIDE_EVOLUTION.md",),
            "PARTIAL",
            "Evidence reference does not validate base-to-sensor transform.",
        ),
        (
            "livox_imu",
            (FrameClassification.MAPPING_REFERENCE, FrameClassification.UNRESOLVED_ALIAS),
            ValidationContext.OFFLINE_REPLAY,
            ("mapping/topic_inventory",),
            "UNRESOLVED_ALIAS",
            "Topic label and frame id must not be conflated.",
        ),
        (
            "imu_link",
            (
                FrameClassification.HISTORICAL_DOCUMENTATION,
                FrameClassification.SIMULATION_MODEL_REFERENCE,
                FrameClassification.UNRESOLVED_ALIAS,
            ),
            ValidationContext.STRUCTURAL_ONLY,
            ("docs/Arquitectura/ODOM_BRIDGE_CONTRACT.md",),
            "UNRESOLVED_ALIAS",
            "No physical alias to livox_imu is established.",
        ),
    )
    entries = []
    for frame, classes, context, paths, strength, limitation in rows:
        entries.append(
            FrameVocabularyEntry(
                frame=frame,
                classifications=classes,
                paths=paths,
                source="code_docs_evidence_mapping",
                validation_context=context,
                claim_strength=strength,
                provenance=(
                    _provenance(
                        f"vocabulary-{frame}",
                        paths[0],
                        context,
                        strength,
                        limitation,
                    ),
                ),
                limitations=(limitation, "Frequency of occurrence is not evidence."),
            )
        )
    return tuple(entries)
