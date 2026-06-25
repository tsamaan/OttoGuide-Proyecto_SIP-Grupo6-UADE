#!/usr/bin/env python3
"""Tests for assert_no_cmd_vel_publishers.sh (fail-closed cmd_vel guard).

All tests use a stub ros2 binary and a stub setup.bash.  No ROS installation
or live graph is required.  Each test controls exactly what ros2 returns.

The bash interpreter is discovered in this order:
  1. OTTOGUIDE_TEST_BASH environment variable
  2. C:\\Program Files\\Git\\bin\\bash.exe
  3. C:\\Program Files\\Git\\usr\\bin\\bash.exe
  4. shutil.which("bash")

If no bash is found, every test is skipped.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
REPO_ROOT = _HERE.parents[3]
CODE_ROOT = REPO_ROOT / "codigo ottoguide"
SCRIPT = CODE_ROOT / "tools" / "hil" / "assert_no_cmd_vel_publishers.sh"


# ---------------------------------------------------------------------------
# Bash discovery
# ---------------------------------------------------------------------------
def _find_bash() -> str | None:
    env_bash = os.environ.get("OTTOGUIDE_TEST_BASH")
    if env_bash and os.path.isfile(env_bash):
        return env_bash
    for candidate in [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("bash")


BASH = _find_bash()


def _w2u(p: Path) -> str:
    """Convert an absolute Windows path to a Git Bash-compatible Unix path."""
    s = str(p).replace("\\", "/")
    if len(s) >= 2 and s[1] == ":":
        return "/" + s[0].lower() + s[2:]
    return s


# ---------------------------------------------------------------------------
# Stub builder
# ---------------------------------------------------------------------------
def _make_stubs(
    td: Path,
    *,
    list_out: str = "",
    list_err: str = "",
    list_rc: int = 0,
    info_out: str = "",
    info_err: str = "",
    info_rc: int = 0,
    list_sleep: int = 0,
    info_sleep: int = 0,
) -> None:
    """Create a fake ros2 binary and a matching setup.bash in *td*."""
    bindir = td / "bin"
    bindir.mkdir(exist_ok=True)

    (td / "_list.out").write_bytes(list_out.encode("utf-8"))
    (td / "_list.err").write_bytes(list_err.encode("utf-8"))
    (td / "_info.out").write_bytes(info_out.encode("utf-8"))
    (td / "_info.err").write_bytes(info_err.encode("utf-8"))

    td_u = _w2u(td)
    sleep_list = f"sleep {list_sleep} && " if list_sleep > 0 else ""
    sleep_info = f"sleep {info_sleep} && " if info_sleep > 0 else ""

    stub = textwrap.dedent("""\
        #!/usr/bin/env bash
        CMD="$1"
        SUB="${2:-}"
        TD="%(td_u)s"
        if [[ "$CMD" == "topic" && "$SUB" == "list" ]]; then
            %(sleep_list)scat "$TD/_list.out"
            cat "$TD/_list.err" >&2
            exit %(list_rc)d
        elif [[ "$CMD" == "topic" && "$SUB" == "info" ]]; then
            %(sleep_info)scat "$TD/_info.out"
            cat "$TD/_info.err" >&2
            exit %(info_rc)d
        fi
        exit 127
        """) % {
        "td_u": td_u,
        "list_rc": list_rc,
        "info_rc": info_rc,
        "sleep_list": sleep_list,
        "sleep_info": sleep_info,
    }
    ros2_path = bindir / "ros2"
    ros2_path.write_text(stub, encoding="utf-8")
    ros2_path.chmod(ros2_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    setup = td / "setup.bash"
    setup.write_text(
        '#!/usr/bin/env bash\nexport PATH="%(bindir_u)s:$PATH"\n'
        % {"bindir_u": _w2u(bindir)},
        encoding="utf-8",
    )
    setup.chmod(setup.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _status(proc: subprocess.CompletedProcess) -> str:
    """Extract the STATUS=... line from stdout."""
    for line in proc.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("STATUS="):
            return stripped
    return ""


def _run(td: Path, env_extra: dict | None = None, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run the guard script with a controlled environment."""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": _w2u(td),
        "TMPDIR": _w2u(td),
        "CMD_VEL_ASSERT_TIMEOUT_S": "2",
        "OTTOGUIDE_ROS_SETUP": _w2u(td / "setup.bash"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [BASH, _w2u(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@unittest.skipIf(BASH is None, "No bash interpreter found; set OTTOGUIDE_TEST_BASH")
class TestAssertNoCmdVelPublishers(unittest.TestCase):

    # T01 — nominal: topic present, 0 publishers → exit 0
    def test_t01_zero_publishers(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(
                p,
                list_out="/cmd_vel\n/tf\n/odom\n",
                info_out="Type: geometry_msgs/msg/Twist\nPublisher count: 0\nSubscription count: 0\n",
            )
            proc = _run(p)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=SAFE_ZERO_PUBLISHERS")

    # T02 — topic present, 1 publisher → exit 1
    def test_t02_publishers_present(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(
                p,
                list_out="/cmd_vel\n/tf\n",
                info_out="Type: geometry_msgs/msg/Twist\nPublisher count: 1\nSubscription count: 0\n",
            )
            proc = _run(p)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=PUBLISHERS_PRESENT")

    # T03 — topic absent from topic list → exit 2
    def test_t03_topic_absent(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(p, list_out="/tf\n/odom\n/scan\n")
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=TOPIC_ABSENT")

    # T04 — topic_info output lacks Publisher count line → exit 2
    def test_t04_no_publisher_count_line(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(
                p,
                list_out="/cmd_vel\n",
                info_out="Type: geometry_msgs/msg/Twist\nSubscription count: 0\n",
            )
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=PARSE_ERROR")

    # T05 — topic_info stdout is empty → exit 2
    def test_t05_empty_topic_info(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(p, list_out="/cmd_vel\n", info_out="")
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=PARSE_ERROR")

    # T06 — publisher count value non-numeric (no match → 0 matches) → exit 2
    def test_t06_publisher_count_non_numeric(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(
                p,
                list_out="/cmd_vel\n",
                info_out="Type: geometry_msgs/msg/Twist\nPublisher count: unknown\nSubscription count: 0\n",
            )
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=PARSE_ERROR")

    # T07 — two Publisher count lines → exit 2
    def test_t07_two_publisher_count_lines(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(
                p,
                list_out="/cmd_vel\n",
                info_out=(
                    "Type: geometry_msgs/msg/Twist\n"
                    "Publisher count: 0\n"
                    "Publisher count: 0\n"
                    "Subscription count: 0\n"
                ),
            )
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=PARSE_ERROR")

    # T08 — ros2 topic list returns non-zero exit → exit 2
    def test_t08_topic_list_command_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(p, list_rc=1, list_err="DDS error\n")
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=COMMAND_ERROR")

    # T09 — ros2 topic info returns non-zero exit → exit 2
    def test_t09_topic_info_command_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(
                p,
                list_out="/cmd_vel\n",
                info_rc=1,
                info_err="topic not found\n",
            )
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=COMMAND_ERROR")

    # T10 — ros2 exceeds timeout → exit 2
    def test_t10_command_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(p, list_sleep=10)
            proc = _run(p, env_extra={"CMD_VEL_ASSERT_TIMEOUT_S": "1"}, timeout=15)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=COMMAND_TIMEOUT")

    # T11 — ros2 topic info writes stderr despite exit 0 → exit 2
    def test_t11_info_stderr_with_exit_zero(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(
                p,
                list_out="/cmd_vel\n",
                info_out="Type: geometry_msgs/msg/Twist\nPublisher count: 0\nSubscription count: 0\n",
                info_err="[WARN] rmw discovery warning\n",
                info_rc=0,
            )
            proc = _run(p)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=COMMAND_ERROR")

    # T12 — OTTOGUIDE_ROS_SETUP points to non-existent file → exit 2
    def test_t12_override_setup_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            proc = _run(
                p,
                env_extra={"OTTOGUIDE_ROS_SETUP": "/nonexistent/path/setup.bash"},
            )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=ROS2_UNAVAILABLE")

    # T13 — invalid timeout value → exit 2
    def test_t13_invalid_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            _make_stubs(p, list_out="/cmd_vel\n")
            proc = _run(p, env_extra={"CMD_VEL_ASSERT_TIMEOUT_S": "0"})
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(_status(proc), "STATUS=INVALID_CONFIGURATION")


# ---------------------------------------------------------------------------
# Static content verification (no bash execution needed)
# ---------------------------------------------------------------------------
class TestAssertNoCmdVelStaticContent(unittest.TestCase):
    """Verify structural properties of the script without running it."""

    def _text(self):
        return SCRIPT.read_text(encoding="utf-8")

    def test_foxy_prefix_present(self):
        self.assertIn("/opt/ros/foxy/setup.bash", self._text(),
                      "Foxy setup path must appear in the ROS detection list")

    def test_pipe_or_true_absent(self):
        self.assertNotIn("|| true", self._text(),
                         "Fail-open '|| true' must not appear in the parser")

    def test_default_zero_absent(self):
        self.assertNotIn("${PUBLISHER_COUNT:-0}", self._text(),
                         "Fail-open default '${PUBLISHER_COUNT:-0}' must be absent")

    def test_has_shebang(self):
        self.assertTrue(self._text().startswith("#!/usr/bin/env bash"),
                        "Script must start with #!/usr/bin/env bash")

    def test_uses_pipefail(self):
        self.assertIn("pipefail", self._text(),
                      "Script must set pipefail")

    def test_lc_all_export(self):
        self.assertIn("LC_ALL=C", self._text(),
                      "Script must export LC_ALL=C for locale-independent parsing")

    def test_no_grep_in_parser(self):
        # The old parser used grep; the new one must not
        import re
        # Allow grep only inside comments
        non_comment_lines = [
            ln for ln in self._text().splitlines()
            if not ln.lstrip().startswith("#")
        ]
        non_comment_text = "\n".join(non_comment_lines)
        self.assertNotRegex(non_comment_text, r'\bgrep\b',
                            "Parser must not use grep; use Bash regex instead")

    def test_no_awk_in_parser(self):
        non_comment_lines = [
            ln for ln in self._text().splitlines()
            if not ln.lstrip().startswith("#")
        ]
        self.assertNotIn("awk", "\n".join(non_comment_lines),
                         "Parser must not use awk")

    def test_ottoguide_ros_setup_seam_present(self):
        self.assertIn("OTTOGUIDE_ROS_SETUP", self._text(),
                      "Test/override seam OTTOGUIDE_ROS_SETUP must be present")

    def test_status_safe_zero_publishers_present(self):
        self.assertIn("STATUS=SAFE_ZERO_PUBLISHERS", self._text())

    def test_status_topic_absent_present(self):
        self.assertIn("STATUS=TOPIC_ABSENT", self._text())

    def test_status_parse_error_present(self):
        self.assertIn("STATUS=PARSE_ERROR", self._text())


if __name__ == "__main__":
    unittest.main()
