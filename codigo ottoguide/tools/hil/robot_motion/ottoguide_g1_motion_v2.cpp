// ottoguide_g1_motion_v2.cpp
//
// ROBOT-R5F-R3B: v2 of the minimal, bounded C++ wrapper over the official Unitree G1 SDK
// (unitree::robot::g1::LocoClient), building on ROBOT-R5F-R2's ottoguide_g1_micro_motion.cpp.
//
// Key differences from v1 (R5F-R2):
//   - default mode is `status` (read-only), not `stop`;
//   - programmatic posture changes are rejected before SDK initialization;
//   - motion modes close with StopMove(), which preserves posture;
//   - added micro-yaw-return: a bounded positive-then-negative yaw pair to approximately
//     restore original heading.
//
// Modes:
//   --mode=status          (default) Read-only: GetFsmId/GetFsmMode/GetBalanceMode/
//                           GetStandHeight. No motion or SetVelocity.
//   --mode=passive-damp     Rejected before SDK initialization. Operator remote only.
//   --mode=velocity-stop    StopMove() only. Normal close of any velocity command, or an
//                           explicit safe-stop after an anomaly.
//   --mode=stand-up         Rejected before SDK initialization. Operator remote only.
//   --mode=balance-stand    Rejected before SDK initialization. Operator remote only.
//   --mode=micro-yaw        Bounded SetVelocity(0, 0, +omega, duration), sleep, StopMove().
//   --mode=micro-yaw-return Bounded SetVelocity(0,0,+omega,d1), StopMove(), sleep,
//                           SetVelocity(0,0,-omega,d2), StopMove().
//   --mode=linear-min       Bounded SetVelocity(vx, 0, 0, duration), sleep, StopMove().
//
// Hard safety bounds (not configurable via CLI, intentionally):
//   - duration capped at kMaxDurationS for every motion mode;
//   - omega/vx magnitude capped at conservative low values;
//   - every motion mode closes with StopMove() and preserves posture;
//   - a single SetVelocity call per motion leg, no loop, no retry.
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
constexpr float kMicroYawOmegaAbs = 0.08f;      // rad/s, conservative
constexpr float kMicroYawReturnLeg1S = 0.25f;   // s, first leg of the return pair
constexpr float kMicroYawReturnLeg2S = 0.25f;   // s, second leg of the return pair
constexpr float kLinearMinVxAbs = 0.05f;        // m/s, conservative
constexpr int kPostMotionSettleMs = 400;        // fixed settle sleep between legs/after motion

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
      "status",     "passive-damp",     "velocity-stop", "stand-up",
      "balance-stand", "micro-yaw", "micro-yaw-return", "linear-min",
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

  if (mode == "passive-damp" || mode == "stand-up" || mode == "balance-stand") {
    std::cerr << "PROGRAMMATIC_POSTURE_CHANGE_PROHIBITED_USE_OPERATOR_REMOTE" << std::endl;
    return 64;
  }

  Log("ottoguide_g1_motion_v2 starting, mode=" + mode +
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

  if (mode == "micro-yaw") {
    float omega = kMicroYawOmegaAbs;
    float duration = kMaxDurationS;
    Log("mode=micro-yaw: SetVelocity(vx=0, vy=0, omega=+" + std::to_string(omega) +
        ", duration=" + std::to_string(duration) + ")");
    int32_t ret = client.SetVelocity(0.f, 0.f, omega, duration);
    Log("SetVelocity() returned " + std::to_string(ret));
    SleepMs(kPostMotionSettleMs);
    Log("micro-yaw window elapsed, issuing StopMove() (normal close, not Damp).");
    int32_t stopRet = client.StopMove();
    Log("StopMove() returned " + std::to_string(stopRet));
    if (ret != 0) {
      std::cerr << "SetVelocity() failed with code " << ret << std::endl;
      return 7;
    }
    Log("micro-yaw mode complete, exit 0.");
    return 0;
  }

  if (mode == "micro-yaw-return") {
    float omega = kMicroYawOmegaAbs;
    Log("mode=micro-yaw-return: leg 1 SetVelocity(0,0,+" + std::to_string(omega) +
        "," + std::to_string(kMicroYawReturnLeg1S) + ")");
    int32_t ret1 = client.SetVelocity(0.f, 0.f, omega, kMicroYawReturnLeg1S);
    Log("SetVelocity() leg1 returned " + std::to_string(ret1));
    SleepMs(kPostMotionSettleMs);
    int32_t stopRet1 = client.StopMove();
    Log("StopMove() after leg1 returned " + std::to_string(stopRet1));

    SleepMs(kPostMotionSettleMs);

    Log("mode=micro-yaw-return: leg 2 SetVelocity(0,0,-" + std::to_string(omega) +
        "," + std::to_string(kMicroYawReturnLeg2S) + ")");
    int32_t ret2 = client.SetVelocity(0.f, 0.f, -omega, kMicroYawReturnLeg2S);
    Log("SetVelocity() leg2 returned " + std::to_string(ret2));
    SleepMs(kPostMotionSettleMs);
    int32_t stopRet2 = client.StopMove();
    Log("StopMove() after leg2 returned " + std::to_string(stopRet2));

    if (ret1 != 0 || ret2 != 0) {
      std::cerr << "SetVelocity() failed: leg1=" << ret1 << " leg2=" << ret2 << std::endl;
      return 8;
    }
    Log("micro-yaw-return mode complete, exit 0.");
    return 0;
  }

  if (mode == "linear-min") {
    float vx = kLinearMinVxAbs;
    float duration = kMaxDurationS;
    Log("mode=linear-min: SetVelocity(vx=+" + std::to_string(vx) +
        ", vy=0, omega=0, duration=" + std::to_string(duration) + ")");
    int32_t ret = client.SetVelocity(vx, 0.f, 0.f, duration);
    Log("SetVelocity() returned " + std::to_string(ret));
    SleepMs(kPostMotionSettleMs);
    Log("linear-min window elapsed, issuing StopMove() (normal close, not Damp).");
    int32_t stopRet = client.StopMove();
    Log("StopMove() returned " + std::to_string(stopRet));
    if (ret != 0) {
      std::cerr << "SetVelocity() failed with code " << ret << std::endl;
      return 9;
    }
    Log("linear-min mode complete, exit 0.");
    return 0;
  }

  return 1;
}
