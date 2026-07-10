# CMakeLists.txt — otto_jsonl cxx_runtime skeleton (IA-CXX-R5)
#
# Isolated build definition for the productive C++ runtime skeleton under
# codigo ottoguide/src/interaction/cxx_runtime/. Does NOT depend on, include,
# or reference the legacy CMakeLists.txt under
# docs/legacy/interaccionia/Ottoguide_IA/src/otto_audio/cpp/, which remains
# untouched. Does not search for Unitree SDK, Whisper, Ollama, or Piper.
# Installs nothing. Runs no post-build commands. Produces build artifacts
# only inside the caller-specified build directory.

cmake_minimum_required(VERSION 3.16)

project(otto_cxx_runtime_skeleton CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(otto_jsonl_protocol INTERFACE)
target_include_directories(otto_jsonl_protocol INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# IA-CXX-R11: otto_jsonl_shim now runs a background heartbeat thread (std::thread), requiring
# the platform threading library. No other target in this file uses threads.
set(THREADS_PREFER_PTHREAD_FLAG ON)
find_package(Threads REQUIRED)

add_executable(otto_jsonl_shim
    src/otto_jsonl_shim.cpp
)
target_link_libraries(otto_jsonl_shim PRIVATE otto_jsonl_protocol Threads::Threads)

add_executable(otto_jsonl_protocol_smoke
    tests/protocol_contract_smoke.cpp
)
target_link_libraries(otto_jsonl_protocol_smoke PRIVATE otto_jsonl_protocol)

# IA-CXX-R8: protocol-compliant loopback worker (test double, no real audio/models/Unitree).
add_executable(otto_jsonl_loopback_worker
    src/otto_jsonl_loopback_worker.cpp
)
target_link_libraries(otto_jsonl_loopback_worker PRIVATE otto_jsonl_protocol)

add_executable(loopback_worker_protocol_smoke
    tests/loopback_worker_protocol_smoke.cpp
)
target_link_libraries(loopback_worker_protocol_smoke PRIVATE otto_jsonl_protocol)

# IA-CXX-R11: mocked dispatch loop smoke test (otto_jsonl_shim.cpp is no longer a stub).
add_executable(shim_mock_protocol_smoke
    tests/shim_mock_protocol_smoke.cpp
)
target_link_libraries(shim_mock_protocol_smoke PRIVATE otto_jsonl_protocol)
