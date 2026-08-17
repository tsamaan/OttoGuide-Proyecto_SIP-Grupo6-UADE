// SKELETON — no compilado, no ejecutado en IA-CXX-R2.
// @TASK: Declarar el contrato JSONL del shim, en espejo 1:1 con
//        codigo ottoguide/src/interaction/runtime_port.py (Python, autoritativo).
// @CONTEXT: docs/Arquitectura/IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md, secciones 5-8.
// @SECURITY: Este header no incluye whisper.h, unitree/*, ni realiza I/O, syscalls,
//            ni spawns de proceso. Es declarativo unicamente.
//
// No integrado a CMakeLists.txt en R2. No usar fuera de revision de diseño.

#pragma once

#include <cstdint>
#include <optional>
#include <string>

namespace otto::jsonl {

// Debe coincidir exactamente con INTERACTION_PROTOCOL_VERSION en runtime_port.py.
inline constexpr int kProtocolVersion = 1;

// Limites de payload — espejo de runtime_port.py (MAX_* constants).
inline constexpr std::size_t kMaxIdentifierLength = 80;
inline constexpr std::size_t kMaxPayloadDepth = 8;
inline constexpr std::size_t kMaxPayloadStringLength = 4096;
inline constexpr std::size_t kMaxPayloadContainerItems = 256;
inline constexpr std::size_t kMaxPayloadSerializedBytes = 32768;

// --- Comandos (WorkerCommandType en runtime_port.py:102-110) ----------------
// Comandos de proceso: interaction_id debe ser nullopt.
// Comandos de interaccion: interaction_id es obligatorio.
enum class CommandType {
    kStart,          // proceso
    kHealth,         // proceso
    kActivate,       // interaccion
    kPause,          // interaccion
    kResume,         // interaccion
    kStop,           // interaccion
    kEmergencyStop,  // proceso
    kClose,          // proceso
};

// TODO(R2B+): validar que estos strings coincidan byte a byte con
// WorkerCommandType.value en runtime_port.py antes de cualquier build futuro.
constexpr const char* CommandTypeToWire(CommandType type) {
    switch (type) {
        case CommandType::kStart: return "start";
        case CommandType::kHealth: return "health";
        case CommandType::kActivate: return "activate";
        case CommandType::kPause: return "pause";
        case CommandType::kResume: return "resume";
        case CommandType::kStop: return "stop";
        case CommandType::kEmergencyStop: return "emergency_stop";
        case CommandType::kClose: return "close";
    }
    return "";
}

// true si el comando es de clase "proceso" (interaction_id debe ser nullopt).
constexpr bool IsProcessCommand(CommandType type) {
    switch (type) {
        case CommandType::kStart:
        case CommandType::kHealth:
        case CommandType::kEmergencyStop:
        case CommandType::kClose:
            return true;
        default:
            return false;
    }
}

// --- Eventos (WorkerEventType en runtime_port.py:113-127) -------------------
enum class EventType {
    kReady,                 // proceso
    kHeartbeat,              // proceso
    kCommandAccepted,        // flexible (requiere payload.command + payload.message_id)
    kWakeWordConfirmed,      // proceso
    kCaptureStarted,         // interaccion
    kTranscriptReady,        // interaccion
    kResponseReady,          // interaccion
    kPlaybackStarted,        // interaccion
    kPlaybackCompleted,      // interaccion
    kInteractionTimeout,     // interaccion
    kCancelled,              // interaccion
    kFailed,                 // flexible (requiere payload.code + payload.message)
    kStopped,                // proceso
    kClosed,                 // proceso
};

// TODO(R2B+): validar que estos strings coincidan byte a byte con
// WorkerEventType.value en runtime_port.py antes de cualquier build futuro.
constexpr const char* EventTypeToWire(EventType type) {
    switch (type) {
        case EventType::kReady: return "ready";
        case EventType::kHeartbeat: return "heartbeat";
        case EventType::kCommandAccepted: return "command_accepted";
        case EventType::kWakeWordConfirmed: return "wake_word_confirmed";
        case EventType::kCaptureStarted: return "capture_started";
        case EventType::kTranscriptReady: return "transcript_ready";
        case EventType::kResponseReady: return "response_ready";
        case EventType::kPlaybackStarted: return "playback_started";
        case EventType::kPlaybackCompleted: return "playback_completed";
        case EventType::kInteractionTimeout: return "interaction_timeout";
        case EventType::kCancelled: return "cancelled";
        case EventType::kFailed: return "failed";
        case EventType::kStopped: return "stopped";
        case EventType::kClosed: return "closed";
    }
    return "";
}

// --- Envelope declarativo (WorkerCommandEnvelope / WorkerEventEnvelope) -----
// NOTA: esto es un schema documental, no una implementacion de (de)serializacion.
// La serializacion JSON real queda fuera de alcance de R2 (ver TODOs en
// otto_jsonl_shim.cpp).
struct CommandEnvelopeSchema {
    int protocol_version;                   // debe ser kProtocolVersion
    std::string message_id;                 // identificador ASCII, ver kMaxIdentifierLength
    std::optional<std::string> interaction_id;
    CommandType command;
    std::int64_t sequence;                  // no negativo
    double emitted_at_monotonic_s;          // finito, no negativo
    // payload: TODO(R2B+) — representar como mapa JSON-safe acotado por
    // kMaxPayloadDepth / kMaxPayloadContainerItems / kMaxPayloadSerializedBytes.
};

struct EventEnvelopeSchema {
    int protocol_version;                   // debe ser kProtocolVersion
    std::string message_id;
    std::optional<std::string> interaction_id;
    EventType event;
    std::int64_t sequence;                  // monotono creciente, generado por el shim
    double emitted_at_monotonic_s;
    // payload: TODO(R2B+) — ver CommandEnvelopeSchema.
};

}  // namespace otto::jsonl
