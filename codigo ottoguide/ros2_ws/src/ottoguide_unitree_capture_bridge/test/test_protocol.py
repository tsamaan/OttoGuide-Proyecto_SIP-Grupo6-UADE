import json
import math
import os
import sys
import ast
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ottoguide_unitree_capture_bridge.protocol import (
    ALLOWED_TOPICS,
    BUTTON_NAMES,
    PROHIBITED_TOPICS,
    ParseError,
    assert_not_prohibited,
    keys_to_buttons,
    make_imu_dict,
    packet_age_seconds,
    parse_packet,
)


def encoded(packet):
    return json.dumps(packet).encode("utf-8")


def lowstate(**updates):
    packet = {
        "v": 1,
        "k": "lowstate",
        "t": 1_000_000_000,
        "ch": "rt/lowstate",
        "tick": 100,
        "mm": 5,
        "lx": 0.1,
        "ly": -0.2,
        "rx": 0.3,
        "ry": -0.4,
        "keys": 0,
        "q": [1.0, 0.0, 0.0, 0.0],
        "g": [0.1, 0.2, 0.3],
        "a": [0.0, 0.0, 9.81],
        "rpy": [0.01, 0.02, 0.03],
    }
    packet.update(updates)
    return packet


def secondary_imu(**updates):
    packet = lowstate(k="secondary_imu")
    for key in ("ch", "tick", "mm", "lx", "ly", "rx", "ry", "keys"):
        packet.pop(key)
    packet.update(updates)
    return packet


def sport_state(**updates):
    packet = {"v": 1, "k": "sport_state", "t": 1, "fsm": 7}
    packet.update(updates)
    return packet


def health(**updates):
    packet = {
        "v": 1,
        "k": "health",
        "t": 1,
        "up": 2.5,
        "n_ls": 10,
        "n_lf_ls": 0,
        "n_simu": 10,
        "n_sport": 1,
        "n_sent": 5,
        "n_drop": 0,
    }
    packet.update(updates)
    return packet


@pytest.mark.parametrize("packet", [lowstate(), secondary_imu(), sport_state(), health()])
def test_valid_packets(packet):
    assert parse_packet(encoded(packet)) == packet


@pytest.mark.parametrize("raw", [b"", b"not-json", b"[]", b"\xff"])
def test_invalid_datagrams(raw):
    with pytest.raises(ParseError):
        parse_packet(raw)


@pytest.mark.parametrize("field", [
    "v", "k", "t", "ch", "tick", "mm", "lx", "ly", "rx", "ry",
    "keys", "q", "g", "a", "rpy",
])
def test_lowstate_missing_field(field):
    packet = lowstate()
    packet.pop(field)
    with pytest.raises(ParseError):
        parse_packet(encoded(packet))


@pytest.mark.parametrize("field,value", [
    ("v", True), ("t", -1), ("tick", "100"), ("mm", None),
    ("lx", "0.1"), ("keys", 65536), ("keys", True),
])
def test_lowstate_wrong_scalar_type_or_range(field, value):
    with pytest.raises(ParseError):
        parse_packet(encoded(lowstate(**{field: value})))


@pytest.mark.parametrize("field,value", [
    ("q", [1.0, 0.0, 0.0]),
    ("g", [0.0, 0.0]),
    ("a", [0.0, 0.0, "bad"]),
    ("rpy", [0.0, math.inf, 0.0]),
])
def test_invalid_imu_vectors(field, value):
    with pytest.raises(ParseError):
        parse_packet(encoded(lowstate(**{field: value})))


def test_lowstate_source_is_exact():
    with pytest.raises(ParseError):
        parse_packet(encoded(lowstate(ch="rt/lf/lowstate")))


def test_fsm_validation():
    assert parse_packet(encoded(sport_state(fsm=4)))["fsm"] == 4
    with pytest.raises(ParseError):
        parse_packet(encoded(sport_state(fsm="4")))


def test_health_requires_drop_and_sent_counters():
    assert parse_packet(encoded(health(n_drop=3)))["n_drop"] == 3
    packet = health()
    packet.pop("n_sent")
    with pytest.raises(ParseError):
        parse_packet(encoded(packet))


def test_joy_axes_and_buttons_order_contract():
    packet = parse_packet(encoded(lowstate(lx=1.0, ly=2.0, rx=3.0, ry=4.0)))
    assert [packet[name] for name in ("lx", "ly", "rx", "ry")] == [1.0, 2.0, 3.0, 4.0]
    assert BUTTON_NAMES == [
        "R1", "L1", "Start", "Select", "R2", "L2", "F1", "F2",
        "A", "B", "X", "Y", "Up", "Right", "Down", "Left",
    ]
    assert keys_to_buttons((1 << 0) | (1 << 7) | (1 << 15)) == [
        1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1,
    ]


def test_imu_and_quaternion_contract():
    values = make_imu_dict(lowstate(q=[0.9, 0.1, 0.2, 0.3]))
    assert values["q"] == [0.9, 0.1, 0.2, 0.3]
    assert values["a"] == [0.0, 0.0, 9.81]


def test_packet_age_uses_monotonic_nanoseconds():
    assert packet_age_seconds(health(t=1_000_000_000), 3_500_000_000) == 2.5


def test_topic_allowlist_is_exact_and_control_topics_are_rejected():
    assert ALLOWED_TOPICS == frozenset({
        "/unitree/remote_joy",
        "/unitree/lowstate_imu",
        "/unitree/secondary_imu",
        "/unitree/fsm_state",
        "/unitree/lowstate_summary",
        "/unitree/sdk_health",
    })
    assert not ALLOWED_TOPICS & PROHIBITED_TOPICS
    for topic in ALLOWED_TOPICS:
        assert_not_prohibited(topic)
    for topic in PROHIBITED_TOPICS | {"/unitree/not_allowed", "/other"}:
        with pytest.raises(RuntimeError):
            assert_not_prohibited(topic)


def test_bridge_source_has_no_unitree_sdk_imports():
    source = Path(__file__).parents[1] / "ottoguide_unitree_capture_bridge" / "bridge_node.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not [name for name in imported if name.startswith("unitree")]
