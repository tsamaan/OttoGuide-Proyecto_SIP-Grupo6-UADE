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

# ---------------------------------------------------------------------------
# MVP-IA-CXX-R1: physical JSONL worker (real audio/STT/LLM/TTS).
#
# OFF by default so the offline protocol build above stays hardware-free and buildable on any
# host (no Unitree SDK / Whisper / CUDA required). Enable ONLY on the Jetson companion, where the
# real dependencies exist, with:
#   cmake -DOTTO_BUILD_PHYSICAL_WORKER=ON \
#         -DWHISPER_DIR=/home/unitree/Desktop/whisper.cpp \
#         -DUNITREE_SDK2_DIR=/opt/unitree_robotics/lib/cmake/unitree_sdk2 ...
#
# Paths/flags mirror the functional standalone CMakeLists.txt. This target links ONLY the Unitree
# AudioClient (audio), Whisper, and pthread — never any locomotion/posture/FSM library.
# ---------------------------------------------------------------------------
option(OTTO_BUILD_PHYSICAL_WORKER "Build the physical audio JSONL worker (needs Unitree SDK + Whisper)" OFF)

if(OTTO_BUILD_PHYSICAL_WORKER)
    if(NOT DEFINED WHISPER_DIR)
        set(WHISPER_DIR /home/unitree/Desktop/whisper.cpp)
    endif()
    if(NOT DEFINED UNITREE_SDK2_DIR)
        set(UNITREE_SDK2_DIR /opt/unitree_robotics/lib/cmake/unitree_sdk2)
    endif()

    find_package(unitree_sdk2 REQUIRED PATHS ${UNITREE_SDK2_DIR} NO_DEFAULT_PATH)

    add_executable(otto_jsonl_physical_worker
        src/otto_jsonl_physical_worker.cpp
    )
    target_include_directories(otto_jsonl_physical_worker PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_SOURCE_DIR}/vendor
        ${WHISPER_DIR}/include
        ${WHISPER_DIR}
        ${WHISPER_DIR}/ggml/include
    )
    target_link_libraries(otto_jsonl_physical_worker PRIVATE
        otto_jsonl_protocol
        unitree_sdk2
        ${WHISPER_DIR}/build/src/libwhisper.so
        ${WHISPER_DIR}/build/ggml/src/libggml.so
        ${WHISPER_DIR}/build/ggml/src/libggml-base.so
        ${WHISPER_DIR}/build/ggml/src/libggml-cpu.so
        ${WHISPER_DIR}/build/ggml/src/ggml-cuda/libggml-cuda.so
        Threads::Threads
    )
    set_target_properties(otto_jsonl_physical_worker PROPERTIES
        BUILD_RPATH "${WHISPER_DIR}/build/src:${WHISPER_DIR}/build/ggml/src:${WHISPER_DIR}/build/ggml/src/ggml-cuda"
        INSTALL_RPATH "${WHISPER_DIR}/build/src:${WHISPER_DIR}/build/ggml/src:${WHISPER_DIR}/build/ggml/src/ggml-cuda"
        BUILD_WITH_INSTALL_RPATH TRUE
    )
endif()
