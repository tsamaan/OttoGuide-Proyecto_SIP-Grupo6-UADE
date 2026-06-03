from __future__ import annotations

# @TASK: Tests unitarios para el contrato de contenido del tour (TourScript, ConversationManager)
# @INPUT: TourScript/WaypointContent desde api.schemas; ConversationManager desde src.interaction
# @OUTPUT: Verificacion de validacion Pydantic, carga de script y comportamiento de zona
# @CONTEXT: Ejecutable sin hardware fisico ni unitree_sdk2py ni Ollama
# @SECURITY: Sin I/O de red; mocks de estrategias NLP para aislar ConversationManager

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from api.schemas import TourScript, WaypointContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VALID_SCRIPT_DATA = {
    "version": "1.0.0",
    "waypoints": [
        {
            "waypoint_id": "entrada",
            "interaction_type": "llm_qa",
            "system_prompt": "Eres OttoGuide en la entrada.",
            "pose_2d": {"x": 0.0, "y": 0.0, "theta": 0.0},
        },
        {
            "waypoint_id": "planta_baja",
            "interaction_type": "llm_qa",
            "system_prompt": "Eres OttoGuide en la planta baja.",
            "pose_2d": {"x": 1.0, "y": 0.0, "theta": 0.0},
        },
        {
            "waypoint_id": "patio",
            "interaction_type": "llm_qa",
            "system_prompt": "Eres OttoGuide en el patio.",
            "pose_2d": {"x": 2.0, "y": 0.0, "theta": 0.0},
        },
    ],
}


@pytest.fixture
def valid_script_file(tmp_path: Path) -> Path:
    """
    @TASK: Crear archivo JSON valido del guion en directorio temporal
    @INPUT: tmp_path fixture de pytest
    @OUTPUT: Path al archivo JSON temporal
    @CONTEXT: Usado por tests de load_script_from_file()
    @SECURITY: Sin escritura fuera del directorio temporal
    """
    script_file = tmp_path / "tour_script.json"
    script_file.write_text(json.dumps(VALID_SCRIPT_DATA), encoding="utf-8")
    return script_file


@pytest.fixture
def conversation_manager():
    """
    @TASK: Construir ConversationManager con estrategias NLP completamente mockeadas
    @INPUT: Sin parametros
    @OUTPUT: ConversationManager con LocalNLPPipeline y CloudNLPPipeline mockeados
    @CONTEXT: Aislamiento completo; sin Ollama, sin sounddevice, sin httpx real
    @SECURITY: Sin I/O de red ni de audio
    """
    from src.interaction.conversation_manager import ConversationManager

    local_mock = MagicMock()
    local_mock.generate = AsyncMock()
    local_mock.close = MagicMock()

    cloud_mock = MagicMock()
    cloud_mock.generate = AsyncMock()
    cloud_mock.close = MagicMock()

    return ConversationManager(
        local_strategy=local_mock,
        cloud_strategy=cloud_mock,
    )


# ---------------------------------------------------------------------------
# TAREA 5.1 — Validacion de TourScript con Pydantic
# ---------------------------------------------------------------------------

class TestTourScriptValidation:
    """Verificar que TourScript rechaza JSON malformado."""

    def test_valid_script_parses_correctly(self) -> None:
        """
        @TASK: Verificar que un JSON bien formado produce un TourScript valido
        @INPUT: VALID_SCRIPT_DATA
        @OUTPUT: TourScript con 3 waypoints
        @SECURITY: Sin I/O de red
        """
        script = TourScript.model_validate(VALID_SCRIPT_DATA)
        assert script.version == "1.0.0"
        assert len(script.waypoints) == 3
        assert script.waypoints[0].waypoint_id == "entrada"

    def test_missing_version_raises_validation_error(self) -> None:
        """
        @TASK: Verificar que falta de 'version' causa ValidationError
        @INPUT: JSON sin campo version
        @OUTPUT: pydantic.ValidationError
        """
        data = {k: v for k, v in VALID_SCRIPT_DATA.items() if k != "version"}
        with pytest.raises(ValidationError):
            TourScript.model_validate(data)

    def test_empty_waypoints_raises_validation_error(self) -> None:
        """
        @TASK: Verificar que waypoints=[] causa ValidationError (min_length=1)
        @INPUT: JSON con waypoints vacio
        @OUTPUT: pydantic.ValidationError
        """
        data = {**VALID_SCRIPT_DATA, "waypoints": []}
        with pytest.raises(ValidationError):
            TourScript.model_validate(data)

    def test_waypoint_missing_waypoint_id_raises_validation_error(self) -> None:
        """
        @TASK: Verificar que WaypointContent sin waypoint_id causa ValidationError
        @INPUT: Waypoint sin campo waypoint_id
        @OUTPUT: pydantic.ValidationError
        """
        bad_waypoint = {
            "interaction_type": "llm_qa",
            "system_prompt": "Sin zona id.",
            "pose_2d": {"x": 0.0, "y": 0.0, "theta": 0.0},
        }
        with pytest.raises(ValidationError):
            WaypointContent.model_validate(bad_waypoint)

    def test_waypoint_missing_interaction_type_raises_validation_error(self) -> None:
        """
        @TASK: Verificar que WaypointContent sin interaction_type causa ValidationError
        @INPUT: Waypoint sin campo interaction_type
        @OUTPUT: pydantic.ValidationError
        """
        bad_waypoint = {
            "waypoint_id": "entrada",
            "system_prompt": "Prompt de prueba.",
            "pose_2d": {"x": 0.0, "y": 0.0, "theta": 0.0},
        }
        with pytest.raises(ValidationError):
            WaypointContent.model_validate(bad_waypoint)

    def test_extra_fields_ignored(self) -> None:
        """
        @TASK: Verificar que campos extra en WaypointContent son ignorados (extra=ignore)
        @INPUT: WaypointContent con campo desconocido 'nota_equipo_contenido'
        @OUTPUT: WaypointContent valido sin error
        """
        data = {
            "waypoint_id": "entrada",
            "interaction_type": "llm_qa",
            "system_prompt": "Prompt de prueba.",
            "pose_2d": {"x": 0.0, "y": 0.0, "theta": 0.0},
            "nota_equipo_contenido": "Revisar en marzo",
        }
        waypoint = WaypointContent.model_validate(data)
        assert waypoint.waypoint_id == "entrada"
        assert not hasattr(waypoint, "nota_equipo_contenido")

    def test_mvp_script_file_is_valid(self) -> None:
        """
        @TASK: Verificar que data/mvp_tour_script.json es un TourScript valido
        @INPUT: Archivo de plantilla del MVP
        @OUTPUT: TourScript con los 5 waypoints UADE (I, 1, 2, 3, F)
        @CONTEXT: Garantia de que la plantilla del equipo de contenido es correcta
        """
        script_path = Path(__file__).resolve().parents[2] / "data" / "mvp_tour_script.json"
        raw = script_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        script = TourScript.model_validate(data)
        waypoint_ids = [w.waypoint_id for w in script.waypoints]
        assert waypoint_ids == ["I", "1", "2", "3", "F"]


# ---------------------------------------------------------------------------
# TAREA 5.2 — load_script_from_file asigna estado correctamente
# ---------------------------------------------------------------------------

class TestLoadScriptFromFile:
    """Verificar que load_script_from_file asigna estado interno correctamente."""

    def test_load_assigns_script_and_first_zone(
        self, conversation_manager, valid_script_file: Path
    ) -> None:
        """
        @TASK: Verificar que load_script_from_file popula _script y activa la primera zona
        @INPUT: archivo JSON valido con 3 zonas
        @OUTPUT: loaded_script != None; current_zone == "entrada"
        """
        assert conversation_manager.loaded_script is None
        assert conversation_manager.current_zone == ""

        conversation_manager.load_script_from_file(valid_script_file)

        assert conversation_manager.loaded_script is not None
        assert conversation_manager.loaded_script.version == "1.0.0"
        assert conversation_manager.current_zone == "entrada"

    def test_load_invalid_json_raises_error(
        self, conversation_manager, tmp_path: Path
    ) -> None:
        """
        @TASK: Verificar que JSON malformado propaga excepcion al caller
        @INPUT: archivo con JSON invalido
        @OUTPUT: json.JSONDecodeError o ValidationError
        """
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid json", encoding="utf-8")

        with pytest.raises(Exception):
            conversation_manager.load_script_from_file(bad_file)

    def test_load_missing_file_raises_file_not_found(
        self, conversation_manager
    ) -> None:
        """
        @TASK: Verificar que archivo inexistente propaga FileNotFoundError
        @INPUT: path a archivo que no existe
        @OUTPUT: FileNotFoundError
        """
        with pytest.raises(FileNotFoundError):
            conversation_manager.load_script_from_file(Path("/no/existo.json"))

    def test_reload_preserves_active_zone_if_still_valid(
        self, conversation_manager, valid_script_file: Path, tmp_path: Path
    ) -> None:
        """
        @TASK: Verificar que recargar preserva la zona activa si sigue en el nuevo guion
        @INPUT: Script v1.0.0 cargado con zona "planta_baja" activa; recargar mismo script
        @OUTPUT: zona activa mantiene "planta_baja"
        """
        conversation_manager.load_script_from_file(valid_script_file)
        conversation_manager.set_active_zone("planta_baja")
        assert conversation_manager.current_zone == "planta_baja"

        conversation_manager.load_script_from_file(valid_script_file)
        assert conversation_manager.current_zone == "planta_baja"


# ---------------------------------------------------------------------------
# TAREA 5.3 — set_active_zone actualiza prompt interno correctamente
# ---------------------------------------------------------------------------

class TestSetActiveZone:
    """Verificar que set_active_zone actualiza el system_prompt en cache."""

    def test_set_valid_zone_updates_prompt(
        self, conversation_manager, valid_script_file: Path
    ) -> None:
        """
        @TASK: Verificar que cambiar de zona actualiza _current_zone_prompt
        @INPUT: Script cargado; llamar set_active_zone("planta_baja")
        @OUTPUT: _build_zoned_text incluye system_prompt de planta_baja
        """
        conversation_manager.load_script_from_file(valid_script_file)
        conversation_manager.set_active_zone("planta_baja")

        assert conversation_manager.current_zone == "planta_baja"
        zoned = conversation_manager._build_zoned_text("Donde esta la biblioteca?")
        assert "planta baja" in zoned.lower()

    def test_set_invalid_zone_raises_value_error(
        self, conversation_manager, valid_script_file: Path
    ) -> None:
        """
        @TASK: Verificar que zone_id inexistente lanza ValueError con lista de zonas validas
        @INPUT: zone_id="zona_inexistente"
        @OUTPUT: ValueError con mensaje descriptivo
        """
        conversation_manager.load_script_from_file(valid_script_file)
        with pytest.raises(ValueError, match="zona_inexistente"):
            conversation_manager.set_active_zone("zona_inexistente")

    def test_set_zone_without_script_logs_warning_no_raise(
        self, conversation_manager
    ) -> None:
        """
        @TASK: Verificar que set_active_zone sin script cargado no lanza excepcion
        @INPUT: ConversationManager sin script; llamar set_active_zone
        @OUTPUT: Sin excepcion; zone permanece ""
        """
        conversation_manager.set_active_zone("entrada")
        assert conversation_manager.current_zone == ""

    def test_zone_switch_changes_prompt_in_zoned_text(
        self, conversation_manager, valid_script_file: Path
    ) -> None:
        """
        @TASK: Verificar que el texto construido cambia al cambiar de zona
        @INPUT: Zona inicial "entrada" -> zona nueva "patio"
        @OUTPUT: _build_zoned_text retorna prompt de patio tras el cambio
        """
        conversation_manager.load_script_from_file(valid_script_file)
        conversation_manager.set_active_zone("entrada")
        text_entrada = conversation_manager._build_zoned_text("Hola")
        assert "entrada" in text_entrada.lower()

        conversation_manager.set_active_zone("patio")
        text_patio = conversation_manager._build_zoned_text("Hola")
        assert "patio" in text_patio.lower()
        assert text_entrada != text_patio

    def test_no_script_build_zoned_text_returns_original(
        self, conversation_manager
    ) -> None:
        """
        @TASK: Verificar que _build_zoned_text sin script retorna texto sin modificar
        @INPUT: Sin script cargado; user_text="Hola"
        @OUTPUT: "Hola" sin prefijo
        """
        result = conversation_manager._build_zoned_text("Hola")
        assert result == "Hola"
