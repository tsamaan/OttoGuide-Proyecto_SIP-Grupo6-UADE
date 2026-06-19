"""AF_UNIX SOCK_DGRAM socket-layer tests for the capture bridge protocol.

These exercise protocol.create_ros_socket_server / protocol.receive_packet
directly with real sockets bound under a tempfile.TemporaryDirectory. No
rclpy and no ROS runtime is required.
"""

import json
import os
import socket
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ottoguide_unitree_capture_bridge.protocol import (
    RECV_BUFSIZE,
    ParseError,
    create_ros_socket_server,
    receive_packet,
)

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="AF_UNIX sockets are not available on this platform (e.g. native Windows Python)",
)


def lowstate_payload(pad_to=None):
    packet = {
        "v": 1,
        "k": "lowstate",
        "t": 1_000_000_000,
        "ch": "rt/lowstate",
        "tick": 1,
        "mm": 0,
        "lx": 0.0,
        "ly": 0.0,
        "rx": 0.0,
        "ry": 0.0,
        "keys": 0,
        "q": [1.0, 0.0, 0.0, 0.0],
        "g": [0.0, 0.0, 0.0],
        "a": [0.0, 0.0, 9.81],
        "rpy": [0.0, 0.0, 0.0],
    }
    if pad_to is not None:
        packet["pad"] = ""
        overhead = pad_to - len(json.dumps(packet).encode("utf-8"))
        packet["pad"] = "x" * max(0, overhead)
    return json.dumps(packet).encode("utf-8")


@pytest.fixture
def sock_path():
    with tempfile.TemporaryDirectory() as tmp:
        yield os.path.join(tmp, "capture.sock")


def test_create_and_bind_creates_socket_file(sock_path):
    server = create_ros_socket_server(sock_path)
    try:
        assert os.path.exists(sock_path)
        import stat as stat_module
        assert stat_module.S_ISSOCK(os.lstat(sock_path).st_mode)
    finally:
        server.close()


def test_stale_socket_cleanup_recreates_bindable_socket(sock_path):
    stale = create_ros_socket_server(sock_path)
    stale.close()
    assert os.path.exists(sock_path), "stale socket file should remain after close"

    server = create_ros_socket_server(sock_path)
    try:
        assert os.path.exists(sock_path)
    finally:
        server.close()


def test_socket_occupied_by_regular_file_raises(sock_path):
    with open(sock_path, "w", encoding="utf-8") as handle:
        handle.write("not a socket")

    with pytest.raises(RuntimeError):
        create_ros_socket_server(sock_path)

    assert os.path.exists(sock_path), "regular file must not be deleted"
    with open(sock_path, "r", encoding="utf-8") as handle:
        assert handle.read() == "not a socket"


def test_socket_absent_receive_returns_none(sock_path):
    server = create_ros_socket_server(sock_path)
    try:
        assert receive_packet(server) is None
    finally:
        server.close()


def test_receive_multiple_datagrams_in_order(sock_path):
    server = create_ros_socket_server(sock_path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        for tick in range(1, 6):
            packet = json.loads(lowstate_payload())
            packet["tick"] = tick
            client.sendto(json.dumps(packet).encode("utf-8"), sock_path)
        received_ticks = []
        for _ in range(5):
            packet = receive_packet(server)
            assert packet is not None
            received_ticks.append(packet["tick"])
        assert received_ticks == [1, 2, 3, 4, 5]
    finally:
        client.close()
        server.close()


def test_max_size_datagram_accepted(sock_path):
    server = create_ros_socket_server(sock_path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        payload = lowstate_payload(pad_to=RECV_BUFSIZE)
        assert len(payload) <= RECV_BUFSIZE
        client.sendto(payload, sock_path)
        packet = receive_packet(server)
        assert packet is not None
        assert packet["k"] == "lowstate"
    finally:
        client.close()
        server.close()


def test_oversized_datagram_rejected_gracefully(sock_path):
    server = create_ros_socket_server(sock_path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        oversized = lowstate_payload(pad_to=RECV_BUFSIZE * 4)
        assert len(oversized) > RECV_BUFSIZE
        client.sendto(oversized, sock_path)
        with pytest.raises(ParseError):
            receive_packet(server)
    finally:
        client.close()
        server.close()


def test_parse_error_does_not_corrupt_subsequent_reads(sock_path):
    server = create_ros_socket_server(sock_path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(b"{not-json", sock_path)
        client.sendto(lowstate_payload(), sock_path)

        with pytest.raises(ParseError):
            receive_packet(server)

        packet = receive_packet(server)
        assert packet is not None
        assert packet["k"] == "lowstate"
    finally:
        client.close()
        server.close()


def test_synthetic_drop_counting_pattern(sock_path):
    """Mirrors bridge_node._poll_ipc's drop-counting loop without rclpy."""
    server = create_ros_socket_server(sock_path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(b"{bad-1", sock_path)
        client.sendto(lowstate_payload(), sock_path)
        client.sendto(b"{bad-2", sock_path)

        drops = 0
        received = 0
        for _ in range(10):
            try:
                packet = receive_packet(server)
            except ParseError:
                drops += 1
                continue
            if packet is None:
                break
            received += 1
        assert drops == 2
        assert received == 1
    finally:
        client.close()
        server.close()


def test_clean_shutdown_close_and_unlink(sock_path):
    server = create_ros_socket_server(sock_path)
    server.close()
    assert os.path.exists(sock_path)
    os.unlink(sock_path)
    assert not os.path.exists(sock_path)
