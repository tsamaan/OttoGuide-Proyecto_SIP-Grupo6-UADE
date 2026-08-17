"""
@TASK: Guardia de regresion estatica sobre el contrato no-publish del adapter
       de odometria candidata
@INPUT: src/navigation/odometry_candidate_adapter/*.py (codigo fuente, no
        comportamiento en runtime)
@OUTPUT: Aserciones textuales: ausencia de imports ROS/DDS/SDK y de literales
         de topics de publicacion; verificacion de constantes de contrato
@CONTEXT: Adaptado de ODOM-R1 (run local) al layout src/ de este repositorio.
          Complementa (no reemplaza) cualquier gate de CI/linting existente.
@SECURITY: Solo lectura de texto fuente local; no importa ni ejecuta ROS/DDS.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ADAPTER_DIR = REPO_ROOT / "src" / "navigation" / "odometry_candidate_adapter"

FORBIDDEN_IMPORT_RE = re.compile(
    r"^\s*(import|from)\s+(rclpy|nav_msgs|geometry_msgs|tf2_ros|tf2|unitree_sdk2)\b",
    re.MULTILINE,
)

FORBIDDEN_TOPIC_LITERAL_RE = re.compile(r"(/cmd_vel|/odom['\"]|/tf)")

FORBIDDEN_PUBLICATION_API_RE = re.compile(
    r"\b(create_publisher|Publisher|CreateSendChannel|ChannelPublisher)\b"
)

FORBIDDEN_CONTROL_API_RE = re.compile(
    r"\b(LowCmd|LocoClient|SportClient|SetVelocity)\b|\bstand\(|\bwalk\(|\bdamp\(|\bMove\("
)


def _adapter_source_files():
    return sorted(ADAPTER_DIR.glob("*.py"))


class TestContractRegression:
    def test_adapter_package_exists(self):
        files = _adapter_source_files()
        assert len(files) >= 4, f"expected at least 4 .py files, found {files}"

    def test_no_forbidden_imports_in_adapter(self):
        for path in _adapter_source_files():
            text = path.read_text(encoding="utf-8")
            match = FORBIDDEN_IMPORT_RE.search(text)
            assert match is None, f"forbidden import in {path.name}: {match.group(0) if match else ''}"

    def test_no_forbidden_topic_literals_in_adapter(self):
        for path in _adapter_source_files():
            text = path.read_text(encoding="utf-8")
            match = FORBIDDEN_TOPIC_LITERAL_RE.search(text)
            assert match is None, f"forbidden topic literal in {path.name}: {match.group(0) if match else ''}"

    def test_no_forbidden_publication_apis_in_adapter(self):
        for path in _adapter_source_files():
            text = path.read_text(encoding="utf-8")
            match = FORBIDDEN_PUBLICATION_API_RE.search(text)
            assert match is None, f"forbidden publication API in {path.name}: {match.group(0) if match else ''}"

    def test_no_forbidden_control_apis_in_adapter(self):
        for path in _adapter_source_files():
            text = path.read_text(encoding="utf-8")
            match = FORBIDDEN_CONTROL_API_RE.search(text)
            assert match is None, f"forbidden control API in {path.name}: {match.group(0) if match else ''}"

    def test_contract_constants_match_mfr_r6(self):
        from src.navigation.odometry_candidate_adapter.validation import (
            COVARIANCE_POLICY,
            FRAME_ID,
            TIMESTAMP_POLICY,
        )
        assert TIMESTAMP_POLICY == "MESSAGE_STAMP_ZERO_USE_RECEIPT_TIME_REQUIRED"
        assert FRAME_ID == "unitree_odom_candidate"
        assert COVARIANCE_POLICY == "NO_COVARIANCE_IN_SOURCE_DOCUMENT_GAP"
