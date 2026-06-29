from __future__ import annotations

from importlib import import_module
from typing import Any

_SYMBOL_MODULE_MAP: dict[str, str] = {
    # Audio hardware bridge
    "AudioHardwareBridge": ".audio_bridge",
    # Conversation pipeline (Strategy pattern)
    "CloudNLPPipeline": ".conversation_manager",
    "ConversationManager": ".conversation_manager",
    "ConversationRequest": ".conversation_manager",
    "ConversationResponse": ".conversation_manager",
    "LocalNLPPipeline": ".conversation_manager",
    "NLPStrategy": ".conversation_manager",
    # LLM client
    "OllamaAsyncClient": ".llm_client",
    # Wake word detection (migrado de OttoGuide IA/)
    "WakeWordDetector": ".wake_word_detector",
    "clean_text_for_tts": ".wake_word_detector",
    "correct_uade_transcription": ".wake_word_detector",
    "load_uade_corrections": ".wake_word_detector",
    "WAKE_WORDS": ".wake_word_detector",
    "FAREWELL_WORDS": ".wake_word_detector",
    # STT adapter async (migrado de OttoGuide IA/)
    "WhisperSTTClient": ".stt_whisper_client",
    # TTS adapters — Strategy pattern (Piper + SDK Unitree)
    "TTSAdapter": ".tts_unitree_client",
    "PiperTTSAdapter": ".tts_unitree_client",
    "UnitreeTTSAdapter": ".tts_unitree_client",
    "tts_adapter_factory": ".tts_unitree_client",
    # Contrato canonico de runtime de interaccion real (U1)
    "INTERACTION_PROTOCOL_VERSION": ".runtime_port",
    "InteractionContext": ".runtime_port",
    "InteractionRuntimeCapabilities": ".runtime_port",
    "InteractionRuntimeError": ".runtime_port",
    "InteractionRuntimeHealth": ".runtime_port",
    "InteractionRuntimePort": ".runtime_port",
    "InteractionRuntimeProtocolError": ".runtime_port",
    "InteractionRuntimeState": ".runtime_port",
    "InteractionRuntimeUnavailableError": ".runtime_port",
    "WorkerCommandEnvelope": ".runtime_port",
    "WorkerCommandType": ".runtime_port",
    "WorkerEventEnvelope": ".runtime_port",
    "WorkerEventType": ".runtime_port",
    # Supervisor JSONL concreto (U3A, stdlib-only)
    "JsonlInteractionWorkerSupervisor": ".jsonl_worker_supervisor",
    "JsonlWorkerSupervisorConfig": ".jsonl_worker_supervisor",
    # Contrato canonico del supervisor del worker real (U1)
    "InteractionWorkerSupervisor": ".worker_supervisor",
    "WorkerTermination": ".worker_supervisor",
}


def __getattr__(name: str) -> Any:
    module_name = _SYMBOL_MODULE_MAP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))


__all__ = [
    # Audio hardware bridge
    "AudioHardwareBridge",
    # Conversation pipeline (Strategy pattern)
    "CloudNLPPipeline",
    "ConversationManager",
    "ConversationRequest",
    "ConversationResponse",
    "LocalNLPPipeline",
    "NLPStrategy",
    # LLM client
    "OllamaAsyncClient",
    # Wake word detection (migrado de OttoGuide IA/)
    "WakeWordDetector",
    "clean_text_for_tts",
    "correct_uade_transcription",
    "load_uade_corrections",
    "WAKE_WORDS",
    "FAREWELL_WORDS",
    # STT adapter async (migrado de OttoGuide IA/)
    "WhisperSTTClient",
    # TTS adapters — Strategy pattern (Piper + SDK Unitree)
    "TTSAdapter",
    "PiperTTSAdapter",
    "UnitreeTTSAdapter",
    "tts_adapter_factory",
    # Contrato canonico de runtime de interaccion real (U1)
    "INTERACTION_PROTOCOL_VERSION",
    "InteractionContext",
    "InteractionRuntimeCapabilities",
    "InteractionRuntimeError",
    "InteractionRuntimeHealth",
    "InteractionRuntimePort",
    "InteractionRuntimeProtocolError",
    "InteractionRuntimeState",
    "InteractionRuntimeUnavailableError",
    "WorkerCommandEnvelope",
    "WorkerCommandType",
    "WorkerEventEnvelope",
    "WorkerEventType",
    # Supervisor JSONL concreto (U3A, stdlib-only)
    "JsonlInteractionWorkerSupervisor",
    "JsonlWorkerSupervisorConfig",
    # Contrato canonico del supervisor del worker real (U1)
    "InteractionWorkerSupervisor",
    "WorkerTermination",
]
