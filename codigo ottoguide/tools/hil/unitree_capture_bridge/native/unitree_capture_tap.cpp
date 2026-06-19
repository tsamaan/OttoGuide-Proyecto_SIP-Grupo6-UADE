#define _GNU_SOURCE
#include <sys/uio.h>

#include <array>
#include <atomic>
#include <chrono>
#include <cinttypes>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <string>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/idl/hg/IMUState_.hpp>
#include <unitree/idl/hg/LowState_.hpp>
#include <unitree/idl/hg/SportModeState_.hpp>
#include <unitree/dds_wrapper/common/unitree_joystick.hpp>

using namespace unitree::robot;
using namespace unitree_hg::msg::dds_;

namespace {

constexpr const char* kSocketPath = "/tmp/ottoguide_unitree_capture.sock";
constexpr std::size_t kBufferSize = 1024;

std::atomic_bool running{true};
int socket_fd = -1;
sockaddr_un destination{};

struct Counters {
    std::atomic_uint64_t lowstate{0};
    std::atomic_uint64_t optional_lowstate{0};
    std::atomic_uint64_t secondary_imu{0};
    std::atomic_uint64_t sport_state{0};
    std::atomic_uint64_t ipc_sent{0};
    std::atomic_uint64_t ipc_drops{0};
    uint64_t start_ns{0};
};

Counters counters;

uint64_t monotonic_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<uint64_t>(ts.tv_sec) * 1000000000ULL +
           static_cast<uint64_t>(ts.tv_nsec);
}

void signal_handler(int) {
    running.store(false, std::memory_order_relaxed);
}

struct RateLimiter {
    explicit RateLimiter(uint64_t period) : period_ns(period) {}

    bool allow(uint64_t now) {
        uint64_t previous = last_ns.load(std::memory_order_relaxed);
        while (now - previous >= period_ns) {
            if (last_ns.compare_exchange_weak(
                    previous, now, std::memory_order_relaxed)) {
                return true;
            }
        }
        return false;
    }

    const uint64_t period_ns;
    std::atomic_uint64_t last_ns{0};
};

RateLimiter lowstate_rate{1000000000ULL / 50};
RateLimiter secondary_imu_rate{1000000000ULL / 100};
RateLimiter sport_rate{1000000000ULL / 10};
RateLimiter health_rate{1000000000ULL};

bool initialize_ipc() {
    socket_fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    if (socket_fd < 0) {
        std::perror("[tap] socket");
        return false;
    }
    destination.sun_family = AF_UNIX;
    std::strncpy(destination.sun_path, kSocketPath,
                 sizeof(destination.sun_path) - 1);
    return true;
}

void send_datagram(const char* data, std::size_t length) {
    if (socket_fd < 0 || length == 0 || length >= kBufferSize) {
        counters.ipc_drops.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    const ssize_t sent = sendto(
        socket_fd, data, length, MSG_DONTWAIT,
        reinterpret_cast<const sockaddr*>(&destination), sizeof(destination));
    if (sent == static_cast<ssize_t>(length)) {
        counters.ipc_sent.fetch_add(1, std::memory_order_relaxed);
    } else {
        counters.ipc_drops.fetch_add(1, std::memory_order_relaxed);
    }
}

template <typename... Args>
void format_and_send(const char* format, Args... args) {
    std::array<char, kBufferSize> buffer{};
    const int length = std::snprintf(buffer.data(), buffer.size(), format, args...);
    if (length <= 0 || static_cast<std::size_t>(length) >= buffer.size()) {
        counters.ipc_drops.fetch_add(1, std::memory_order_relaxed);
        return;
    }
    send_datagram(buffer.data(), static_cast<std::size_t>(length));
}

struct RemoteState {
    float lx{0.0F};
    float ly{0.0F};
    float rx{0.0F};
    float ry{0.0F};
    uint16_t buttons{0};
};

RemoteState decode_remote(const std::array<uint8_t, 40>& bytes) {
    static_assert(sizeof(unitree::common::REMOTE_DATA_RX) == 40,
                  "Unexpected Unitree remote layout");
    unitree::common::REMOTE_DATA_RX remote{};
    std::memcpy(remote.buff, bytes.data(), sizeof(remote.buff));
    return {
        remote.RF_RX.lx,
        remote.RF_RX.ly,
        remote.RF_RX.rx,
        remote.RF_RX.ry,
        remote.RF_RX.btn.value,
    };
}

void emit_lowstate(uint64_t receipt_ns, const LowState_& state) {
    if (!lowstate_rate.allow(receipt_ns)) return;
    const auto remote = decode_remote(state.wireless_remote());
    const auto& imu = state.imu_state();
    format_and_send(
        "{\"v\":1,\"k\":\"lowstate\",\"t\":%" PRIu64
        ",\"ch\":\"rt/lowstate\",\"tick\":%u,\"mm\":%u"
        ",\"lx\":%.6f,\"ly\":%.6f,\"rx\":%.6f,\"ry\":%.6f,\"keys\":%u"
        ",\"q\":[%.7f,%.7f,%.7f,%.7f]"
        ",\"g\":[%.7f,%.7f,%.7f]"
        ",\"a\":[%.7f,%.7f,%.7f]"
        ",\"rpy\":[%.7f,%.7f,%.7f]}",
        receipt_ns, state.tick(), static_cast<unsigned>(state.mode_machine()),
        remote.lx, remote.ly, remote.rx, remote.ry,
        static_cast<unsigned>(remote.buttons),
        imu.quaternion()[0], imu.quaternion()[1],
        imu.quaternion()[2], imu.quaternion()[3],
        imu.gyroscope()[0], imu.gyroscope()[1], imu.gyroscope()[2],
        imu.accelerometer()[0], imu.accelerometer()[1], imu.accelerometer()[2],
        imu.rpy()[0], imu.rpy()[1], imu.rpy()[2]);
}

void emit_secondary_imu(uint64_t receipt_ns, const IMUState_& imu) {
    if (!secondary_imu_rate.allow(receipt_ns)) return;
    format_and_send(
        "{\"v\":1,\"k\":\"secondary_imu\",\"t\":%" PRIu64
        ",\"q\":[%.7f,%.7f,%.7f,%.7f]"
        ",\"g\":[%.7f,%.7f,%.7f]"
        ",\"a\":[%.7f,%.7f,%.7f]"
        ",\"rpy\":[%.7f,%.7f,%.7f]}",
        receipt_ns,
        imu.quaternion()[0], imu.quaternion()[1],
        imu.quaternion()[2], imu.quaternion()[3],
        imu.gyroscope()[0], imu.gyroscope()[1], imu.gyroscope()[2],
        imu.accelerometer()[0], imu.accelerometer()[1], imu.accelerometer()[2],
        imu.rpy()[0], imu.rpy()[1], imu.rpy()[2]);
}

void emit_sport_state(uint64_t receipt_ns, const SportModeState_& state) {
    if (!sport_rate.allow(receipt_ns)) return;
    format_and_send(
        "{\"v\":1,\"k\":\"sport_state\",\"t\":%" PRIu64
        ",\"fsm\":%u}",
        receipt_ns, state.fsm_mode());
}

void emit_health(uint64_t now) {
    if (!health_rate.allow(now)) return;
    format_and_send(
        "{\"v\":1,\"k\":\"health\",\"t\":%" PRIu64
        ",\"up\":%.3f,\"n_ls\":%" PRIu64
        ",\"n_lf_ls\":%" PRIu64 ",\"n_simu\":%" PRIu64
        ",\"n_sport\":%" PRIu64 ",\"n_sent\":%" PRIu64
        ",\"n_drop\":%" PRIu64 "}",
        now, (now - counters.start_ns) / 1e9,
        counters.lowstate.load(), counters.optional_lowstate.load(),
        counters.secondary_imu.load(), counters.sport_state.load(),
        counters.ipc_sent.load(), counters.ipc_drops.load());
}

}  // namespace

int main(int argc, char* argv[]) {
    const std::string network_interface = argc >= 2 ? argv[1] : "eth0";
    const int domain = argc >= 3 ? std::stoi(argv[2]) : 0;
    if (domain != 0) {
        std::fprintf(stderr, "[tap] domain must be 0\n");
        return 2;
    }

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);
    if (!initialize_ipc()) return 3;
    counters.start_ns = monotonic_ns();

    ChannelFactory::Instance()->Init(domain, network_interface);
    auto lowstate = ChannelFactory::Instance()->CreateRecvChannel<LowState_>(
        "rt/lowstate", [](const void* message) {
            counters.lowstate.fetch_add(1, std::memory_order_relaxed);
            emit_lowstate(monotonic_ns(), *static_cast<const LowState_*>(message));
        });
    auto optional_lowstate = ChannelFactory::Instance()->CreateRecvChannel<LowState_>(
        "rt/lf/lowstate", [](const void*) {
            counters.optional_lowstate.fetch_add(1, std::memory_order_relaxed);
        });
    auto secondary_imu = ChannelFactory::Instance()->CreateRecvChannel<IMUState_>(
        "rt/secondary_imu", [](const void* message) {
            counters.secondary_imu.fetch_add(1, std::memory_order_relaxed);
            emit_secondary_imu(monotonic_ns(), *static_cast<const IMUState_*>(message));
        });
    auto sport_state = ChannelFactory::Instance()->CreateRecvChannel<SportModeState_>(
        "rt/sportmodestate", [](const void* message) {
            counters.sport_state.fetch_add(1, std::memory_order_relaxed);
            emit_sport_state(monotonic_ns(), *static_cast<const SportModeState_*>(message));
        });

    std::printf("[tap] receive-only capture active on %s domain 0\n",
                network_interface.c_str());
    while (running.load(std::memory_order_relaxed)) {
        emit_health(monotonic_ns());
        usleep(100000);
    }

    std::printf(
        "[tap] stopped ls=%" PRIu64 " lf=%" PRIu64
        " secondary=%" PRIu64 " sport=%" PRIu64
        " sent=%" PRIu64 " drops=%" PRIu64 "\n",
        counters.lowstate.load(), counters.optional_lowstate.load(),
        counters.secondary_imu.load(), counters.sport_state.load(),
        counters.ipc_sent.load(), counters.ipc_drops.load());
    if (socket_fd >= 0) close(socket_fd);
    return 0;
}
