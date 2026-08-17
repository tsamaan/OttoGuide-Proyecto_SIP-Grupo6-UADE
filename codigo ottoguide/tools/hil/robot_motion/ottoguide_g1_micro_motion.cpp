// ottoguide_g1_micro_motion.cpp
//
// ROBOT-R5F-R2: minimal, bounded C++ wrapper over the official Unitree G1 SDK
// (unitree::robot::g1::LocoClient) for supervised micro-motion testing.
//
// Modes:
//   --mode stop         StopMove() only. Never changes posture. Default mode.
//   --mode micro-yaw    Bounded SetVelocity(0, 0, omega, duration) then StopMove().
//   --mode linear-min   Bounded SetVelocity(vx, 0, 0, duration) then StopMove().
//
// Hard safety bounds (not configurable via CLI, intentionally):
//   - duration capped at kMaxDurationS for every motion mode;
//   - omega/vx magnitude capped at conservative low values;
//   - every motion mode always calls StopMove() immediately afterward;
//   - a single SetVelocity call per invocation, no loop, no retry.
//
// Does not touch ROS2, ottoguide production Python, or otto_pipeline.cpp.

#include <chrono>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>

#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/loco/g1_loco_client.hpp>

namespace {

constexpr float kMaxDurationS = 0.30f;
constexpr float kMicroYawOmegaAbs = 0.08f;   // rad/s, conservative
constexpr float kLinearMinVxAbs = 0.05f;     // m/s, conservative

std::string NowIso() {
  auto now = std::chrono::system_clock::now();
  auto t = std::chrono::system_clock::to_time_t(now);
  char buf[32];
  std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", std::gmtime(&t));
  return std::string(buf);
}

void Log(const std::string& msg) {
  std::cout << "[" << NowIso() << "] " << msg << std::endl;
}

}  // namespace

int main(int argc, char** argv) {
  std::string mode = "stop";
  std::string networkInterface = "lo";

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg.rfind("--mode=", 0) == 0) {
      mode = arg.substr(std::string("--mode=").size());
    } else if (arg == "--mode" && i + 1 < argc) {
      mode = argv[++i];
    } else if (arg.rfind("--network_interface=", 0) == 0) {
      networkInterface = arg.substr(std::string("--network_interface=").size());
    }
  }

  if (mode != "stop" && mode != "micro-yaw" && mode != "linear-min") {
    std::cerr << "Unknown --mode: " << mode
              << " (expected stop|micro-yaw|linear-min)" << std::endl;
    return 1;
  }

  Log("ottoguide_g1_micro_motion starting, mode=" + mode +
      ", network_interface=" + networkInterface);

  try {
    unitree::robot::ChannelFactory::Instance()->Init(0, networkInterface);
  } catch (const std::exception& e) {
    std::cerr << "ChannelFactory::Init failed: " << e.what() << std::endl;
    return 2;
  }

  unitree::robot::g1::LocoClient client;
  client.Init();
  client.SetTimeout(10.f);

  Log("LocoClient initialized.");

  if (mode == "stop") {
    Log("mode=stop: calling StopMove() only, preserving posture.");
    int32_t ret = client.StopMove();
    Log("StopMove() returned " + std::to_string(ret));
    if (ret != 0) {
      std::cerr << "StopMove() failed with code " << ret << std::endl;
      return 3;
    }
    Log("stop mode complete, exit 0.");
    return 0;
  }

  if (mode == "micro-yaw") {
    float omega = kMicroYawOmegaAbs;
    float duration = kMaxDurationS;
    Log("mode=micro-yaw: SetVelocity(vx=0, vy=0, omega=" +
        std::to_string(omega) + ", duration=" + std::to_string(duration) +
        ")");
    int32_t ret = client.SetVelocity(0.f, 0.f, omega, duration);
    Log("SetVelocity() returned " + std::to_string(ret));
    // SetVelocity's duration is enforced by the robot's own controller;
    // this wrapper does not sleep or loop while it executes.
    std::this_thread::sleep_for(
        std::chrono::milliseconds(static_cast<int>(duration * 1000) + 100));
    Log("micro-yaw window elapsed, issuing StopMove() to preserve posture.");
    int32_t stopRet = client.StopMove();
    Log("StopMove() returned " + std::to_string(stopRet));
    if (ret != 0) {
      std::cerr << "SetVelocity() failed with code " << ret << std::endl;
      return 4;
    }
    Log("micro-yaw mode complete, exit 0.");
    return 0;
  }

  if (mode == "linear-min") {
    float vx = kLinearMinVxAbs;
    float duration = kMaxDurationS;
    Log("mode=linear-min: SetVelocity(vx=" + std::to_string(vx) +
        ", vy=0, omega=0, duration=" + std::to_string(duration) + ")");
    int32_t ret = client.SetVelocity(vx, 0.f, 0.f, duration);
    Log("SetVelocity() returned " + std::to_string(ret));
    std::this_thread::sleep_for(
        std::chrono::milliseconds(static_cast<int>(duration * 1000) + 100));
    Log("linear-min window elapsed, issuing StopMove() to preserve posture.");
    int32_t stopRet = client.StopMove();
    Log("StopMove() returned " + std::to_string(stopRet));
    if (ret != 0) {
      std::cerr << "SetVelocity() failed with code " << ret << std::endl;
      return 5;
    }
    Log("linear-min mode complete, exit 0.");
    return 0;
  }

  return 1;
}
