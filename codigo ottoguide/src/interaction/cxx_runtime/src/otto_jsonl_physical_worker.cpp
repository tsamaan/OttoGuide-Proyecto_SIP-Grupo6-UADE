// otto_jsonl_physical_worker.cpp
//
// MVP-IA-CXX-R1: physical JSONL interaction worker for OttoGuide (Unitree G1 EDU).
//
// This is the FIRST non-mock worker: it drives the real audio interaction stack
// (UDP multicast microphone -> Whisper GPU STT -> Ollama LLM -> Piper TTS ->
// Unitree AudioClient PlayStream/PlayStop) while speaking the canonical JSONL wire
// protocol declared in codigo ottoguide/src/interaction/runtime_port.py (mirrored in
// otto_jsonl_protocol.hpp). It is a drop-in for JsonlInteractionWorkerSupervisor, exactly
// like otto_jsonl_shim.cpp, but with grounded physical capabilities.
//
// It REUSES the proven logic and constants of the functional standalone pipeline
// (docs/legacy/.../otto_pipeline.cpp), which remains byte-for-byte untouched. This is a
// separate, new file: no edit of the protected pipeline.
//
// Discipline:
//   stdout  = JSONL protocol frames ONLY (WorkerEventEnvelope), one object per line.
//   stderr  = human logs ONLY.
// It links ONLY the Unitree AudioClient (audio), Whisper, and pthread. It NEVER references any
// locomotion / posture / FSM API (LocoClient, MotionSwitcher, StopMove, Damp, BalanceStand,
// SetFsmId, cmd_vel). No motion is possible from this process.
//
// C++17.

#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <fstream>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "whisper.h"
#include <unitree/common/time/time_tool.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/audio/g1_audio_client.hpp>
#include "wav.hpp"

#include "otto_jsonl_protocol.hpp"

// ===========================================================================
// Configuration (reused verbatim from the functional pipeline).
// ===========================================================================
namespace {

constexpr const char* kMcastGrp   = "239.168.123.161";
constexpr int         kMcastPort  = 5555;
constexpr const char* kLocalIp    = "192.168.123.164";
constexpr int         kSampleRate = 16000;
constexpr int         kCaptureSecs = 3;
constexpr int         kRmsThreshold = 2000;
constexpr int         kChunkSize   = 96000;
constexpr int         kSdkVolume   = 70;

constexpr const char* kWhisperModel = "/home/unitree/Desktop/whisper.cpp/models/ggml-large-v3-turbo.bin";
constexpr const char* kWhisperPrompt = "UADE Otto OttoGuide";
constexpr const char* kPiperBin   = "/home/unitree/piper/piper";
constexpr const char* kPiperVoice = "/home/unitree/piper/voices/es_MX-gevy-high.onnx";
constexpr const char* kNetIface   = "eth0";

using otto::jsonl::CommandType;
using otto::jsonl::CommandTypeToWire;
using otto::jsonl::EventType;
using otto::jsonl::EventTypeToWire;
using otto::jsonl::kProtocolVersion;

// ---------------------------------------------------------------------------
// Shared audio buffer + capture thread (reused from the pipeline).
// ---------------------------------------------------------------------------
std::mutex             g_buf_mutex;
std::vector<int16_t>   g_audio_buffer;
std::atomic<bool>      g_running{true};
unitree::robot::g1::AudioClient* g_audio = nullptr;

double MonotonicSeconds() {
    static const auto start = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

void LogErr(const std::string& msg) {
    std::cerr << "[physical_worker] " << msg << std::endl;
}

// ---------------------------------------------------------------------------
// JSON helpers.
// ---------------------------------------------------------------------------
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

// Minimal top-level string field extractor for the flat command envelopes the Python
// supervisor writes (WorkerCommandEnvelope.to_wire_dict()). Same shape handled by the shim.
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

// ---------------------------------------------------------------------------
// FrameEmitter: serializes one WorkerEventEnvelope JSONL line to stdout, mutex-guarded
// (heartbeat thread, interaction thread and dispatch loop all emit).
// ---------------------------------------------------------------------------
class FrameEmitter {
public:
    void Emit(EventType event, const std::optional<std::string>& interactionId,
              const std::string& payloadJson) {
        long long sequence;
        {
            std::lock_guard<std::mutex> lock(seq_mutex_);
            sequence = sequence_++;
        }
        std::ostringstream frame;
        frame << "{\"protocol_version\":" << kProtocolVersion
              << ",\"message_id\":\"physical:" << sequence << "\""
              << ",\"interaction_id\":"
              << (interactionId ? ("\"" + JsonEscape(*interactionId) + "\"") : "null")
              << ",\"event\":\"" << EventTypeToWire(event) << "\""
              << ",\"sequence\":" << sequence
              << ",\"emitted_at_monotonic_s\":" << MonotonicSeconds()
              << ",\"payload\":" << payloadJson
              << "}";
        std::lock_guard<std::mutex> lock(out_mutex_);
        std::cout << frame.str() << "\n";
        std::cout.flush();
    }

private:
    std::mutex seq_mutex_;
    std::mutex out_mutex_;
    long long sequence_ = 0;
};

// ---------------------------------------------------------------------------
// HeartbeatTimer: ~1s heartbeat cadence, joins cleanly (no dangling thread).
// ---------------------------------------------------------------------------
class HeartbeatTimer {
public:
    explicit HeartbeatTimer(FrameEmitter& emitter) : emitter_(emitter) {}
    ~HeartbeatTimer() { Stop(); }

    void Start() {
        if (running_.exchange(true)) return;
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

private:
    void Run() {
        std::unique_lock<std::mutex> lock(mutex_);
        int intervals = 0;
        while (running_.load()) {
            if (cv_.wait_for(lock, std::chrono::milliseconds(200),
                             [this] { return !running_.load(); })) {
                break;
            }
            if (++intervals % 5 == 0) {
                lock.unlock();
                emitter_.Emit(EventType::kHeartbeat, std::nullopt, "{}");
                lock.lock();
            }
        }
    }

    FrameEmitter& emitter_;
    std::thread thread_;
    std::mutex mutex_;
    std::condition_variable cv_;
    std::atomic<bool> running_{false};
};

// ===========================================================================
// Reused audio / STT / LLM / TTS logic (adapted from the functional pipeline;
// human status prints redirected to stderr to keep stdout JSONL-clean).
// ===========================================================================

void CaptureThread() {
    int sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sock < 0) { LogErr("capture: socket() failed"); return; }
    struct timeval tv{1, 0};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    int reuse = 1;
    setsockopt(sock, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_port        = htons(kMcastPort);
    addr.sin_addr.s_addr = INADDR_ANY;
    bind(sock, (sockaddr*)&addr, sizeof(addr));

    ip_mreq mreq{};
    inet_pton(AF_INET, kMcastGrp, &mreq.imr_multiaddr);
    inet_pton(AF_INET, kLocalIp,  &mreq.imr_interface);
    setsockopt(sock, IPPROTO_IP, IP_ADD_MEMBERSHIP, &mreq, sizeof(mreq));

    LogErr(std::string("capture: UDP multicast ") + kMcastGrp + ":" + std::to_string(kMcastPort));

    while (g_running.load()) {
        char buf[65535];
        ssize_t n = recvfrom(sock, buf, sizeof(buf), 0, nullptr, nullptr);
        if (n <= 0) continue;
        std::lock_guard<std::mutex> lock(g_buf_mutex);
        const int16_t* ptr = reinterpret_cast<const int16_t*>(buf);
        g_audio_buffer.insert(g_audio_buffer.end(), ptr, ptr + n / 2);
        const size_t kMax = static_cast<size_t>(kSampleRate) * 30;
        if (g_audio_buffer.size() > kMax) {
            g_audio_buffer.erase(g_audio_buffer.begin(),
                                 g_audio_buffer.begin() + (g_audio_buffer.size() - kMax));
        }
    }
    close(sock);
}

float CalcularRms(const std::vector<int16_t>& s) {
    if (s.empty()) return 0.0f;
    double sum = 0;
    for (auto x : s) sum += static_cast<double>(x) * x;
    return static_cast<float>(std::sqrt(sum / s.size()));
}

std::vector<int16_t> TomarAudio(size_t segundos) {
    size_t n = static_cast<size_t>(kSampleRate) * segundos;
    std::lock_guard<std::mutex> lock(g_buf_mutex);
    if (g_audio_buffer.size() < n) return {};
    std::vector<int16_t> chunk(g_audio_buffer.end() - n, g_audio_buffer.end());
    g_audio_buffer.clear();
    return chunk;
}

void ClearBuffer() {
    std::lock_guard<std::mutex> lock(g_buf_mutex);
    g_audio_buffer.clear();
}

// VAD utterance capture (from the pipeline). cancel flag lets stop/emergency abort promptly.
std::vector<int16_t> TomarUtterance(float rmsHabla, std::atomic<bool>& cancel,
                                    int msSilencio = 700, int msMax = 8000) {
    const int windowSamples = kSampleRate * 150 / 1000;
    const int silenceWindows = msSilencio / 150;
    const int maxWindows = msMax / 150;

    std::vector<int16_t> utterance;
    int silence = 0, voice = 0;
    bool hablando = false;

    for (int w = 0; w < maxWindows && !cancel.load(); ++w) {
        usleep(150000);
        std::vector<int16_t> window;
        {
            std::lock_guard<std::mutex> lock(g_buf_mutex);
            if (g_audio_buffer.size() >= static_cast<size_t>(windowSamples)) {
                window.assign(g_audio_buffer.begin(), g_audio_buffer.begin() + windowSamples);
                g_audio_buffer.erase(g_audio_buffer.begin(), g_audio_buffer.begin() + windowSamples);
            }
        }
        if (window.empty()) continue;
        float rms = CalcularRms(window);
        if (rms >= rmsHabla) {
            voice++; silence = 0;
            utterance.insert(utterance.end(), window.begin(), window.end());
            if (voice >= 2) hablando = true;
        } else if (hablando) {
            silence++;
            utterance.insert(utterance.end(), window.begin(), window.end());
            if (silence >= silenceWindows) break;
        } else {
            voice = 0;
        }
    }
    if (voice < 2) return {};
    return utterance;
}

std::string Transcribir(whisper_context* ctx, const std::vector<int16_t>& pcm) {
    float maxVal = 1.0f;
    for (auto s : pcm) maxVal = std::max(maxVal, std::abs(static_cast<float>(s)));
    float gain = (maxVal > 500.0f) ? (20000.0f / maxVal) : 1.0f;

    std::vector<float> f32(pcm.size());
    for (size_t i = 0; i < pcm.size(); ++i)
        f32[i] = std::min(1.0f, std::max(-1.0f, (pcm[i] * gain) / 32768.0f));

    whisper_full_params p = whisper_full_default_params(WHISPER_SAMPLING_BEAM_SEARCH);
    p.language = "es";
    p.print_progress = false;
    p.print_realtime = false;
    p.print_timestamps = false;
    p.no_context = true;
    p.initial_prompt = kWhisperPrompt;
    p.n_threads = 4;
    p.beam_search.beam_size = 3;
    p.no_speech_thold = 0.4f;
    p.temperature = 0.0f;

    if (whisper_full(ctx, p, f32.data(), static_cast<int>(f32.size())) != 0) return "";
    std::string result;
    int nseg = whisper_full_n_segments(ctx);
    for (int i = 0; i < nseg; ++i) result += whisper_full_get_segment_text(ctx, i);
    while (!result.empty() && (result[0] == ' ' || result[0] == '\n')) result.erase(0, 1);
    return result;
}

std::string OllamaQuery(const std::string& pregunta) {
    int sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0) return "";
    struct timeval tv{60, 0};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(11434);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
    if (connect(sock, (sockaddr*)&addr, sizeof(addr)) < 0) { close(sock); return ""; }

    std::string p = pregunta;
    size_t pos = 0;
    while ((pos = p.find('"', pos)) != std::string::npos) { p.replace(pos, 1, "\\\""); pos += 2; }
    std::string body = "{\"model\":\"otto\",\"prompt\":\"" + p + "\",\"stream\":false,\"think\":false}";
    std::string req = "POST /api/generate HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                      "Content-Type: application/json\r\nContent-Length: " +
                      std::to_string(body.size()) + "\r\n\r\n" + body;
    send(sock, req.c_str(), req.size(), 0);
    std::string resp; char buf[4096]; int n;
    while ((n = recv(sock, buf, sizeof(buf) - 1, 0)) > 0) { buf[n] = 0; resp += buf; }
    close(sock);

    std::string key = "\"response\":\"";
    size_t s = resp.find(key);
    if (s == std::string::npos) return "";
    s += key.size();
    std::string result;
    for (size_t i = s; i < resp.size(); ++i) {
        if (resp[i] == '\\' && i + 1 < resp.size() && resp[i + 1] == '"') { result += '"'; ++i; }
        else if (resp[i] == '\\' && i + 1 < resp.size() && resp[i + 1] == 'n') { result += ' '; ++i; }
        else if (resp[i] == '"') break;
        else result += resp[i];
    }
    return result;
}

// Synthesize with Piper + normalize with ffmpeg, then stream via AudioClient. Returns playback
// duration seconds (>=0), or -1 on synthesis error. Honors cancel between chunks (stop/emergency).
double OttoSpeak(const std::string& texto, std::atomic<bool>& cancel) {
    {
        std::ofstream f("/tmp/otto_phys_text.txt");
        f << texto;
    }
    std::string piper = std::string("cat /tmp/otto_phys_text.txt | ") + kPiperBin +
                        " --model " + kPiperVoice +
                        " --output_file /tmp/otto_phys_raw.wav >/dev/null 2>&1";
    if (system(piper.c_str()) != 0) { LogErr("tts: piper failed"); return -1; }
    if (system("ffmpeg -y -i /tmp/otto_phys_raw.wav -ar 16000 -ac 1 -sample_fmt s16 "
               "-af \"volume=3.0\" /tmp/otto_phys.wav -loglevel quiet") != 0) {
        LogErr("tts: ffmpeg failed");
        return -1;
    }
    int32_t sr = -1; int8_t ch = 0; bool ok = false;
    auto pcm = ReadWave("/tmp/otto_phys.wav", &sr, &ch, &ok);
    if (!ok || sr != 16000 || ch != 1) { LogErr("tts: bad WAV"); return -1; }
    if (g_audio == nullptr) { LogErr("tts: no AudioClient"); return -1; }

    std::string sid = std::to_string(unitree::common::GetCurrentTimeMillisecond());
    size_t offset = 0, total = pcm.size();
    double dur = static_cast<double>(total) / (16000.0 * 2.0);
    auto t0 = std::chrono::steady_clock::now();
    while (offset < total && !cancel.load()) {
        size_t sz = std::min(static_cast<size_t>(kChunkSize), total - offset);
        std::vector<uint8_t> chunk(pcm.begin() + offset, pcm.begin() + offset + sz);
        g_audio->PlayStream("otto", sid, chunk);
        offset += sz;
        if (offset < total) unitree::common::Sleep(1);
    }
    if (!cancel.load()) {
        double elapsed = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - t0).count();
        double remaining = dur + 0.3 - elapsed;
        if (remaining > 0) usleep(static_cast<int>(remaining * 1000000));
    }
    g_audio->PlayStop("otto");
    ClearBuffer();
    return dur;
}

bool EsWakeWord(const std::string& t) {
    std::string s;
    for (char c : t) s += static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s.find("hola otto") != std::string::npos ||
           s.find("ola otto")  != std::string::npos ||
           s.find("hola oto")  != std::string::npos ||
           s.find("hola, otto") != std::string::npos;
}

// ===========================================================================
// PhysicalWorker: JSONL dispatch + single-interaction lifecycle.
// ===========================================================================
class PhysicalWorker {
public:
    explicit PhysicalWorker(FrameEmitter& emitter) : emitter_(emitter), heartbeat_(emitter) {}

    // Boot the real audio stack. Returns false if hardware/model init fails.
    bool BootHardware() {
        unitree::robot::ChannelFactory::Instance()->Init(0, kNetIface);
        audio_client_ = std::make_unique<unitree::robot::g1::AudioClient>();
        audio_client_->SetTimeout(10.0f);
        audio_client_->Init();
        audio_client_->SetVolume(kSdkVolume);
        g_audio = audio_client_.get();
        uint8_t vol = 0;
        if (audio_client_->GetVolume(vol) != 0) { LogErr("boot: AudioClient not reachable"); return false; }
        LogErr("boot: AudioClient connected, volume=" + std::to_string(static_cast<int>(vol)));

        whisper_context_params cparams = whisper_context_default_params();
        cparams.use_gpu = true;
        wctx_ = whisper_init_from_file_with_params(kWhisperModel, cparams);
        if (!wctx_ ) { LogErr("boot: whisper load failed"); return false; }
        LogErr("boot: whisper loaded on GPU");

        capture_ = std::thread(CaptureThread);
        return true;
    }

    void EmitCommandAccepted(CommandType command, const std::string& messageId,
                             const std::optional<std::string>& interactionId) {
        std::ostringstream payload;
        payload << "{\"command\":\"" << CommandTypeToWire(command)
                << "\",\"message_id\":\"" << JsonEscape(messageId) << "\"}";
        emitter_.Emit(EventType::kCommandAccepted, interactionId, payload.str());
    }

    void EmitFailed(const std::optional<std::string>& interactionId, const std::string& code,
                    const std::string& message) {
        std::ostringstream payload;
        payload << "{\"code\":\"" << JsonEscape(code) << "\",\"message\":\""
                << JsonEscape(message) << "\"}";
        emitter_.Emit(EventType::kFailed, interactionId, payload.str());
    }

    void EmitReady() {
        // Grounded physical capabilities: every flag corresponds to an implemented path.
        emitter_.Emit(EventType::kReady, std::nullopt,
            "{\"audio_capture\":true,\"wake_word\":true,\"vad\":true,\"stt\":true,"
            "\"local_llm\":true,\"spanish_tts\":true,\"physical_playback\":true,"
            "\"physical_playback_stop\":true,\"physical_playback_completion\":true}");
        heartbeat_.Start();
    }

    // Runs one full interaction on a dedicated thread; returns to ready afterward.
    void RunInteraction(const std::string& interactionId) {
        cancel_.store(false);
        active_id_ = interactionId;

        // 1. Wait for wake word, bounded by a generous window (supervisor timeout governs overall).
        LogErr("interaction " + interactionId + ": waiting for wake word");
        bool woke = false;
        for (int i = 0; i < 200 && !cancel_.load(); ++i) {   // ~ up to 200 * (3s cap) but chunk-gated
            auto chunk = TomarAudio(kCaptureSecs);
            if (chunk.empty()) { usleep(300000); continue; }
            if (CalcularRms(chunk) < kRmsThreshold) { usleep(200000); continue; }
            std::string texto = Transcribir(wctx_, chunk);
            if (texto.empty()) continue;
            LogErr("wake-listen STT: \"" + texto + "\"");
            if (EsWakeWord(texto)) { woke = true; break; }
        }
        if (cancel_.load()) { Finish(interactionId, /*cancelled=*/true); return; }
        if (!woke) {
            emitter_.Emit(EventType::kInteractionTimeout, interactionId,
                          "{\"reason\":\"no_wake_word\"}");
            Finish(interactionId, /*cancelled=*/false);
            return;
        }
        emitter_.Emit(EventType::kWakeWordConfirmed, std::nullopt, "{}");

        // Greeting.
        OttoSpeak("Hola! Soy OttoMan, el robot guia de UADE. En que te puedo ayudar?", cancel_);
        if (cancel_.load()) { Finish(interactionId, true); return; }

        // 2. Capture question.
        emitter_.Emit(EventType::kCaptureStarted, interactionId, "{}");
        ClearBuffer();
        auto utter = TomarUtterance(static_cast<float>(kRmsThreshold), cancel_, 700, 8000);
        if (cancel_.load()) { Finish(interactionId, true); return; }
        if (utter.empty()) {
            emitter_.Emit(EventType::kInteractionTimeout, interactionId,
                          "{\"reason\":\"no_question\"}");
            Finish(interactionId, false);
            return;
        }

        // 3. Transcribe.
        std::string pregunta = Transcribir(wctx_, utter);
        if (cancel_.load()) { Finish(interactionId, true); return; }
        {
            std::ostringstream pl;
            pl << "{\"text\":\"" << JsonEscape(pregunta) << "\"}";
            emitter_.Emit(EventType::kTranscriptReady, interactionId, pl.str());
        }
        if (pregunta.empty()) {
            EmitFailed(interactionId, "ERR_STT_EMPTY", "empty transcript");
            Finish(interactionId, false);
            return;
        }

        // 4. LLM.
        std::string respuesta = OllamaQuery(pregunta);
        if (cancel_.load()) { Finish(interactionId, true); return; }
        if (respuesta.empty()) {
            EmitFailed(interactionId, "ERR_LLM_EMPTY", "empty LLM response");
            Finish(interactionId, false);
            return;
        }
        {
            std::ostringstream pl;
            pl << "{\"text\":\"" << JsonEscape(respuesta) << "\"}";
            emitter_.Emit(EventType::kResponseReady, interactionId, pl.str());
        }

        // 5. TTS + physical playback.
        emitter_.Emit(EventType::kPlaybackStarted, interactionId, "{}");
        double dur = OttoSpeak(respuesta, cancel_);
        if (cancel_.load()) { Finish(interactionId, true); return; }
        if (dur < 0) {
            EmitFailed(interactionId, "ERR_TTS", "tts/playback failure");
            Finish(interactionId, false);
            return;
        }
        {
            std::ostringstream pl;
            pl << "{\"duration_s\":" << dur << "}";
            emitter_.Emit(EventType::kPlaybackCompleted, interactionId, pl.str());
        }
        Finish(interactionId, false);
    }

    void Finish(const std::string& interactionId, bool cancelled) {
        if (cancelled) {
            emitter_.Emit(EventType::kCancelled, interactionId, "{}");
        }
        active_id_.clear();
    }

    // Returns false when the process should exit (after stopped/closed).
    bool HandleLine(const std::string& line) {
        auto commandWire = ExtractStringField(line, "command");
        auto messageId = ExtractStringField(line, "message_id");
        auto interactionId = ExtractStringField(line, "interaction_id");
        if (!commandWire || !messageId) {
            EmitFailed(std::nullopt, "ERR_PROTOCOL_INVALID", "malformed command envelope");
            return true;
        }
        auto command = ParseCommand(*commandWire);
        if (!command) {
            EmitFailed(std::nullopt, "ERR_PROTOCOL_INVALID", "unknown command");
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
                    EmitFailed(std::nullopt, "ERR_IDENTIFIER", "activate requires interaction_id");
                    return true;
                }
                EmitCommandAccepted(*command, *messageId, interactionId);
                JoinInteraction();
                interaction_ = std::thread([this, id = *interactionId] { RunInteraction(id); });
                return true;
            }
            case CommandType::kStop:
                EmitCommandAccepted(*command, *messageId, interactionId);
                cancel_.store(true);
                if (g_audio) g_audio->PlayStop("otto");
                JoinInteraction();
                return true;
            case CommandType::kPause:
            case CommandType::kResume:
                EmitCommandAccepted(*command, *messageId, interactionId);
                return true;
            case CommandType::kEmergencyStop:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                cancel_.store(true);
                if (g_audio) g_audio->PlayStop("otto");   // audio stop ONLY; no locomotor command
                JoinInteraction();
                heartbeat_.Stop();
                emitter_.Emit(EventType::kStopped, std::nullopt, "{}");
                return false;
            case CommandType::kClose:
                EmitCommandAccepted(*command, *messageId, std::nullopt);
                cancel_.store(true);
                if (g_audio) g_audio->PlayStop("otto");
                JoinInteraction();
                heartbeat_.Stop();
                emitter_.Emit(EventType::kClosed, std::nullopt, "{}");
                return false;
        }
        return true;
    }

    void Shutdown() {
        g_running.store(false);
        JoinInteraction();
        heartbeat_.Stop();
        if (capture_.joinable()) capture_.join();
        if (wctx_) { whisper_free(wctx_); wctx_ = nullptr; }
    }

private:
    void JoinInteraction() {
        if (interaction_.joinable()) interaction_.join();
    }

    FrameEmitter& emitter_;
    HeartbeatTimer heartbeat_;
    // Heap-allocated so it is constructed ONLY after ChannelFactory::Init (a value member would be
    // constructed with PhysicalWorker in main(), before DDS init, and crash).
    std::unique_ptr<unitree::robot::g1::AudioClient> audio_client_;
    whisper_context* wctx_ = nullptr;
    std::thread capture_;
    std::thread interaction_;
    std::atomic<bool> cancel_{false};
    std::string active_id_;
};

}  // namespace

int main() {
    FrameEmitter emitter;
    PhysicalWorker worker(emitter);

    if (!worker.BootHardware()) {
        // Process-level failure before ready: supervisor treats a FAILED frame as unavailable.
        std::ostringstream payload;
        payload << "{\"code\":\"ERR_HARDWARE_INIT\",\"message\":\"physical audio stack init failed\"}";
        emitter.Emit(EventType::kFailed, std::nullopt, payload.str());
        return 1;
    }

    std::string line;
    while (std::getline(std::cin, line)) {
        if (line.empty()) continue;
        if (!worker.HandleLine(line)) break;
    }
    worker.Shutdown();
    return 0;
}
