import math

import pytest

from src.navigation.odometry_contract_r2_p2.models import (
    ContractValidationError,
    P2_SCHEMA_VERSION,
    ProvenanceRef,
    ValidationContext,
    validate_covariance_matrix,
)


def test_schema_version():
    assert P2_SCHEMA_VERSION == "2.2.0-p2"


def test_provenance_rejects_personal_absolute_path():
    with pytest.raises(ContractValidationError):
        ProvenanceRef(
            source_id="x",
            relative_path="C:/Users/example/file.json",
            validation_context=ValidationContext.STRUCTURAL_ONLY,
            claim_strength="STRUCTURAL",
        )


@pytest.mark.parametrize(
    "matrix",
    [
        (0.0,) * 35,
        (False,) + (0.0,) * 35,
        (float("nan"),) + (0.0,) * 35,
        (float("inf"),) + (0.0,) * 35,
    ],
)
def test_covariance_wrong_shape_bool_nan_infinity_rejected(matrix):
    with pytest.raises(ContractValidationError):
        validate_covariance_matrix(matrix)


def test_negative_diagonal_rejected():
    values = [0.0] * 36
    values[0] = -1.0
    with pytest.raises(ContractValidationError):
        validate_covariance_matrix(tuple(values))


def test_asymmetry_rejected():
    values = [0.0] * 36
    values[1] = 1.0
    with pytest.raises(ContractValidationError):
        validate_covariance_matrix(tuple(values))


def test_non_psd_rejected():
    values = [0.0] * 36
    values[0] = 1.0
    values[7] = 1.0
    values[1] = values[6] = 2.0
    with pytest.raises(ContractValidationError):
        validate_covariance_matrix(tuple(values))


def test_psd_diagonal_accepted():
    values = [0.0] * 36
    for index, value in enumerate((1.0, 2.0, 3.0, 0.1, 0.1, 0.5)):
        values[index * 6 + index] = value
    validate_covariance_matrix(tuple(values))
