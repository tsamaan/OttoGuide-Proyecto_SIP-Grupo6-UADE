"""
@TASK: Validar StationRegistry y su esquema YAML estricto (U2)
@INPUT: Archivos YAML temporales construidos por cada test; sin camara
@OUTPUT: Resultado de pytest: PASSED si el registro valida correctamente
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_u2_station_registry.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.stations.station_registry import StationDefinition, StationRegistry, StationRegistryError

_VALID_YAML = """\
version: 1
stations:
  QR_A:
    station_id: "1"
    name: "Estacion A"
  QR_B:
    station_id: "2"
    name: "Estacion B"
"""


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "qr_stations.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID_YAML)
    registry = StationRegistry.from_yaml(path)
    assert len(registry.stations) == 2
    assert registry.qr_values == frozenset({"QR_A", "QR_B"})
    assert registry.station_ids == frozenset({"1", "2"})


def test_resolve_known_value(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID_YAML)
    registry = StationRegistry.from_yaml(path)
    station = registry.resolve("QR_A")
    assert station == StationDefinition(qr_value="QR_A", station_id="1", name="Estacion A")


def test_resolve_unknown_returns_none(tmp_path: Path) -> None:
    path = _write(tmp_path, _VALID_YAML)
    registry = StationRegistry.from_yaml(path)
    assert registry.resolve("QR_NOPE") is None


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(tmp_path / "does_not_exist.yaml")


def test_yaml_not_mapping_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "- a\n- b\n")
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_missing_version_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "stations:\n  QR_A:\n    station_id: '1'\n    name: 'A'\n")
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_non_integer_version_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: '1'\nstations:\n  QR_A:\n    station_id: '1'\n    name: 'A'\n",
    )
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_version_other_than_one_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 2\nstations:\n  QR_A:\n    station_id: '1'\n    name: 'A'\n",
    )
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_empty_stations_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 1\nstations: {}\n")
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_item_not_mapping_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 1\nstations:\n  QR_A: 'not a mapping'\n")
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_missing_required_field_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "version: 1\nstations:\n  QR_A:\n    station_id: '1'\n")
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_unknown_field_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\nstations:\n  QR_A:\n    station_id: '1'\n    name: 'A'\n    extra: 'x'\n",
    )
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_empty_strings_raise(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\nstations:\n  QR_A:\n    station_id: ''\n    name: 'A'\n",
    )
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_duplicate_station_id_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        (
            "version: 1\n"
            "stations:\n"
            "  QR_A:\n"
            "    station_id: '1'\n"
            "    name: 'A'\n"
            "  QR_B:\n"
            "    station_id: '1'\n"
            "    name: 'B'\n"
        ),
    )
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


@pytest.mark.parametrize(
    "field",
    [
        "audio_path",
        "turn_to_students_deg",
        "turn_to_front_deg",
        "is_final",
        "llm_zone_id",
        "motion",
        "velocity",
        "duration",
        "conversation",
        "llm",
        "tts",
    ],
)
def test_forbidden_fields_raise(tmp_path: Path, field: str) -> None:
    path = _write(
        tmp_path,
        f"version: 1\nstations:\n  QR_A:\n    station_id: '1'\n    name: 'A'\n    {field}: 'x'\n",
    )
    with pytest.raises(StationRegistryError):
        StationRegistry.from_yaml(path)


def test_production_config_has_exactly_four_authorized_qr_codes() -> None:
    prod_path = Path(_PROJECT_ROOT) / "config" / "qr_stations.yaml"
    registry = StationRegistry.from_yaml(prod_path)
    assert registry.qr_values == frozenset(
        {
            "QR_MOLINETES",
            "QR_HALL_CENTRAL",
            "QR_PASILLO_LIMA2",
            "QR_OFICINAS_GESTION",
        }
    )
    assert len(registry.stations) == 4


def test_production_station_ids_are_subset_of_tour_script_waypoint_ids() -> None:
    prod_path = Path(_PROJECT_ROOT) / "config" / "qr_stations.yaml"
    registry = StationRegistry.from_yaml(prod_path)

    script_path = Path(_PROJECT_ROOT) / "data" / "mvp_tour_script.json"
    with open(script_path, "r", encoding="utf-8") as fh:
        script = json.load(fh)
    script_waypoint_ids = {wp["waypoint_id"] for wp in script["waypoints"]}

    assert registry.station_ids.issubset(script_waypoint_ids)
