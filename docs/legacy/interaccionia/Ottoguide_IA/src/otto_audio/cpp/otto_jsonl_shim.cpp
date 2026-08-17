// SKELETON — no compilado, no ejecutado en IA-CXX-R2.
// @TASK: main() esqueleto del shim JSONL que envolvera (sin modificarlo) a
//        otto_pipeline.cpp, hablando el protocolo declarado en
//        otto_jsonl_protocol.hpp por stdin/stdout, con stderr exclusivo para logs.
// @CONTEXT: docs/Arquitectura/IA_CXX_R2_CXX_JSONL_SHIM_DESIGN.md, secciones 9, 14, 15, 21.
// @SECURITY: Este archivo NO incluye whisper.h, unitree/*, no llama a Whisper/Ollama/Piper,
//            no abre sockets UDP reales, no usa system(), no reproduce audio.
//            Todo cuerpo de funcion "real" esta marcado TODO y deliberadamente vacio/stub.
//
// No integrado a CMakeLists.txt en R2. No compilar. No ejecutar.

#include <iostream>
#include <string>

#include "otto_jsonl_protocol.hpp"

namespace otto::jsonl {

// TODO(R3+): leer una linea de stdin y parsearla como CommandEnvelopeSchema.
// En R2 esto es un stub declarativo: no lee stdin real, no bloquea, no ejecuta nada.
std::optional<CommandEnvelopeSchema> ReadCommandFromStdin() {
    // TODO: std::getline(std::cin, line); parsear JSON; validar contra
    // otto_jsonl_protocol.hpp (protocol_version, identifier rules, sequence).
    return std::nullopt;
}

// TODO(R3+): serializar un EventEnvelopeSchema a una linea JSON y escribirla a stdout.
// En R2 esto es un stub declarativo: no escribe a stdout real fuera de este comentario.
void EmitEvent(const EventEnvelopeSchema& /*event*/) {
    // TODO: construir JSON minimo (sin dependencias externas o con una libreria
    // JSON aprobada en un checkpoint futuro) y escribir una unica linea a std::cout,
    // seguida de flush. stdout es protocolo exclusivamente (ver diseño R2, seccion 9).
}

// TODO(R3+): logging humano exclusivamente por stderr, nunca por stdout.
void LogInfo(const std::string& message) {
    std::cerr << "[otto_jsonl_shim] " << message << std::endl;
}

// --- Dispatch de comandos (stubs documentales, sin efectos reales) ----------
// Cada handler describe QUE haria en un checkpoint futuro de build/ejecucion,
// pero no invoca a otto_pipeline.cpp, Whisper, Ollama, Piper, ni AudioClient.

void HandleStart() {
    // TODO(R4+): inicializar dependencias fail-closed (ver diseño R2, seccion 14).
    // Si whisper.cpp / modelo / Ollama / Piper / SDK Unitree no estan disponibles,
    // debe fallar el arranque (emitir "failed", no simular una respuesta real).
    LogInfo("HandleStart: stub, no dependencies initialized in R2");
}

void HandleHealth() {
    // TODO(R4+): reportar InteractionRuntimeHealth-equivalente (protocol_version,
    // state, ready, capabilities, last_heartbeat_monotonic_s, last_error).
    LogInfo("HandleHealth: stub, no real health computed in R2");
}

void HandleActivate(const CommandEnvelopeSchema& /*command*/) {
    // TODO(R4+): conectar con el bucle de estados existente de otto_pipeline.cpp
    // (HIBERNACION/ESCUCHANDO/PROCESANDO) via mecanismo aun no definido — ver
    // diseño R2, seccion 17 ("que NO se extrae todavia").
    LogInfo("HandleActivate: stub, no interaction started in R2");
}

void HandlePause() {
    LogInfo("HandlePause: stub in R2");
}

void HandleResume() {
    LogInfo("HandleResume: stub in R2");
}

void HandleStop() {
    LogInfo("HandleStop: stub in R2");
}

void HandleEmergencyStop() {
    // TODO(R4+): debe tener prioridad sobre cualquier operacion de audio en curso
    // (ver diseño R2, seccion 12). En R2 no hay audio real que detener.
    LogInfo("HandleEmergencyStop: stub in R2");
}

void HandleClose() {
    LogInfo("HandleClose: stub in R2");
}

// TODO(R3+): bucle de heartbeat periodico independiente del dispatch de comandos
// (ver diseño R2, seccion 11). En R2 no se inicia ningun hilo ni timer real.
void HeartbeatLoopStub() {
    // TODO: emitir EventType::kHeartbeat periodicamente en un hilo separado,
    // usando std::chrono::steady_clock, una vez exista una implementacion real
    // de EmitEvent().
}

}  // namespace otto::jsonl

// main() skeleton — deliberadamente no funcional en R2.
// TODO(R3+): reemplazar por un bucle real de lectura stdin / dispatch / stdout,
// una vez exista al menos un test de protocolo contra un fake-worker (R3).
int main() {
    otto::jsonl::LogInfo(
        "otto_jsonl_shim: skeleton R2, no dispatch loop implemented, exiting immediately");
    return 0;
}
