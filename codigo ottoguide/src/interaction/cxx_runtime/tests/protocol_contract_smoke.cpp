// protocol_contract_smoke.cpp
//
// Offline compile/smoke test for otto_jsonl_protocol.hpp. Verifies, via
// static_assert (compile-time) and a small set of runtime asserts, that
// the wire-string mapping in the header matches the exact string values
// declared in codigo ottoguide/src/interaction/runtime_port.py.
//
// No robot, no network, no audio, no external dependencies, no Python
// dependency, no subprocess execution of the real shim binary. This test
// binary is compiled offline in IA-CXX-R5 but is NOT executed as part of
// this checkpoint — execution (running the produced binary and checking
// its exit code) is deferred to a future checkpoint (R6, smoke test with
// dummy binary) per docs/Arquitectura/IA_CXX_R4_CXX_RUNTIME_CODE_PLACEMENT_AND_BUILD_GATES.md.

#include <cassert>
#include <cstdlib>
#include <string_view>

#include "otto_jsonl_protocol.hpp"

using otto::jsonl::CommandType;
using otto::jsonl::CommandTypeToWire;
using otto::jsonl::EventType;
using otto::jsonl::EventTypeToWire;
using otto::jsonl::IsProcessCommand;
using otto::jsonl::IsProcessEvent;

// --- Compile-time parity checks (protocol version + full command set) ------

static_assert(otto::jsonl::kProtocolVersion == 1,
              "kProtocolVersion must equal INTERACTION_PROTOCOL_VERSION (1)");

static_assert(CommandTypeToWire(CommandType::kStart) == std::string_view{"start"});
static_assert(CommandTypeToWire(CommandType::kHealth) == std::string_view{"health"});
static_assert(CommandTypeToWire(CommandType::kActivate) == std::string_view{"activate"});
static_assert(CommandTypeToWire(CommandType::kPause) == std::string_view{"pause"});
static_assert(CommandTypeToWire(CommandType::kResume) == std::string_view{"resume"});
static_assert(CommandTypeToWire(CommandType::kStop) == std::string_view{"stop"});
static_assert(CommandTypeToWire(CommandType::kEmergencyStop) ==
              std::string_view{"emergency_stop"});
static_assert(CommandTypeToWire(CommandType::kClose) == std::string_view{"close"});

static_assert(EventTypeToWire(EventType::kReady) == std::string_view{"ready"});
static_assert(EventTypeToWire(EventType::kHeartbeat) == std::string_view{"heartbeat"});
static_assert(EventTypeToWire(EventType::kCommandAccepted) ==
              std::string_view{"command_accepted"});
static_assert(EventTypeToWire(EventType::kWakeWordConfirmed) ==
              std::string_view{"wake_word_confirmed"});
static_assert(EventTypeToWire(EventType::kCaptureStarted) ==
              std::string_view{"capture_started"});
static_assert(EventTypeToWire(EventType::kTranscriptReady) ==
              std::string_view{"transcript_ready"});
static_assert(EventTypeToWire(EventType::kResponseReady) ==
              std::string_view{"response_ready"});
static_assert(EventTypeToWire(EventType::kPlaybackStarted) ==
              std::string_view{"playback_started"});
static_assert(EventTypeToWire(EventType::kPlaybackCompleted) ==
              std::string_view{"playback_completed"});
static_assert(EventTypeToWire(EventType::kInteractionTimeout) ==
              std::string_view{"interaction_timeout"});
static_assert(EventTypeToWire(EventType::kCancelled) == std::string_view{"cancelled"});
static_assert(EventTypeToWire(EventType::kFailed) == std::string_view{"failed"});
static_assert(EventTypeToWire(EventType::kStopped) == std::string_view{"stopped"});
static_assert(EventTypeToWire(EventType::kClosed) == std::string_view{"closed"});

// --- Compile-time process/interaction partition checks ---------------------

static_assert(IsProcessCommand(CommandType::kStart));
static_assert(IsProcessCommand(CommandType::kHealth));
static_assert(IsProcessCommand(CommandType::kEmergencyStop));
static_assert(IsProcessCommand(CommandType::kClose));
static_assert(!IsProcessCommand(CommandType::kActivate));
static_assert(!IsProcessCommand(CommandType::kPause));
static_assert(!IsProcessCommand(CommandType::kResume));
static_assert(!IsProcessCommand(CommandType::kStop));

static_assert(IsProcessEvent(EventType::kReady));
static_assert(IsProcessEvent(EventType::kHeartbeat));
static_assert(IsProcessEvent(EventType::kWakeWordConfirmed));
static_assert(IsProcessEvent(EventType::kStopped));
static_assert(IsProcessEvent(EventType::kClosed));
static_assert(!IsProcessEvent(EventType::kCaptureStarted));
static_assert(!IsProcessEvent(EventType::kTranscriptReady));
static_assert(!IsProcessEvent(EventType::kResponseReady));

int main() {
    // Redundant runtime asserts mirroring the static_asserts above, kept
    // deliberately trivial: this binary is compiled but not executed as
    // part of IA-CXX-R5. A future checkpoint that does execute it will
    // rely on these asserts as an additional runtime confirmation layer.
    assert(otto::jsonl::kProtocolVersion == 1);
    assert(CommandTypeToWire(CommandType::kActivate) == std::string_view{"activate"});
    assert(EventTypeToWire(EventType::kFailed) == std::string_view{"failed"});
    return EXIT_SUCCESS;
}
