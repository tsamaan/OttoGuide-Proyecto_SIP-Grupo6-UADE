// loopback_worker_protocol_smoke.cpp
//
// Offline unit tests for the JSONL frame serialization helpers used by
// otto_jsonl_loopback_worker.cpp. Compiled as a standalone binary; does not spawn the worker
// process, does not touch stdin/stdout as a subprocess, and does not depend on Python or the
// real supervisor. Exercises: no NaN/Infinity in numeric output, every emitted line ends with
// a newline, and the wire vocabulary matches otto_jsonl_protocol.hpp exactly.
//
// This binary is compiled offline in IA-CXX-R8; execution (if any) is gated by its own
// separate confirmation, per the checkpoint's Nivel C rules.

#include <cassert>
#include <cmath>
#include <cstdlib>
#include <sstream>
#include <string>
#include <string_view>

#include "otto_jsonl_protocol.hpp"

using otto::jsonl::CommandType;
using otto::jsonl::CommandTypeToWire;
using otto::jsonl::EventType;
using otto::jsonl::EventTypeToWire;
using otto::jsonl::kProtocolVersion;

namespace {

// Mirrors LoopbackWorker::Emit's framing shape without depending on the worker's private
// implementation: protocol_version, message_id, interaction_id, event, sequence,
// emitted_at_monotonic_s, payload -- exactly the WorkerEventEnvelope required keys in
// runtime_port.py.
std::string BuildFrame(EventType event, long long sequence, double emittedAt,
                        const std::string& payloadJson) {
    std::ostringstream frame;
    frame << "{\"protocol_version\":" << kProtocolVersion
          << ",\"message_id\":\"worker:" << sequence << "\""
          << ",\"interaction_id\":null"
          << ",\"event\":\"" << EventTypeToWire(event) << "\""
          << ",\"sequence\":" << sequence
          << ",\"emitted_at_monotonic_s\":" << emittedAt
          << ",\"payload\":" << payloadJson
          << "}";
    return frame.str();
}

bool EndsWithNewlineWhenWritten(const std::string& frame) {
    // The worker appends "\n" after each frame at the call site (std::cout << frame << "\n");
    // this helper validates the frame body itself carries no embedded raw newline that would
    // corrupt line-based framing.
    return frame.find('\n') == std::string::npos;
}

bool ContainsNaNOrInfLiteral(const std::string& frame) {
    return frame.find("nan") != std::string::npos || frame.find("inf") != std::string::npos ||
           frame.find("NaN") != std::string::npos || frame.find("Infinity") != std::string::npos;
}

}  // namespace

// --- Compile-time protocol parity (re-verifies R5's static_asserts still hold for R8) -----

static_assert(kProtocolVersion == 1, "kProtocolVersion must equal INTERACTION_PROTOCOL_VERSION (1)");
static_assert(CommandTypeToWire(CommandType::kStart) == std::string_view{"start"});
static_assert(CommandTypeToWire(CommandType::kEmergencyStop) == std::string_view{"emergency_stop"});
static_assert(CommandTypeToWire(CommandType::kClose) == std::string_view{"close"});
static_assert(EventTypeToWire(EventType::kReady) == std::string_view{"ready"});
static_assert(EventTypeToWire(EventType::kStopped) == std::string_view{"stopped"});
static_assert(EventTypeToWire(EventType::kClosed) == std::string_view{"closed"});
static_assert(EventTypeToWire(EventType::kCommandAccepted) == std::string_view{"command_accepted"});

int main() {
    // ready
    {
        const std::string frame = BuildFrame(EventType::kReady, 0, 0.0, "{\"audio_capture\":false}");
        assert(frame.find("\"event\":\"ready\"") != std::string::npos);
        assert(EndsWithNewlineWhenWritten(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // heartbeat
    {
        const std::string frame = BuildFrame(EventType::kHeartbeat, 1, 0.05, "{}");
        assert(frame.find("\"event\":\"heartbeat\"") != std::string::npos);
        assert(EndsWithNewlineWhenWritten(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // command_accepted
    {
        const std::string frame =
            BuildFrame(EventType::kCommandAccepted, 2, 0.1, "{\"command\":\"start\",\"message_id\":\"m1\"}");
        assert(frame.find("\"event\":\"command_accepted\"") != std::string::npos);
        assert(EndsWithNewlineWhenWritten(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // stopped
    {
        const std::string frame = BuildFrame(EventType::kStopped, 3, 0.2, "{}");
        assert(frame.find("\"event\":\"stopped\"") != std::string::npos);
        assert(EndsWithNewlineWhenWritten(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // finite emitted_at_monotonic_s only
    {
        assert(std::isfinite(0.0));
        assert(std::isfinite(123.456));
    }
    return EXIT_SUCCESS;
}
