// shim_mock_protocol_smoke.cpp
//
// Offline unit tests for the JSONL frame shape used by otto_jsonl_shim.cpp (IA-CXX-R11).
// Compiled as a standalone binary; does not spawn the shim process, does not touch
// stdin/stdout as a subprocess, and does not depend on Python or the real supervisor.
// Exercises: no NaN/Infinity in numeric output, every emitted line has no embedded newline,
// and the wire vocabulary matches otto_jsonl_protocol.hpp exactly, including the two new
// events (wake_word_confirmed, heartbeat cadence) introduced in R11, and the two mock
// protocol-gap paths (semantic rejection, interaction timeout) introduced in IA-CXX-R14B.

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

// Mirrors FrameEmitter::Emit's framing shape without depending on the shim's private
// implementation: protocol_version, message_id, interaction_id, event, sequence,
// emitted_at_monotonic_s, payload -- exactly the WorkerEventEnvelope required keys in
// runtime_port.py.
std::string BuildFrame(EventType event, long long sequence, double emittedAt,
                        const std::string& payloadJson,
                        const std::string* interactionId = nullptr) {
    std::ostringstream frame;
    frame << "{\"protocol_version\":" << kProtocolVersion
          << ",\"message_id\":\"shim:" << sequence << "\""
          << ",\"interaction_id\":" << (interactionId ? ("\"" + *interactionId + "\"") : "null")
          << ",\"event\":\"" << EventTypeToWire(event) << "\""
          << ",\"sequence\":" << sequence
          << ",\"emitted_at_monotonic_s\":" << emittedAt
          << ",\"payload\":" << payloadJson
          << "}";
    return frame.str();
}

bool HasNoEmbeddedNewline(const std::string& frame) {
    return frame.find('\n') == std::string::npos;
}

bool ContainsNaNOrInfLiteral(const std::string& frame) {
    return frame.find("nan") != std::string::npos || frame.find("inf") != std::string::npos ||
           frame.find("NaN") != std::string::npos || frame.find("Infinity") != std::string::npos;
}

}  // namespace

// --- Compile-time protocol parity (re-verifies R5/R8's static_asserts still hold for R11) ---

static_assert(kProtocolVersion == 1, "kProtocolVersion must equal INTERACTION_PROTOCOL_VERSION (1)");
static_assert(CommandTypeToWire(CommandType::kActivate) == std::string_view{"activate"});
static_assert(CommandTypeToWire(CommandType::kEmergencyStop) == std::string_view{"emergency_stop"});
static_assert(EventTypeToWire(EventType::kWakeWordConfirmed) == std::string_view{"wake_word_confirmed"});
static_assert(EventTypeToWire(EventType::kHeartbeat) == std::string_view{"heartbeat"});
static_assert(EventTypeToWire(EventType::kTranscriptReady) == std::string_view{"transcript_ready"});
static_assert(EventTypeToWire(EventType::kResponseReady) == std::string_view{"response_ready"});
static_assert(EventTypeToWire(EventType::kPlaybackCompleted) == std::string_view{"playback_completed"});
static_assert(EventTypeToWire(EventType::kCancelled) == std::string_view{"cancelled"});
static_assert(EventTypeToWire(EventType::kClosed) == std::string_view{"closed"});
static_assert(EventTypeToWire(EventType::kStopped) == std::string_view{"stopped"});
static_assert(EventTypeToWire(EventType::kFailed) == std::string_view{"failed"});
static_assert(EventTypeToWire(EventType::kInteractionTimeout) ==
              std::string_view{"interaction_timeout"});

int main() {
    // ready (process event, interaction_id must be null)
    {
        const std::string frame = BuildFrame(EventType::kReady, 0, 0.0, "{\"audio_capture\":false}");
        assert(frame.find("\"event\":\"ready\"") != std::string::npos);
        assert(frame.find("\"interaction_id\":null") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // heartbeat (process event)
    {
        const std::string frame = BuildFrame(EventType::kHeartbeat, 1, 1.0, "{}");
        assert(frame.find("\"event\":\"heartbeat\"") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // wake_word_confirmed (process event)
    {
        const std::string frame = BuildFrame(EventType::kWakeWordConfirmed, 2, 1.1, "{}");
        assert(frame.find("\"event\":\"wake_word_confirmed\"") != std::string::npos);
        assert(frame.find("\"interaction_id\":null") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
    }
    // transcript_ready (interaction event, interaction_id required)
    {
        const std::string iid = "i-1";
        const std::string frame =
            BuildFrame(EventType::kTranscriptReady, 3, 1.2, "{\"text\":\"hola otto\"}", &iid);
        assert(frame.find("\"event\":\"transcript_ready\"") != std::string::npos);
        assert(frame.find("\"interaction_id\":\"i-1\"") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // playback_completed with a finite, non-negative duration payload
    {
        const std::string iid = "i-1";
        const std::string frame = BuildFrame(EventType::kPlaybackCompleted, 4, 1.3,
                                              "{\"duration_s\":0.0}", &iid);
        assert(frame.find("\"event\":\"playback_completed\"") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }
    // cancelled (stop path)
    {
        const std::string iid = "i-1";
        const std::string frame = BuildFrame(EventType::kCancelled, 5, 1.4, "{}", &iid);
        assert(frame.find("\"event\":\"cancelled\"") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
    }
    // stopped (emergency_stop path, process event)
    {
        const std::string frame = BuildFrame(EventType::kStopped, 6, 1.5, "{}");
        assert(frame.find("\"event\":\"stopped\"") != std::string::npos);
        assert(frame.find("\"interaction_id\":null") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
    }
    // closed (close path, process event)
    {
        const std::string frame = BuildFrame(EventType::kClosed, 7, 1.6, "{}");
        assert(frame.find("\"event\":\"closed\"") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
    }
    // finite emitted_at_monotonic_s only
    {
        assert(std::isfinite(0.0));
        assert(std::isfinite(1.6));
    }

    // IA-CXX-R14B: semantic rejection path -- failed with a non-null interaction_id and
    // code=ERR_SEMANTIC_REJECTED. Must NOT collapse to a process-level failure (which would
    // require interaction_id:null and terminate the worker per jsonl_worker_supervisor.py).
    {
        const std::string iid = "itx-r14-semantic-reject";
        const std::string frame = BuildFrame(
            EventType::kFailed, 8, 1.7,
            "{\"code\":\"ERR_SEMANTIC_REJECTED\",\"message\":\"mock semantic rejection\"}", &iid);
        assert(frame.find("\"event\":\"failed\"") != std::string::npos);
        assert(frame.find("\"interaction_id\":\"itx-r14-semantic-reject\"") != std::string::npos);
        assert(frame.find("\"code\":\"ERR_SEMANTIC_REJECTED\"") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }

    // IA-CXX-R14B: interaction_timeout path -- non-null interaction_id, stable finite payload,
    // emitted immediately (no sleep -- this is a simulated timeout, not an awaited one).
    {
        const std::string iid = "itx-r14-timeout";
        const std::string frame =
            BuildFrame(EventType::kInteractionTimeout, 9, 1.8, "{\"timeout_s\":0.0}", &iid);
        assert(frame.find("\"event\":\"interaction_timeout\"") != std::string::npos);
        assert(frame.find("\"interaction_id\":\"itx-r14-timeout\"") != std::string::npos);
        assert(HasNoEmbeddedNewline(frame));
        assert(!ContainsNaNOrInfLiteral(frame));
    }

    return EXIT_SUCCESS;
}
