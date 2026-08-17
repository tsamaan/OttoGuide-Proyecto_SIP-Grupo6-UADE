"""
@TASK: Definir el registro canonico de estaciones QR del tour (U2)
@INPUT: Archivo YAML estricto con esquema {version: 1, stations: {QR_VALUE: {station_id, name}}}
@OUTPUT: StationRegistry inmutable que resuelve qr_value -> StationDefinition
@CONTEXT: U2 — Integracion del sensor QR. Este registro es la unica fuente de verdad
          para traducir un valor QR leido por la camara compartida en un station_id
          logico del tour. No conoce movimiento, audio, LLM ni FSM.
@SECURITY: Solo depende de biblioteca estandar y PyYAML. Rechaza explicitamente
           cualquier campo de movimiento, audio o LLM en el esquema para impedir que
           configuracion de estaciones se convierta en un canal de control oculto.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

_FORBIDDEN_ITEM_FIELDS: frozenset[str] = frozenset(
    {
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
    }
)

_REQUIRED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({"version", "stations"})
_REQUIRED_ITEM_FIELDS: frozenset[str] = frozenset({"station_id", "name"})
_SUPPORTED_VERSION: int = 1


class StationRegistryError(Exception):
    """Error tipado del registro de estaciones; mensajes sin contenido sensible."""


@dataclass(frozen=True, slots=True)
class StationDefinition:
    qr_value: str
    station_id: str
    name: str

    def __post_init__(self) -> None:
        if not self.qr_value.strip():
            raise StationRegistryError("qr_value must not be empty")
        if not self.station_id.strip():
            raise StationRegistryError("station_id must not be empty")
        if not self.name.strip():
            raise StationRegistryError("name must not be empty")


class StationRegistry:
    """
    @TASK: Resolver definiciones de estacion a partir de un esquema YAML estricto
    @CONTEXT: from_yaml() es el unico punto de carga; resolve() es de solo lectura.
    """

    def __init__(self, stations: tuple[StationDefinition, ...]) -> None:
        self._stations: tuple[StationDefinition, ...] = stations
        self._by_qr_value: dict[str, StationDefinition] = {
            station.qr_value: station for station in stations
        }

    @classmethod
    def from_yaml(cls, path: Path) -> "StationRegistry":
        if not path.exists():
            raise StationRegistryError(f"config file not found: {path}")

        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StationRegistryError(f"failed to read config file: {type(exc).__name__}") from exc

        try:
            data = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise StationRegistryError(f"invalid YAML syntax: {type(exc).__name__}") from exc

        if not isinstance(data, Mapping):
            raise StationRegistryError("top-level YAML content must be a mapping")

        top_level_keys = set(data.keys())
        missing_top_level = _REQUIRED_TOP_LEVEL_KEYS - top_level_keys
        if missing_top_level:
            raise StationRegistryError(f"missing top-level keys: {sorted(missing_top_level)}")
        unknown_top_level = top_level_keys - _REQUIRED_TOP_LEVEL_KEYS
        if unknown_top_level:
            raise StationRegistryError(f"unknown top-level keys: {sorted(unknown_top_level)}")

        version = data["version"]
        if not isinstance(version, int) or isinstance(version, bool):
            raise StationRegistryError("version must be an integer")
        if version != _SUPPORTED_VERSION:
            raise StationRegistryError(f"unsupported version: {version}")

        stations_raw = data["stations"]
        if not isinstance(stations_raw, Mapping):
            raise StationRegistryError("stations must be a mapping")
        if not stations_raw:
            raise StationRegistryError("stations must not be empty")

        stations: list[StationDefinition] = []
        seen_station_ids: set[str] = set()
        seen_qr_values: set[str] = set()

        for qr_value_raw, item in stations_raw.items():
            if not isinstance(qr_value_raw, str):
                raise StationRegistryError("qr_value keys must be strings")
            qr_value = qr_value_raw.strip()
            if not qr_value:
                raise StationRegistryError("qr_value must not be empty after trim")

            if not isinstance(item, Mapping):
                raise StationRegistryError(f"station item for qr_value={qr_value!r} must be a mapping")

            item_keys = set(item.keys())
            missing_item_fields = _REQUIRED_ITEM_FIELDS - item_keys
            if missing_item_fields:
                raise StationRegistryError(
                    f"station item for qr_value={qr_value!r} missing fields: {sorted(missing_item_fields)}"
                )
            unknown_item_fields = item_keys - _REQUIRED_ITEM_FIELDS
            if unknown_item_fields:
                raise StationRegistryError(
                    f"station item for qr_value={qr_value!r} has unknown fields: {sorted(unknown_item_fields)}"
                )
            forbidden_present = item_keys & _FORBIDDEN_ITEM_FIELDS
            if forbidden_present:
                raise StationRegistryError(
                    f"station item for qr_value={qr_value!r} contains forbidden fields: {sorted(forbidden_present)}"
                )

            station_id_raw = item["station_id"]
            name_raw = item["name"]
            if not isinstance(station_id_raw, str) or not station_id_raw.strip():
                raise StationRegistryError(f"station_id for qr_value={qr_value!r} must be a non-empty string")
            if not isinstance(name_raw, str) or not name_raw.strip():
                raise StationRegistryError(f"name for qr_value={qr_value!r} must be a non-empty string")

            station_id = station_id_raw.strip()
            name = name_raw.strip()

            if qr_value in seen_qr_values:
                raise StationRegistryError(f"duplicate qr_value after normalization: {qr_value!r}")
            if station_id in seen_station_ids:
                raise StationRegistryError(f"duplicate station_id: {station_id!r}")

            seen_qr_values.add(qr_value)
            seen_station_ids.add(station_id)
            stations.append(
                StationDefinition(qr_value=qr_value, station_id=station_id, name=name)
            )

        return cls(tuple(stations))

    def resolve(self, qr_value: str) -> StationDefinition | None:
        return self._by_qr_value.get(qr_value)

    @property
    def stations(self) -> tuple[StationDefinition, ...]:
        return self._stations

    @property
    def qr_values(self) -> frozenset[str]:
        return frozenset(self._by_qr_value.keys())

    @property
    def station_ids(self) -> frozenset[str]:
        return frozenset(station.station_id for station in self._stations)


__all__ = [
    "StationDefinition",
    "StationRegistry",
    "StationRegistryError",
]
