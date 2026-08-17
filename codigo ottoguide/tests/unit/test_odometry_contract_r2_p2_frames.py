from dataclasses import replace

import pytest

from src.navigation.odometry_contract_r2_p2.frame_semantics import (
    frame_vocabulary,
    physical_frame_contract,
    replay_frame_contract,
    simulation_frame_contract,
)
from src.navigation.odometry_contract_r2_p2.models import (
    ContractValidationError,
    FrameClassification,
    ValidationContext,
)


def test_configured_names_are_not_verified_semantics():
    contract = physical_frame_contract()
    assert contract.configured_parent_frame_name == "odom"
    assert contract.configured_child_frame_name == "base_link"
    assert contract.source_frame_semantics_status == "PARTIAL"
    assert contract.child_frame_semantics_status == "UNRESOLVED"


def test_physical_context_cannot_be_promoted_by_synthetic_claim():
    contract = physical_frame_contract()
    with pytest.raises(ContractValidationError):
        replace(contract, source_frame_semantics_status="VERIFIED")


def test_physical_cross_boot_prohibition():
    contract = physical_frame_contract()
    assert contract.boot_domain_policy == "PER_BOOT_NO_CROSS_BOOT_CONCATENATION"
    with pytest.raises(ContractValidationError):
        replace(contract, boot_domain_policy="CROSS_BOOT_ALLOWED")


def test_contexts_have_separate_semantics():
    physical = physical_frame_contract()
    replay = replay_frame_contract()
    simulation = simulation_frame_contract()
    assert physical.validation_context is ValidationContext.PHYSICAL_EVIDENCE
    assert replay.validation_context is ValidationContext.OFFLINE_REPLAY
    assert simulation.validation_context is ValidationContext.SIMULATION
    assert simulation.translation_unit_status == "METERS_SIMULATION_ONLY"
    assert physical.translation_unit_status == "SOURCE_UNITS_UNRESOLVED"


def test_minimum_vocabulary_and_no_frequency_promotion():
    entries = {entry.frame: entry for entry in frame_vocabulary()}
    assert {
        "map",
        "odom",
        "base_link",
        "unitree_odom_candidate",
        "utlidar_lidar",
        "livox_imu",
        "imu_link",
    } <= set(entries)
    assert FrameClassification.CONFIGURED_NAME in entries["odom"].classifications
    assert "Frequency of occurrence is not evidence." in entries["odom"].limitations
