from __future__ import annotations

import inspect

import pytest

from src.navigation import odom_bridge_contract as contract
from src.navigation.odom_bridge_contract import (
    OdomBridgeSafetyFlags,
    OdomFrameContract,
    OdomSourceAssessment,
    OdomSourceKind,
)


def _source(kind: OdomSourceKind, *, pose: bool = False, yaw: bool = False, twist: bool = False):
    return OdomSourceAssessment(
        source_kind=kind,
        has_pose_xy=pose,
        has_yaw=yaw,
        has_twist=twist,
        frequency_hz=100.0,
        notes="offline unit test fixture",
    )


@pytest.mark.parametrize(
    "kind",
    [
        OdomSourceKind.LOWSTATE_ONLY,
        OdomSourceKind.SPORTMODESTATE_ONLY,
        OdomSourceKind.IMU_ONLY,
        OdomSourceKind.JOINTS_ONLY,
        OdomSourceKind.UNKNOWN,
    ],
)
def test_non_translational_sources_are_not_acceptable(kind):
    assert not contract.is_source_acceptable_for_odom(
        _source(kind, pose=True, yaw=True, twist=True)
    )


def test_validated_pose_yaw_twist_source_is_acceptable():
    source = _source(OdomSourceKind.POSE_TWIST_VALIDATED, pose=True, yaw=True, twist=True)
    assert contract.is_source_acceptable_for_odom(source)


def test_validated_source_without_twist_is_not_acceptable():
    source = _source(OdomSourceKind.POSE_TWIST_VALIDATED, pose=True, yaw=True, twist=False)
    assert not contract.is_source_acceptable_for_odom(source)


def test_activation_allowed_never_implies_current_readiness():
    flags = OdomBridgeSafetyFlags(True, True, True, "validated_hg_pose_twist")
    source = _source(OdomSourceKind.POSE_TWIST_VALIDATED, pose=True, yaw=True, twist=True)
    with pytest.warns(DeprecationWarning):
        assert not contract.activation_allowed(flags, source)
    assert contract.legacy_prerequisites_satisfied(flags, source)


@pytest.mark.parametrize(
    "flags",
    [
        OdomBridgeSafetyFlags(False, True, True, "validated_hg_pose_twist"),
        OdomBridgeSafetyFlags(True, False, True, "validated_hg_pose_twist"),
        OdomBridgeSafetyFlags(True, True, False, "validated_hg_pose_twist"),
        OdomBridgeSafetyFlags(True, True, True, None),
        OdomBridgeSafetyFlags(True, True, True, ""),
        OdomBridgeSafetyFlags(True, True, True, "   "),
    ],
)
def test_activation_rejects_missing_required_flags(flags):
    source = _source(OdomSourceKind.POSE_TWIST_VALIDATED, pose=True, yaw=True, twist=True)
    with pytest.warns(DeprecationWarning):
        assert not contract.activation_allowed(flags, source)


def test_default_covariances_have_length_36_and_are_not_zero():
    covariance = contract.default_conservative_covariance()
    assert len(covariance.pose_covariance) == 36
    assert len(covariance.twist_covariance) == 36
    assert any(value != 0.0 for value in covariance.pose_covariance)
    assert any(value != 0.0 for value in covariance.twist_covariance)
    assert covariance.evidence_status == "LEGACY_PLACEHOLDER_NOT_EVIDENCE"
    assert covariance.publication_allowed is False


def test_default_frame_contract():
    frames = OdomFrameContract()
    assert frames.odom_frame == "odom"
    assert frames.base_frame == "base_link"
    assert frames.lidar_frame == "utlidar_lidar"
    assert frames.semantics_status == "CONFIGURED_NAME_ONLY"
    assert frames.physical_semantics_verified is False
    contract.validate_frame_contract(frames)


@pytest.mark.parametrize(
    "frames",
    [
        OdomFrameContract(odom_frame="", base_frame="base_link", lidar_frame="utlidar_lidar"),
        OdomFrameContract(odom_frame="odom", base_frame="", lidar_frame="utlidar_lidar"),
        OdomFrameContract(odom_frame="odom", base_frame="base_link", lidar_frame=""),
    ],
)
def test_frame_contract_rejects_empty_frames(frames):
    with pytest.raises(ValueError):
        contract.validate_frame_contract(frames)


@pytest.mark.parametrize(
    "frames",
    [
        OdomFrameContract(odom_frame="odom", base_frame="odom", lidar_frame="utlidar_lidar"),
        OdomFrameContract(odom_frame="odom", base_frame="base_link", lidar_frame="base_link"),
    ],
)
def test_frame_contract_rejects_duplicate_critical_frames(frames):
    with pytest.raises(ValueError):
        contract.validate_frame_contract(frames)


def test_contract_module_has_no_required_ros_imports():
    source = inspect.getsource(contract)
    forbidden_imports = (
        "import " + "rclpy",
        "from " + "rclpy",
        "import " + "nav_msgs",
        "from " + "nav_msgs",
        "import " + "geometry_msgs",
        "from " + "geometry_msgs",
    )
    for forbidden in forbidden_imports:
        assert forbidden not in source


def test_contract_module_has_no_velocity_command_topic_literal():
    assert "/" + "cmd_vel" not in inspect.getsource(contract)
