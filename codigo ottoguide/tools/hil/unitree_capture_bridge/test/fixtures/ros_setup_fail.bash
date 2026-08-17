#!/usr/bin/env bash
# Fake setup.bash that fails intentionally, to prove source_ros never
# swallows a real error from the sourced script.
echo "[fake-foxy-setup] intentional failure" >&2
exit 1
