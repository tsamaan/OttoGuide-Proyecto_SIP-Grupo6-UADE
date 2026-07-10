// otto_jsonl_shim.cpp
//
// IA-CXX-R11: first non-stub implementation of the productive C++ runtime skeleton under
// codigo ottoguide/src/interaction/cxx_runtime/. Reads WorkerCommandEnvelope JSONL frames from
// stdin and emits WorkerEventEnvelope JSONL frames to stdout, matching the wire contract
// declared in codigo ottoguide/src/interaction/runtime_port.py exactly.
//
// This is a mocked dispatch loop: it validates the framing/protocol path against
// deterministic, hardcoded responses. It does not perform real audio capture, STT, LLM
// inference, or TTS playback, and does not touch otto_pipeline.cpp, the Unitree SDK, or any
// network/audio hardware. stdout carries protocol JSONL only; stderr carries non-protocol logs
// only. Design reference: docs/Arquitectura/IA_CXX_R10_DETAILED_ADAPTER_DESIGN_OFFLINE_NO_CODE_NO_ROBOT.md.

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <iostream>
#include <mutex>
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
// JSON parser: it only needs to survive the exact shapes the Python supervisor (or the
// synthetic smoke-test input of this checkpoint) writes.
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

// Serializes and writes exactly one WorkerEventEnvelope-shaped JSONL line to stdout, guarded by
// a mutex because the heartbeat timer thread and the main dispatch loop both emit frames.
class FrameEmitter {
public:
    void Emit(EventType event, const std::optional<std::string>& interactionId,
              const std::string& payloadJson) {
        std::ostringstream frame;
        long long sequence;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            sequence = sequence_++;
        }
        frame << "{\"protocol_version\":" << kProtocolVersion
              << ",\"message_id\":\"shim:" << sequence << "\""
              << ",\"interaction_id\":"
              << (interactionId ? ("\"" + JsonEscape(*interactionId) + "\"") : "null")
              << ",\"event\":\"" << EventTypeToWire(event) << "\""
              << ",\"sequence\":" << sequence
              << ",\"emitted_at_monotonic_s\":" << MonotonicSeconds()
              << ",\"payload\":" << payloadJson
              << "}";
        std::lock_guard<std::mutex> lock(mutex_);
        std::cout << frame.str() << "\n";
        std::cout.flush();
    }

private:
    std::mutex mutex_;
    long long sequence_ = 0;
};

// Emits a heartbeat event on a fixed interval until stopped. Runs on its own thread so a
// long-running mocked interaction (or an idle READY period) still satisfies the supervisor's
// heartbeat_timeout_s (default 5.0s in jsonl_worker_supervisor.py). Joins cleanly on
// close/emergency_stop, never leaves a detached or dangling thread.
class HeartbeatTimer {
public:
    explicit HeartbeatTimer(FrameEmitter& emitter) : emitter_(emitter) {}

    void Start() {
        running_.store(true);
        thread_ = std::thread([this] { Run(); });
    }

    void Stop() {
        {
            std::lock_guard<std::mutex> lock(mutex_);
            running_.store(false);
        }
        cv_.notify_all();
        if (thread_.joinable()) thread_.join();
    }

    ~HeartbeatTimer() { Stop(); }

private:
    void Run() {
        std::unique_lock<std::mutex> lock(mutex_);
        while (running_.load()) {
            if (cv_.wait_for(lock, std::chrono::milliseconds(200),
                              [this] { return !running_.load(); })) {
                break;
            }
            elapsedIntervals_ += 1;
            if (elapsedIntervals_ % kHeartbeatEveryIntervals == 0) {
                lock.unlock();
                emitter_.Emit(EventType::kHeartbeat, std::nullopt, "{}");
                lock.lock();
            }
        }
    }

    // 200ms poll * 5 = 1s heartbeat cadence, comfortably under the supervisor's default
    // heartbeat_timeout_s of 5.0s.
    static constexpr int kHeartbeatEveryIntervals = 5;

    FrameEmitter& emitter_;
    std::thread thread_;
    std::mutex mutex_;
    std::condition_variable cv_;
    std::atomic<bool> running_{false};
    int elapsedIntervals_ = 0;
};

class MockShim {
public:
    explicit MockShim(FrameEmitter& emitter) : emitter_(emitter), heartbeat_(emitter) {}

    void EmitReady() {
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
        emitter_.Emit(EventType::kReady, std::nullopt, payload.str());
        heartbeat_.Start();
    }

    void EmitCommandAccepted(CommandType command, const std::string& messageId,
                              const std::optional<std::string>& interactionId) {
        std::ostringstream payload;
        payload << "{\"command\":\"" << CommandTypeToWire(command)
                 << "\",\"message_id\":\"" << JsonEscape(messageId) << "\"}";
        emitter_.Emit(EventType::kCommandAccepted, interactionId, payload.str());
    }

    void EmitFailed(const std::string& code, const std::string& message) {
        std::ostringstream payload;
        payload << "{\"code\":\"" << JsonEscape(code) << "\",\"message\":\""
                 << JsonEscape(message) << "\"}";
        emitter_.Emit(EventType::kFailed, std::nullopt, payload.str());
    }

    // Returns false once the process should exit (after stopped/closed emitted).
    bool HandleLine(const std::string& line) {
        auto commandWire = ExtractStringField(line, "command");
        auto messageId = ExtractStringField(line, "message_id");
        auto interactionId = ExtractStringField(line, "interaction_id");
        if (!commandWire || !messageId) {
            EmitFailed("ERR_PROTOCOL_INVALID", "malformed command envelope");
            return true;
        }
        auto command = ParseCommand(*commandWire);
        if (!command) {
            EmitFailed("ERR_PROTOCOL_INVALID", "unknown command");
            return true;
        }
        switch (*command) {
            case CommandType::kStart:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                EmitReady();
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
                emitter_.Emit(EventType::kWakeWordConfirmed, std::nullopt, "{}");
                emitter_.Emit(EventType::kCaptureStarted, interactionId, "{}");
                emitter_.Emit(EventType::kTranscriptReady, interactionId,
                               "{\"text\":\"hola otto\"}");
                emitter_.Emit(EventType::kResponseReady, interactionId,
                               "{\"text\":\"respuesta mock\"}");
                emitter_.Emit(EventType::kPlaybackStarted, interactionId, "{}");
                emitter_.Emit(EventType::kPlaybackCompleted, interactionId,
                               "{\"duration_s\":0.0}");
                return true;
            }
            case CommandType::kPause:
            case CommandType::kResume:
                EmitCommandAccepted(*command, *messageId, interactionId);
                return true;
            case CommandType::kStop:
                EmitCommandAccepted(*command, *messageId, interactionId);
                emitter_.Emit(EventType::kCancelled, interactionId, "{}");
                return true;
            case CommandType::kEmergencyStop:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                heartbeat_.Stop();
                emitter_.Emit(EventType::kStopped, std::nullopt, "{}");
                return false;
            case CommandType::kClose:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                heartbeat_.Stop();
                emitter_.Emit(EventType::kClosed, std::nullopt, "{}");
                return false;
        }
        return true;
    }

private:
    FrameEmitter& emitter_;
    HeartbeatTimer heartbeat_;
};

}  // namespace

int main() {
    FrameEmitter emitter;
    MockShim shim(emitter);
    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        const bool keepRunning = shim.HandleLine(line);
        if (!keepRunning) {
            return 0;
        }
    }
    return 0;
}
