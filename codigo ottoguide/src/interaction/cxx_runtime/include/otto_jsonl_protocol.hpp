// otto_jsonl_protocol.hpp
//
// Productive (compilable) recreation of the JSONL wire protocol contract
// declared in codigo ottoguide/src/interaction/runtime_port.py (Python,
// authoritative). This header is a mirror of the R2 design skeleton at
// docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/otto_jsonl_protocol.hpp,
// recreated (not moved) under codigo ottoguide/ per IA-CXX-R4's placement
// decision.
//
// C++17. No external dependencies. No Unitree SDK. No Whisper/Ollama/Piper.
// No file I/O, no sockets, no process creation, no stdin/stdout access.
// Purely declarative: enums, wire-string mapping, and payload-limit
// constants that mirror runtime_port.py's MAX_* constants.

#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <string_view>

namespace otto::jsonl {

// Must match INTERACTION_PROTOCOL_VERSION in runtime_port.py exactly.
inline constexpr int kProtocolVersion = 1;

// Payload/identifier limits — mirror of runtime_port.py's MAX_* constants.
inline constexpr std::size_t kMaxIdentifierLength = 80;
inline constexpr std::size_t kMaxPayloadDepth = 8;
inline constexpr std::size_t kMaxPayloadStringLength = 4096;
inline constexpr std::size_t kMaxPayloadContainerItems = 256;
inline constexpr std::size_t kMaxPayloadSerializedBytes = 32768;

// --- Commands (WorkerCommandType in runtime_port.py:102-110) ---------------
// Process commands: interaction_id must be nullopt.
// Interaction commands: interaction_id is required.
enum class CommandType {
    kStart,          // process
    kHealth,         // process
    kActivate,       // interaction
    kPause,          // interaction
    kResume,         // interaction
    kStop,           // interaction
    kEmergencyStop,  // process
    kClose,          // process
};

// Wire strings verified byte-for-byte against WorkerCommandType.value in
// runtime_port.py (see IA_CXX_R5_PROTOCOL_PARITY.txt for the verification
// evidence produced alongside this file).
constexpr std::string_view CommandTypeToWire(CommandType type) {
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

// true if the command is a "process" command (interaction_id must be nullopt).
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

// --- Events (WorkerEventType in runtime_port.py:113-127) -------------------
enum class EventType {
    kReady,               // process
    kHeartbeat,           // process
    kCommandAccepted,     // flexible (requires payload.command + payload.message_id)
    kWakeWordConfirmed,   // process
    kCaptureStarted,      // interaction
    kTranscriptReady,     // interaction
    kResponseReady,       // interaction
    kPlaybackStarted,     // interaction
    kPlaybackCompleted,   // interaction
    kInteractionTimeout,  // interaction
    kCancelled,           // interaction
    kFailed,              // flexible (requires payload.code + payload.message)
    kStopped,             // process
    kClosed,              // process
};

// Wire strings verified byte-for-byte against WorkerEventType.value in
// runtime_port.py (see IA_CXX_R5_PROTOCOL_PARITY.txt).
constexpr std::string_view EventTypeToWire(EventType type) {
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

// true if the event is a "process" event (interaction_id must be nullopt).
constexpr bool IsProcessEvent(EventType type) {
    switch (type) {
        case EventType::kReady:
        case EventType::kHeartbeat:
        case EventType::kWakeWordConfirmed:
        case EventType::kStopped:
        case EventType::kClosed:
            return true;
        default:
            return false;
    }
}

// --- Envelope declarative schema (WorkerCommandEnvelope / WorkerEventEnvelope) ---
// NOTE: this is a declarative schema, not a JSON (de)serialization
// implementation. Real JSON parsing/writing is out of scope for R5 — it
// belongs to a future checkpoint that also defines the stdin/stdout
// dispatch loop, per README.md in this directory.
struct CommandEnvelopeSchema {
    int protocol_version;                    // must equal kProtocolVersion
    std::string message_id;                  // ASCII identifier, see kMaxIdentifierLength
    std::optional<std::string> interaction_id;
    CommandType command;
    std::int64_t sequence;                   // non-negative
    double emitted_at_monotonic_s;           // finite, non-negative
    // payload intentionally omitted: future checkpoint, JSON-safe bounded map.
};

struct EventEnvelopeSchema {
    int protocol_version;                    // must equal kProtocolVersion
    std::string message_id;
    std::optional<std::string> interaction_id;
    EventType event;
    std::int64_t sequence;                   // monotonically increasing, shim-generated
    double emitted_at_monotonic_s;
    // payload intentionally omitted: see CommandEnvelopeSchema.
};

}  // namespace otto::jsonl
