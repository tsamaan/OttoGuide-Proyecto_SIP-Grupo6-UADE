# Robot Python 3.10 backend runtime

## Validated robot environment

- Robot: Unitree G1 EDU
- OS: Ubuntu 20.04 aarch64
- Branch: review/orchestrator-unification
- Validated base commit: 92a8bc45a7a8d7557bcdca9ae5684692016168a7
- Python: /home/unitree/.local/ottoguide-miniforge/envs/ottoguide-py310/bin/python
- Python version: 3.10.20

## Installation summary

Miniforge user-space path:

/home/unitree/.local/ottoguide-miniforge

Conda environment:

ottoguide-py310

No sudo or apt required.

## Runtime dependencies validated

The mock/stub backend was validated with:

- fastapi
- uvicorn[standard]
- pydantic-settings
- httpx
- numpy
- python-statemachine
- pyttsx3
- SpeechRecognition
- aiohttp
- opencv-python-headless

## Safe mock/stub launch

Use only mock/stub mode for web validation:

```bash
cd "/home/unitree/Desktop/Ottoguide/OttoGuide-unification/codigo ottoguide"

env -u RMW_IMPLEMENTATION -u CYCLONEDDS_URI -u ROBOT_NETWORK_INTERFACE \
  ROBOT_MODE=mock \
  NAVIGATION_BACKEND=stub \
  NAVIGATION_ALLOW_STUB_TOURS=false \
  QR_STATION_TRIGGER_ENABLED=false \
  WEB_UI_ALLOWED_ORIGINS="http://localhost:3001,http://127.0.0.1:3001,http://192.168.123.101:3001" \
  WEB_UI_ALLOW_MISSING_ORIGIN=true \
  API_PORT=8000 \
  /home/unitree/.local/ottoguide-miniforge/envs/ottoguide-py310/bin/python main.py
```

## Validated endpoints

- GET /status
- GET /content/script
- GET /ws/telemetry handshake

## Safety constraints

This validation does not start ROS, DDS, Unitree SDK, navigation, or motion.

Do not use start_robot.sh for this mock/stub backend validation.

## Shutdown note

In ENV-R2, SIGINT/SIGTERM sent to the timeout wrapper did not stop the child process quickly enough. Future operators should identify and signal the actual Python child process if the wrapper does not exit, and always verify that port 8000 is closed.
