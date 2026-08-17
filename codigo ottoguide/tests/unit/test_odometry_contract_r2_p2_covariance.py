import pytest

from src.navigation.odometry_contract_r2_p2.covariance import (
    build_physical_source_unit_evidence,
    covariance_context_contracts,
)
from src.navigation.odometry_contract_r2_p2.models import ContractValidationError


def _p1a_doc(stddev=(2.0, 3.0, 0.5)):
    return {
        "p1_bundle": {
            "stationary": [
                {
                    "channel": "rt/odommodestate",
                    "session_id": "s1",
                    "stddev": list(stddev),
                    "mad": [1.0, 1.0, 0.1],
                    "p95_deviation": [4.0, 5.0, 1.0],
                    "sample_count": 10,
                    "duration_s": 1.5,
                }
            ],
            "dynamic_residuals": [
                {
                    "session_id": "s1",
                    "channel": "BOTH",
                    "residual_value": 0.25,
                }
            ],
        },
        "yaw_speed_residuals": [
            {
                "session_id": "s1",
                "yaw_speed_rmse_rad_s": 0.1,
            }
        ],
    }


def test_source_units_never_promoted_to_si():
    evidence = build_physical_source_unit_evidence(_p1a_doc())[0]
    assert evidence.units == "SOURCE_UNITS_UNRESOLVED"
    assert evidence.ros_si_matrix is None
    assert evidence.publication_ready is False
    assert evidence.diagonal_candidates_source_unit_squared[:3] == (4.0, 9.0, 0.25)


def test_zero_is_not_used_as_unknown_or_candidate():
    evidence = build_physical_source_unit_evidence(_p1a_doc((0.0, 1.0, 1.0)))[0]
    assert evidence.diagonal_candidates_source_unit_squared[0] is None


def test_999_is_not_a_physical_policy_value():
    contexts = covariance_context_contracts()
    assert "999" not in repr(contexts)
    assert contexts["ROS_SI_PUBLICATION_CANDIDATE"]["matrix"] is None


def test_primary_and_lf_are_separate_records():
    doc = _p1a_doc()
    second = dict(doc["p1_bundle"]["stationary"][0])
    second["channel"] = "rt/lf/odommodestate"
    doc["p1_bundle"]["stationary"].append(second)
    records = build_physical_source_unit_evidence(doc)
    assert {record.channel for record in records} == {
        "rt/odommodestate",
        "rt/lf/odommodestate",
    }


def test_yaw_speed_residual_not_yaw_pose_covariance():
    evidence = build_physical_source_unit_evidence(_p1a_doc())[0]
    assert evidence.yaw_speed_residual_rad_s == 0.1
    assert evidence.diagonal_candidates_source_unit_squared[5] is None


def test_malformed_stationary_input_fails_closed():
    with pytest.raises(ContractValidationError):
        build_physical_source_unit_evidence({"p1_bundle": {"stationary": [{}]}})


def test_simulation_policy_cannot_validate_physical_claim():
    simulation = covariance_context_contracts()["SIMULATION_COVARIANCE_POLICY"]
    assert simulation["simulation_only"] is True
    assert simulation["physical_validation_claim"] is False
