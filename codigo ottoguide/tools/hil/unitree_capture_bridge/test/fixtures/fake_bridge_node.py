#!/usr/bin/env python3
"""Minimal stand-in for the real bridge_node executable. Used directly as
BRIDGE_EXECUTABLE by the offline wrapper test suite (cmd_start now launches
the bridge executable directly, with no `ros2 run` indirection, so this
fixture takes no arguments and must behave like the real installed script:
binds the AF_UNIX IPC socket from $IPC_SOCK and waits for SIGINT/SIGTERM,
cleaning the socket up on exit). No ROS or rclpy involved.

Env vars:
  IPC_SOCK                     socket path to bind (required)
  FAKE_BRIDGE_CREATE_SOCKET=0  skip binding the socket (simulates a bridge
                                that never comes up)
  FAKE_BRIDGE_EXIT_IMMEDIATELY=1  exit right away (simulates a crash)
"""
import os
import signal
import socket
import sys
import time

sock_path = os.environ.get("IPC_SOCK", "/tmp/ottoguide_unitree_capture.sock")

if os.environ.get("FAKE_BRIDGE_EXIT_IMMEDIATELY") == "1":
    sys.exit(1)

stop = {"flag": False}


def handle(_signum, _frame):
    stop["flag"] = True


signal.signal(signal.SIGINT, handle)
signal.signal(signal.SIGTERM, handle)

server = None
if os.environ.get("FAKE_BRIDGE_CREATE_SOCKET", "1") == "1":
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(sock_path)

while not stop["flag"]:
    time.sleep(0.05)

if server is not None:
    server.close()
    if os.path.exists(sock_path):
        os.unlink(sock_path)
