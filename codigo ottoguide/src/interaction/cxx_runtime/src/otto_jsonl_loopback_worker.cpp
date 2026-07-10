// otto_jsonl_loopback_worker.cpp
//
// Protocol-compliant C++ loopback worker for IA-CXX-R8. Reads WorkerCommandEnvelope JSONL
// frames from stdin and emits WorkerEventEnvelope JSONL frames to stdout, matching the wire
// contract declared in codigo ottoguide/src/interaction/runtime_port.py exactly.
//
// This is a test double (offline, simulated responses), analogous in purpose to
// codigo ottoguide/tests/support/u3a_loopback_worker.py. It does not perform real audio
// capture, STT, LLM inference, or TTS playback, and does not touch otto_pipeline.cpp, the
// Unitree SDK, or any network/audio hardware. stdout carries protocol JSONL only; stderr
// carries non-protocol logs only.

#include <chrono>
#include <cstdio>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <thread>

#include "otto_jsonl_protocol.hpp"

namespace {

using otto::jsonl::CommandType;
using otto::jsonl::CommandTypeToWire;
using otto::jsonl::EventType;
using otto::jsonl::EventTypeToWire;
using otto::jsonl::kProtocolVersion;

double MonotonicSeconds() {
    static const auto start = std::chrono::steady_clock::now();
    const auto now = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(now - start).count();
}

// Minimal JSON string escaper sufficient for the ASCII-only identifiers and short
// human-readable text this worker emits (message ids, locale text, fixed status strings).
std::string JsonEscape(const std::string& value) {
    std::string out;
    out.reserve(value.size() + 2);
    for (char c : value) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else {
                    out += c;
                }
        }
    }
    return out;
}

// Minimal, allocation-light extractor for a single top-level string field from a flat JSON
// object produced by runtime_port.py's WorkerCommandEnvelope.to_wire_dict(). Not a general
// JSON parser: it only needs to survive the exact shapes the Python supervisor writes.
std::optional<std::string> ExtractStringField(const std::string& line, const std::string& key) {
    const std::string needle = "\"" + key + "\"";
    auto pos = line.find(needle);
    if (pos == std::string::npos) return std::nullopt;
    pos = line.find(':', pos + needle.size());
    if (pos == std::string::npos) return std::nullopt;
    ++pos;
    while (pos < line.size() && (line[pos] == ' ' || line[pos] == '\t')) ++pos;
    if (pos >= line.size()) return std::nullopt;
    if (line[pos] == 'n' && line.compare(pos, 4, "null") == 0) return std::nullopt;
    if (line[pos] != '"') return std::nullopt;
    ++pos;
    std::string value;
    while (pos < line.size() && line[pos] != '"') {
        if (line[pos] == '\\' && pos + 1 < line.size()) {
            char next = line[pos + 1];
            switch (next) {
                case 'n': value += '\n'; break;
                case 'r': value += '\r'; break;
                case 't': value += '\t'; break;
                case '"': value += '"'; break;
                case '\\': value += '\\'; break;
                default: value += next;
            }
            pos += 2;
        } else {
            value += line[pos];
            ++pos;
        }
    }
    return value;
}

std::optional<CommandType> ParseCommand(const std::string& wire) {
    if (wire == "start") return CommandType::kStart;
    if (wire == "health") return CommandType::kHealth;
    if (wire == "activate") return CommandType::kActivate;
    if (wire == "pause") return CommandType::kPause;
    if (wire == "resume") return CommandType::kResume;
    if (wire == "stop") return CommandType::kStop;
    if (wire == "emergency_stop") return CommandType::kEmergencyStop;
    if (wire == "close") return CommandType::kClose;
    return std::nullopt;
}

class LoopbackWorker {
public:
    void EmitReady(const std::string& sourceMessageId) {
        (void)sourceMessageId;
        static const char* kCapabilityKeys[] = {
            "audio_capture", "wake_word", "vad", "stt", "local_llm",
            "spanish_tts", "physical_playback", "physical_playback_stop",
            "physical_playback_completion",
        };
        std::ostringstream payload;
        payload << "{";
        for (std::size_t i = 0; i < std::size(kCapabilityKeys); ++i) {
            if (i > 0) payload << ",";
            payload << "\"" << kCapabilityKeys[i] << "\":false";
        }
        payload << "}";
        Emit(EventType::kReady, std::nullopt, payload.str());
    }

    void EmitHeartbeat() { Emit(EventType::kHeartbeat, std::nullopt, "{}"); }

    void EmitCommandAccepted(CommandType command, const std::string& messageId,
                              const std::optional<std::string>& interactionId) {
        std::ostringstream payload;
        payload << "{\"command\":\"" << CommandTypeToWire(command)
                 << "\",\"message_id\":\"" << JsonEscape(messageId) << "\"}";
        Emit(EventType::kCommandAccepted, interactionId, payload.str());
    }

    void EmitCaptureStarted(const std::string& interactionId) {
        Emit(EventType::kCaptureStarted, interactionId, "{}");
    }

    void EmitTranscriptReady(const std::string& interactionId) {
        Emit(EventType::kTranscriptReady, interactionId, "{\"text\":\"hola\"}");
    }

    void EmitResponseReady(const std::string& interactionId) {
        Emit(EventType::kResponseReady, interactionId, "{\"text\":\"respuesta\"}");
    }

    void EmitPlaybackStarted(const std::string& interactionId) {
        Emit(EventType::kPlaybackStarted, interactionId, "{}");
    }

    void EmitPlaybackCompleted(const std::string& interactionId) {
        Emit(EventType::kPlaybackCompleted, interactionId, "{\"duration_s\":0.01}");
    }

    void EmitCancelled(const std::optional<std::string>& interactionId) {
        Emit(EventType::kCancelled, interactionId, "{}");
    }

    void EmitStopped() { Emit(EventType::kStopped, std::nullopt, "{}"); }

    void EmitClosed() { Emit(EventType::kClosed, std::nullopt, "{}"); }

    void EmitFailed(const std::string& code, const std::string& message) {
        std::ostringstream payload;
        payload << "{\"code\":\"" << JsonEscape(code) << "\",\"message\":\""
                 << JsonEscape(message) << "\"}";
        Emit(EventType::kFailed, std::nullopt, payload.str());
    }

    // Returns false once the worker should exit (after stopped/closed emitted).
    bool HandleLine(const std::string& line) {
        auto commandWire = ExtractStringField(line, "command");
        auto messageId = ExtractStringField(line, "message_id");
        auto interactionId = ExtractStringField(line, "interaction_id");
        if (!commandWire || !messageId) {
            EmitFailed("ERR_TYPE", "malformed command envelope");
            return true;
        }
        auto command = ParseCommand(*commandWire);
        if (!command) {
            EmitFailed("ERR_TYPE", "unknown command");
            return true;
        }
        switch (*command) {
            case CommandType::kStart:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                EmitReady(*messageId);
                return true;
            case CommandType::kHealth:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                return true;
            case CommandType::kActivate: {
                if (!interactionId) {
                    EmitFailed("ERR_IDENTIFIER", "activate requires interaction_id");
                    return true;
                }
                EmitCommandAccepted(*command, *messageId, interactionId);
                EmitCaptureStarted(*interactionId);
                EmitTranscriptReady(*interactionId);
                EmitResponseReady(*interactionId);
                EmitPlaybackStarted(*interactionId);
                EmitPlaybackCompleted(*interactionId);
                return true;
            }
            case CommandType::kPause:
            case CommandType::kResume:
                EmitCommandAccepted(*command, *messageId, interactionId);
                return true;
            case CommandType::kStop:
                EmitCommandAccepted(*command, *messageId, interactionId);
                EmitCancelled(interactionId);
                EmitStopped();
                return true;
            case CommandType::kEmergencyStop:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                EmitStopped();
                return false;
            case CommandType::kClose:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                EmitClosed();
                return false;
        }
        return true;
    }

private:
    void Emit(EventType event, const std::optional<std::string>& interactionId,
              const std::string& payloadJson) {
        std::ostringstream frame;
        frame << "{\"protocol_version\":" << kProtocolVersion
              << ",\"message_id\":\"worker:" << sequence_ << "\""
              << ",\"interaction_id\":"
              << (interactionId ? ("\"" + JsonEscape(*interactionId) + "\"") : "null")
              << ",\"event\":\"" << EventTypeToWire(event) << "\""
              << ",\"sequence\":" << sequence_
              << ",\"emitted_at_monotonic_s\":" << MonotonicSeconds()
              << ",\"payload\":" << payloadJson
              << "}";
        std::cout << frame.str() << "\n";
        std::cout.flush();
        ++sequence_;
    }

    long long sequence_ = 0;
};

}  // namespace

int main() {
    LoopbackWorker worker;
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        const bool keepRunning = worker.HandleLine(line);
        if (!keepRunning) {
            return 0;
        }
    }
    return 0;
}
