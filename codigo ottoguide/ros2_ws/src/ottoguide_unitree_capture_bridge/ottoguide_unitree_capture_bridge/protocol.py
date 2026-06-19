"""Validated AF_UNIX protocol for the receive-only Unitree capture bridge."""

import json
import math
import os
import socket
import stat
import time
from typing import Any, Dict, List, Optional, Sequence

PROTOCOL_VERSION = 1
SOCK_PATH = "/tmp/ottoguide_unitree_capture.sock"
RECV_BUFSIZE = 4096

ALLOWED_TOPICS = frozenset({
    "/unitree/remote_joy",
    "/unitree/lowstate_imu",
    "/unitree/secondary_imu",
    "/unitree/fsm_state",
    "/unitree/lowstate_summary",
    "/unitree/sdk_health",
})

PROHIBITED_TOPICS = frozenset({
    "/cmd_vel",
    "/odom",
    "/tf",
    "/tf_static",
    "/api/sport/request",
    "/api/sport/response",
})

BUTTON_NAMES = [
    "R1", "L1", "Start", "Select", "R2", "L2", "F1", "F2",
    "A", "B", "X", "Y", "Up", "Right", "Down", "Left",
]
BUTTON_MASKS = [1 << index for index in range(len(BUTTON_NAMES))]


class ParseError(ValueError):
    """A datagram violated the capture bridge protocol."""


def assert_not_prohibited(topic: str) -> None:
    if topic in PROHIBITED_TOPICS or topic not in ALLOWED_TOPICS:
        raise RuntimeError("SAFETY_CONTRACT_VIOLATED: {}".format(topic))


def _require_dict(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ParseError("packet must be a JSON object")
    return value


def _require_int(packet: Dict[str, Any], name: str, minimum: int = 0,
                 maximum: Optional[int] = None) -> int:
    value = packet.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParseError("{} must be an integer".format(name))
    if value < minimum or (maximum is not None and value > maximum):
        raise ParseError("{} outside range".format(name))
    return value


def _require_number(packet: Dict[str, Any], name: str) -> float:
    value = packet.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParseError("{} must be numeric".format(name))
    result = float(value)
    if not math.isfinite(result):
        raise ParseError("{} must be finite".format(name))
    return result


def _require_vector(packet: Dict[str, Any], name: str, length: int) -> List[float]:
    value = packet.get(name)
    if not isinstance(value, list) or len(value) != length:
        raise ParseError("{} must contain {} values".format(name, length))
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ParseError("{} values must be numeric".format(name))
        number = float(item)
        if not math.isfinite(number):
            raise ParseError("{} values must be finite".format(name))
        result.append(number)
    return result


def parse_packet(raw: bytes) -> Dict[str, Any]:
    if not isinstance(raw, bytes) or not raw or len(raw) > RECV_BUFSIZE:
        raise ParseError("invalid datagram size")
    try:
        packet = _require_dict(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError("invalid UTF-8 JSON") from exc

    if _require_int(packet, "v", PROTOCOL_VERSION, PROTOCOL_VERSION) != PROTOCOL_VERSION:
        raise ParseError("unsupported version")
    kind = packet.get("k")
    if kind not in {"lowstate", "secondary_imu", "sport_state", "health"}:
        raise ParseError("unknown packet kind")
    _require_int(packet, "t")

    if kind == "lowstate":
        if packet.get("ch") != "rt/lowstate":
            raise ParseError("lowstate source must be rt/lowstate")
        _require_int(packet, "tick", 0, 0xFFFFFFFF)
        _require_int(packet, "mm", 0, 0xFFFFFFFF)
        for field in ("lx", "ly", "rx", "ry"):
            _require_number(packet, field)
        _require_int(packet, "keys", 0, 0xFFFF)
        _require_imu(packet)
    elif kind == "secondary_imu":
        _require_imu(packet)
    elif kind == "sport_state":
        _require_int(packet, "fsm", 0, 0xFFFFFFFF)
    else:
        _require_number(packet, "up")
        for field in ("n_ls", "n_lf_ls", "n_simu", "n_sport", "n_sent", "n_drop"):
            _require_int(packet, field)
    return packet


def _require_imu(packet: Dict[str, Any]) -> None:
    _require_vector(packet, "q", 4)
    _require_vector(packet, "g", 3)
    _require_vector(packet, "a", 3)
    _require_vector(packet, "rpy", 3)


def keys_to_buttons(keys: int) -> List[int]:
    if isinstance(keys, bool) or not isinstance(keys, int) or not 0 <= keys <= 0xFFFF:
        raise ValueError("keys must be an unsigned 16-bit integer")
    return [1 if keys & mask else 0 for mask in BUTTON_MASKS]


def make_imu_dict(packet: Dict[str, Any]) -> Dict[str, List[float]]:
    return {
        "q": _require_vector(packet, "q", 4),
        "g": _require_vector(packet, "g", 3),
        "a": _require_vector(packet, "a", 3),
        "rpy": _require_vector(packet, "rpy", 3),
    }


def packet_age_seconds(packet: Dict[str, Any], now_ns: Optional[int] = None) -> float:
    timestamp = _require_int(packet, "t")
    current = time.monotonic_ns() if now_ns is None else now_ns
    return max(0.0, (current - timestamp) / 1_000_000_000.0)


def create_ros_socket_server(path: str = SOCK_PATH) -> socket.socket:
    if os.path.lexists(path):
        mode = os.lstat(path).st_mode
        if not stat.S_ISSOCK(mode):
            raise RuntimeError("refusing to replace non-socket path: {}".format(path))
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(path)
    server.settimeout(0.1)
    return server


def receive_packet(server: socket.socket) -> Optional[Dict[str, Any]]:
    try:
        return parse_packet(server.recv(RECV_BUFSIZE))
    except socket.timeout:
        return None
