#!/usr/bin/env python3
"""Minimal stand-in for the real bridge_node: binds the AF_UNIX IPC socket
and waits for SIGINT/SIGTERM, cleaning the socket up on exit. Used only by
the offline wrapper test suite's fake `ros2 run` to simulate a healthy
bridge process without ROS or rclpy."""
import os
import signal
import socket
import sys
import time

sock_path = sys.argv[1]
stop = {"flag": False}


def handle(_signum, _frame):
    stop["flag"] = True


signal.signal(signal.SIGINT, handle)
signal.signal(signal.SIGTERM, handle)

if os.path.exists(sock_path):
    os.unlink(sock_path)
server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
server.bind(sock_path)

while not stop["flag"]:
    time.sleep(0.05)

server.close()
if os.path.exists(sock_path):
    os.unlink(sock_path)
