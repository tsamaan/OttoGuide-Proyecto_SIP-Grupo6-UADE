from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SCRIPT = PROJECT_ROOT / "scripts" / "hil_capture_mapping_bundle.sh"
RECORDER_SCRIPT = PROJECT_ROOT / "scripts" / "hil_mapping_recorder.sh"


def test_hil_capture_bundle_has_no_eval_and_declares_manifest() -> None:
    # @TASK: Validar contrato estatico del bundle HIL
    # @INPUT: Script hil_capture_mapping_bundle.sh
    # @OUTPUT: Sin eval, con manifest y dry-run declarados
    # @CONTEXT: Evita regresion a orquestacion ad hoc sin trazabilidad
    # @SECURITY: Bloquea eval en checks de readiness
    text = BUNDLE_SCRIPT.read_text(encoding="utf-8")

    assert "eval " not in text
    assert "MANIFEST_PATH" in text
    assert "HIL_DRY_RUN" in text
    assert 'wait_for_topic "/scan"' in text


def test_hil_mapping_recorder_accepts_exact_bag_path() -> None:
    # @TASK: Validar path exacto de rosbag2
    # @INPUT: Script hil_mapping_recorder.sh
    # @OUTPUT: Uso de HIL_BAG_PATH como override
    # @CONTEXT: Alinea path reportado por bundle y path real grabado
    # @SECURITY: Sin ejecucion de ROS2 ni escritura de bags en test
    text = RECORDER_SCRIPT.read_text(encoding="utf-8")

    assert "HIL_BAG_PATH" in text
    assert '--output "${BAG_PATH}"' in text
