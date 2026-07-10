// otto_jsonl_shim.cpp
//
// Compile-only dummy entrypoint for the productive C++ runtime skeleton
// under codigo ottoguide/src/interaction/cxx_runtime/. This is IA-CXX-R5:
// the binary built from this file is compiled offline and MUST NOT be
// executed as part of this checkpoint (see README.md).
//
// This file deliberately does nothing beyond a dummy status line to
// stderr: no stdin reading, no stdout JSONL writing, no sockets, no
// process spawning, no audio, no model calls. A future checkpoint
// (post-R5, with its own explicit authorization) is responsible for
// implementing the real stdin/stdout dispatch loop described in
// docs/Arquitectura/IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md.

#include <iostream>

#include "otto_jsonl_protocol.hpp"

namespace {

// Dummy, side-effect-free "would this compile against the real protocol"
// check: exercises the wire-string mapping functions at compile time via
// constexpr evaluation, without any I/O.
constexpr bool kStartWireIsCorrect =
    otto::jsonl::CommandTypeToWire(otto::jsonl::CommandType::kStart) == "start";
constexpr bool kReadyWireIsCorrect =
    otto::jsonl::EventTypeToWire(otto::jsonl::EventType::kReady) == "ready";

static_assert(kStartWireIsCorrect, "start command wire string must be \"start\"");
static_assert(kReadyWireIsCorrect, "ready event wire string must be \"ready\"");

}  // namespace

int main() {
    // Dummy status line only, to stderr. Not JSONL protocol output — this
    // binary does not speak the real protocol yet, and must not be treated
    // as a functioning worker by any supervisor.
    std::cerr << "otto_jsonl_shim: compile-only skeleton (IA-CXX-R5), "
                 "protocol_version="
              << otto::jsonl::kProtocolVersion
              << ", no dispatch loop implemented, no I/O performed, exiting"
              << std::endl;
    return 0;
}
