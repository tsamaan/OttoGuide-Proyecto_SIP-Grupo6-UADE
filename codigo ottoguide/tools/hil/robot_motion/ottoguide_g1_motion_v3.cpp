// ottoguide_g1_motion_v3.cpp
//
// ROBOT-R5F-R3C: v3 of the minimal, bounded C++ wrapper over the official Unitree G1 SDK
// (unitree::robot::g1::LocoClient), building on ROBOT-R5F-R3B's ottoguide_g1_motion_v2.cpp.
//
// Purpose: v2's micro-yaw (0.08 rad/s, 0.30s) and linear-min (0.05 m/s, 0.30s) both returned
// API success but produced no visually confirmable displacement. v3 replaces those two modes
// with a calibrated ladder of named, hardcoded profiles (yaw-l1/l2/l3, linear-l1/l2/l3) plus
// an optional yaw-return pair, so magnitude/duration can be escalated step by step under
// separate operator confirmation at each level, instead of guessing a single larger value.
//
// Preserved from v2, unchanged:
//   - default mode is `status` (read-only);
//   - Damp() is isolated to its own explicit `passive-damp` mode -- never called implicitly
//     as prep or as the normal close of a motion command;
//   - every motion mode closes with StopMove(), never Damp();
//   - no freeform vx/omega/duration via CLI -- named profiles only, hardcoded.
//
// Modes:
//   --mode=status           (default) Read-only: GetFsmId/GetFsmMode/GetBalanceMode/
//                            GetStandHeight. No motion, no Damp, no SetVelocity.
//   --mode=passive-damp      Damp() only. Explicit passive/emergency mode.
//   --mode=velocity-stop     StopMove() only. Normal close of any velocity command, or an
//                            explicit safe-stop after an anomaly.
//   --mode=yaw-l1            SetVelocity(0,0,+0.20, 0.50s), sleep, StopMove().
//   --mode=yaw-l2            SetVelocity(0,0,+0.30, 0.60s), sleep, StopMove().
//   --mode=yaw-l3            SetVelocity(0,0,+0.45, 0.60s), sleep, StopMove().
//   --mode=yaw-return-l1     +0.20/0.50s, StopMove(), sleep, -0.20/0.50s, StopMove().
//   --mode=yaw-return-l2     +0.30/0.60s, StopMove(), sleep, -0.30/0.60s, StopMove().
//   --mode=linear-l1         SetVelocity(+0.10,0,0, 0.50s), sleep, StopMove().
//   --mode=linear-l2         SetVelocity(+0.20,0,0, 0.60s), sleep, StopMove().
//   --mode=linear-l3         SetVelocity(+0.30,0,0, 0.60s), sleep, StopMove().
//
// Hard safety bounds (not configurable via CLI, intentionally):
//   - every profile's vx/omega/duration is a hardcoded constant, selected only by --mode;
//   - highest profile in this wrapper is linear-l3 (0.30 m/s) / yaw-l3 (0.45 rad/s) -- no
//     mode accepts a value above these;
//   - every motion mode closes with StopMove(), never Damp();
//   - a single SetVelocity call per motion leg (two for the return pair), no loop, no retry.
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

// yaw profiles: omega (rad/s), duration (s)
constexpr float kYawL1Omega = 0.20f;
constexpr float kYawL1DurationS = 0.50f;
constexpr float kYawL2Omega = 0.30f;
constexpr float kYawL2DurationS = 0.60f;
constexpr float kYawL3Omega = 0.45f;
constexpr float kYawL3DurationS = 0.60f;

// linear profiles: vx (m/s), duration (s)
constexpr float kLinearL1Vx = 0.10f;
constexpr float kLinearL1DurationS = 0.50f;
constexpr float kLinearL2Vx = 0.20f;
constexpr float kLinearL2DurationS = 0.60f;
constexpr float kLinearL3Vx = 0.30f;
constexpr float kLinearL3DurationS = 0.60f;

constexpr int kPostMotionSettleMs = 400;  // fixed settle sleep between legs/after motion

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

void SleepMs(int ms) {
  std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}

// Runs one SetVelocity leg followed by the mandatory StopMove() close (never Damp()).
// Returns true if both calls returned 0.
bool RunVelocityLeg(unitree::robot::g1::LocoClient& client, float vx, float vy, float omega,
                     float duration, const std::string& label) {
  Log(label + ": SetVelocity(vx=" + std::to_string(vx) + ", vy=" + std::to_string(vy) +
      ", omega=" + std::to_string(omega) + ", duration=" + std::to_string(duration) + ")");
  int32_t ret = client.SetVelocity(vx, vy, omega, duration);
  Log(label + ": SetVelocity() returned " + std::to_string(ret));
  SleepMs(kPostMotionSettleMs);
  Log(label + ": window elapsed, issuing StopMove() (normal close, not Damp).");
  int32_t stopRet = client.StopMove();
  Log(label + ": StopMove() returned " + std::to_string(stopRet));
  return ret == 0 && stopRet == 0;
}

}  // namespace

int main(int argc, char** argv) {
  std::string mode = "status";
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

  static const std::string kValidModes[] = {
      "status",     "passive-damp", "velocity-stop",
      "yaw-l1",     "yaw-l2",       "yaw-l3",
      "yaw-return-l1", "yaw-return-l2",
      "linear-l1",  "linear-l2",    "linear-l3",
  };
  bool validMode = false;
  for (const auto& m : kValidModes) {
    if (mode == m) {
      validMode = true;
      break;
    }
  }
  if (!validMode) {
    std::cerr << "Unknown --mode: " << mode << std::endl;
    return 1;
  }

  Log("ottoguide_g1_motion_v3 starting, mode=" + mode +
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

  if (mode == "status") {
    Log("mode=status: read-only FSM/balance/stand-height queries. No motion, no Damp, no "
        "SetVelocity.");
    int fsmId = -1;
    int32_t retFsmId = client.GetFsmId(fsmId);
    Log("GetFsmId() returned " + std::to_string(retFsmId) + ", fsm_id=" +
        std::to_string(fsmId));

    int fsmMode = -1;
    int32_t retFsmMode = client.GetFsmMode(fsmMode);
    Log("GetFsmMode() returned " + std::to_string(retFsmMode) + ", fsm_mode=" +
        std::to_string(fsmMode));

    int balanceMode = -1;
    int32_t retBalanceMode = client.GetBalanceMode(balanceMode);
    Log("GetBalanceMode() returned " + std::to_string(retBalanceMode) + ", balance_mode=" +
        std::to_string(balanceMode));

    float standHeight = -1.f;
    int32_t retStandHeight = client.GetStandHeight(standHeight);
    Log("GetStandHeight() returned " + std::to_string(retStandHeight) + ", stand_height=" +
        std::to_string(standHeight));

    Log("status mode complete, exit 0.");
    return 0;
  }

  if (mode == "passive-damp") {
    Log("mode=passive-damp: explicit passive mode, calling Damp() only. This is NOT used as "
        "prep or as the normal close of any motion mode in this wrapper.");
    int32_t ret = client.Damp();
    Log("Damp() returned " + std::to_string(ret));
    if (ret != 0) {
      std::cerr << "Damp() failed with code " << ret << std::endl;
      return 3;
    }
    Log("passive-damp mode complete, exit 0.");
    return 0;
  }

  if (mode == "velocity-stop") {
    Log("mode=velocity-stop: calling StopMove() only. Normal close / safe-stop mode. Damp() "
        "is NOT called.");
    int32_t ret = client.StopMove();
    Log("StopMove() returned " + std::to_string(ret));
    if (ret != 0) {
      std::cerr << "StopMove() failed with code " << ret << std::endl;
      return 4;
    }
    Log("velocity-stop mode complete, exit 0.");
    return 0;
  }

  if (mode == "yaw-l1") {
    bool ok = RunVelocityLeg(client, 0.f, 0.f, kYawL1Omega, kYawL1DurationS, "yaw-l1");
    if (!ok) return 7;
    Log("yaw-l1 mode complete, exit 0.");
    return 0;
  }

  if (mode == "yaw-l2") {
    bool ok = RunVelocityLeg(client, 0.f, 0.f, kYawL2Omega, kYawL2DurationS, "yaw-l2");
    if (!ok) return 7;
    Log("yaw-l2 mode complete, exit 0.");
    return 0;
  }

  if (mode == "yaw-l3") {
    bool ok = RunVelocityLeg(client, 0.f, 0.f, kYawL3Omega, kYawL3DurationS, "yaw-l3");
    if (!ok) return 7;
    Log("yaw-l3 mode complete, exit 0.");
    return 0;
  }

  if (mode == "yaw-return-l1") {
    bool ok1 = RunVelocityLeg(client, 0.f, 0.f, kYawL1Omega, kYawL1DurationS,
                               "yaw-return-l1 leg1");
    SleepMs(kPostMotionSettleMs);
    bool ok2 = RunVelocityLeg(client, 0.f, 0.f, -kYawL1Omega, kYawL1DurationS,
                               "yaw-return-l1 leg2");
    if (!ok1 || !ok2) return 8;
    Log("yaw-return-l1 mode complete, exit 0.");
    return 0;
  }

  if (mode == "yaw-return-l2") {
    bool ok1 = RunVelocityLeg(client, 0.f, 0.f, kYawL2Omega, kYawL2DurationS,
                               "yaw-return-l2 leg1");
    SleepMs(kPostMotionSettleMs);
    bool ok2 = RunVelocityLeg(client, 0.f, 0.f, -kYawL2Omega, kYawL2DurationS,
                               "yaw-return-l2 leg2");
    if (!ok1 || !ok2) return 8;
    Log("yaw-return-l2 mode complete, exit 0.");
    return 0;
  }

  if (mode == "linear-l1") {
    bool ok = RunVelocityLeg(client, kLinearL1Vx, 0.f, 0.f, kLinearL1DurationS, "linear-l1");
    if (!ok) return 9;
    Log("linear-l1 mode complete, exit 0.");
    return 0;
  }

  if (mode == "linear-l2") {
    bool ok = RunVelocityLeg(client, kLinearL2Vx, 0.f, 0.f, kLinearL2DurationS, "linear-l2");
    if (!ok) return 9;
    Log("linear-l2 mode complete, exit 0.");
    return 0;
  }

  if (mode == "linear-l3") {
    bool ok = RunVelocityLeg(client, kLinearL3Vx, 0.f, 0.f, kLinearL3DurationS, "linear-l3");
    if (!ok) return 9;
    Log("linear-l3 mode complete, exit 0.");
    return 0;
  }

  return 1;
}
