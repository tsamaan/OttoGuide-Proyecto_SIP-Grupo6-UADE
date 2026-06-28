"""
@TASK: Validar el filtro de estabilidad QR y el decoder OpenCV (U2)
@INPUT: Decoder fake; sin camara real
@OUTPUT: Resultado de pytest: PASSED si el filtro cumple su especificacion
@CONTEXT: Ejecutar con: python -m pytest tests/unit/test_u2_qr_frame_detector.py -q
"""
from __future__ import annotations

import ast
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.vision.qr_frame_detector import (
    OpenCVQRCodeDecoder,
    QRFrameDecoder,
    StableQRFrameDetector,
    StableQRValue,
)


class FakeDecoder:
    def __init__(self, values: list[str | None]) -> None:
        self._values = list(values)

    def decode(self, frame: object) -> str | None:
        if not self._values:
            return None
        return self._values.pop(0)


def test_fake_decoder_satisfies_protocol() -> None:
    assert isinstance(FakeDecoder([]), QRFrameDecoder)


def test_four_equal_values_emit_once() -> None:
    decoder = FakeDecoder(["A", "A", "A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    results = [detector.process_frame(None) for _ in range(4)]
    assert results[:3] == [None, None, None]
    assert isinstance(results[3], StableQRValue)
    assert results[3].value == "A"


def test_values_before_threshold_do_not_emit() -> None:
    decoder = FakeDecoder(["A", "A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    results = [detector.process_frame(None) for _ in range(3)]
    assert all(r is None for r in results)


def test_continuous_presence_does_not_repeat() -> None:
    decoder = FakeDecoder(["A", "A", "A", "A", "A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    results = [detector.process_frame(None) for _ in range(6)]
    emissions = [r for r in results if r is not None]
    assert len(emissions) == 1
    assert emissions[0].value == "A"


def test_three_absences_rearm() -> None:
    decoder = FakeDecoder(["A", "A", "A", "A", None, None, None, "A", "A", "A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    results = [detector.process_frame(None) for _ in range(11)]
    emissions = [r for r in results if r is not None]
    assert len(emissions) == 2
    assert all(e.value == "A" for e in emissions)


def test_different_value_resets_count() -> None:
    decoder = FakeDecoder(["A", "A", "B", "B", "B", "B"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    results = [detector.process_frame(None) for _ in range(6)]
    emissions = [r for r in results if r is not None]
    assert len(emissions) == 1
    assert emissions[0].value == "B"


def test_whitespace_is_normalized() -> None:
    decoder = FakeDecoder(["  A  ", "A", "A ", " A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    results = [detector.process_frame(None) for _ in range(4)]
    assert results[3].value == "A"


def test_empty_value_counts_as_absence() -> None:
    decoder = FakeDecoder(["A", "A", "A", "A", "", "", "", "A", "A", "A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)

    results = [detector.process_frame(None) for _ in range(11)]
    emissions = [r for r in results if r is not None]
    assert len(emissions) == 2


def test_invalid_stable_frames_rejected() -> None:
    with pytest.raises(ValueError):
        StableQRFrameDetector(FakeDecoder([]), stable_frames=0, release_frames=3)
    with pytest.raises(ValueError):
        StableQRFrameDetector(FakeDecoder([]), stable_frames=-1, release_frames=3)


def test_invalid_release_frames_rejected() -> None:
    with pytest.raises(ValueError):
        StableQRFrameDetector(FakeDecoder([]), stable_frames=4, release_frames=0)
    with pytest.raises(ValueError):
        StableQRFrameDetector(FakeDecoder([]), stable_frames=4, release_frames=-1)


def test_reset_restores_state() -> None:
    decoder = FakeDecoder(["A", "A", "A", "A", "A", "A", "A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    for _ in range(4):
        detector.process_frame(None)

    detector.reset()

    results = [detector.process_frame(None) for _ in range(4)]
    assert results[3] is not None
    assert results[3].value == "A"


def test_confidence_is_exactly_one_on_confirmed_emission() -> None:
    decoder = FakeDecoder(["A", "A", "A", "A"])
    detector = StableQRFrameDetector(decoder, stable_frames=4, release_frames=3)
    results = [detector.process_frame(None) for _ in range(4)]
    assert results[3].confidence_or_stability == 1.0


def test_opencv_decoder_does_not_open_video_capture() -> None:
    decoder = OpenCVQRCodeDecoder()
    assert decoder._cv2_detector is None


def test_no_qr_module_contains_videocapture_call() -> None:
    qr_modules = [
        os.path.join(_PROJECT_ROOT, "src", "vision", "qr_frame_detector.py"),
    ]
    for path in qr_modules:
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "VideoCapture":
                pytest.fail(f"{path} contains a VideoCapture reference")
