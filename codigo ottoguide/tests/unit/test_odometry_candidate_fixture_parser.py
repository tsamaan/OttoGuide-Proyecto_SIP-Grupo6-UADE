"""
@TASK: Verificar que las fixtures reales de MFR-R6 (SportModeState_) se cargan
       correctamente para los tests del adapter de odometria candidata
@INPUT: tests/fixtures/mfr_r6_sportmodestate/*.jsonl (datos reales capturados
        del robot en MFR-R6, no sinteticos)
@OUTPUT: Aserciones sobre conteo y forma de las fixtures cargadas
@CONTEXT: Adaptado de ODOM-R1 (run local, no repo) para el layout de tests/
          de este repositorio. No cambia el comportamiento validado en ODOM-R1.
@SECURITY: Solo lectura de archivos locales del repo; sin red, sin ROS, sin DDS.
"""
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "mfr_r6_sportmodestate"


def load_jsonl(path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TestFixtureParser:
    def setup_method(self):
        self.all_samples = load_jsonl(FIXTURES_DIR / "mfr_r6_sportmodestate_samples.jsonl")
        self.primary = load_jsonl(FIXTURES_DIR / "mfr_r6_primary_rt_odommodestate.jsonl")
        self.secondary = load_jsonl(FIXTURES_DIR / "mfr_r6_secondary_rt_lf_odommodestate.jsonl")
        with (FIXTURES_DIR / "mfr_r6_fixture_summary.json").open(encoding="utf-8") as f:
            self.summary = json.load(f)

    def test_parser_extracts_160_real_samples(self):
        assert len(self.all_samples) == 160
        assert self.summary["total_samples"] == 160

    def test_parser_extracts_80_primary_samples(self):
        assert len(self.primary) == 80
        assert all(s["channel"] == "rt/odommodestate" for s in self.primary)

    def test_parser_extracts_80_secondary_samples(self):
        assert len(self.secondary) == 80
        assert all(s["channel"] == "rt/lf/odommodestate" for s in self.secondary)

    def test_all_samples_have_stamp_zero(self):
        assert all(s["stamp_sec"] == 0 and s["stamp_nanosec"] == 0 for s in self.all_samples)
        assert self.summary["stamp_all_zero"] is True

    def test_no_prefix_channels_absent(self):
        assert self.summary["no_prefix_odommodestate_count"] == 0
        assert self.summary["no_prefix_lf_odommodestate_count"] == 0
