"""Separated readiness decisions for physical, replay, and simulation contexts."""

from .models import ReadinessContract


PHYSICAL_BLOCKERS = (
    "AUTHORITATIVE_SOURCE_CHANNEL_UNRESOLVED",
    "SOURCE_FRAME_SEMANTICS_PARTIAL",
    "CHILD_FRAME_ID_UNRESOLVED",
    "TRANSLATION_SCALE_UNRESOLVED",
    "YAW_SCALE_UNRESOLVED",
    "ROS_HEADER_STAMP_POLICY_UNRESOLVED",
    "COVARIANCE_SI_CONVERSION_UNAVAILABLE",
    "NO_NEW_HARDWARE_ACCESS",
)


def assess_p2_readiness(
    *,
    frame_contract_complete: bool,
    covariance_contract_complete: bool,
    mapping_inventory_available: bool,
) -> ReadinessContract:
    structurally_ready = (
        type(frame_contract_complete) is bool
        and type(covariance_contract_complete) is bool
        and type(mapping_inventory_available) is bool
        and frame_contract_complete
        and covariance_contract_complete
        and mapping_inventory_available
    )
    return ReadinessContract(
        p2_contract_structurally_ready=structurally_ready,
        offline_replay_contract_ready=structurally_ready,
        simulation_contract_ready=structurally_ready,
        physical_odom_publication_ready=False,
        physical_tf_publication_ready=False,
        simulated_odom_publication_ready=False,
        simulated_tf_publication_ready=False,
        nav2_simulation_readiness=False,
        blockers=PHYSICAL_BLOCKERS
        + (
            "SIMULATED_ODOM_PUBLICATION_DEFERRED_TO_P3",
            "SIMULATED_TF_PUBLICATION_DEFERRED_TO_P3",
            "NAV2_SIMULATION_DEFERRED",
        ),
    )
