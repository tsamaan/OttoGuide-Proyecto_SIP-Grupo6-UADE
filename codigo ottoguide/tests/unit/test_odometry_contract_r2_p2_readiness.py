import pytest

from src.navigation.odometry_contract_r2_p2.models import (
    ContractValidationError,
    ReadinessContract,
)
from src.navigation.odometry_contract_r2_p2.readiness import assess_p2_readiness


def test_structural_replay_and_simulation_contracts_ready():
    result = assess_p2_readiness(
        frame_contract_complete=True,
        covariance_contract_complete=True,
        mapping_inventory_available=True,
    )
    assert result.p2_contract_structurally_ready is True
    assert result.offline_replay_contract_ready is True
    assert result.simulation_contract_ready is True


def test_all_publication_and_nav2_flags_remain_false():
    result = assess_p2_readiness(
        frame_contract_complete=True,
        covariance_contract_complete=True,
        mapping_inventory_available=True,
    )
    assert result.physical_odom_publication_ready is False
    assert result.physical_tf_publication_ready is False
    assert result.simulated_odom_publication_ready is False
    assert result.simulated_tf_publication_ready is False
    assert result.nav2_simulation_readiness is False
    assert "NO_NEW_HARDWARE_ACCESS" in result.blockers


def test_missing_mapping_blocks_structural_readiness():
    result = assess_p2_readiness(
        frame_contract_complete=True,
        covariance_contract_complete=True,
        mapping_inventory_available=False,
    )
    assert result.p2_contract_structurally_ready is False


def test_manual_physical_promotion_rejected():
    with pytest.raises(ContractValidationError):
        ReadinessContract(
            p2_contract_structurally_ready=True,
            offline_replay_contract_ready=True,
            simulation_contract_ready=True,
            physical_odom_publication_ready=True,
            physical_tf_publication_ready=False,
            simulated_odom_publication_ready=False,
            simulated_tf_publication_ready=False,
            nav2_simulation_readiness=False,
            blockers=("x",),
        )
