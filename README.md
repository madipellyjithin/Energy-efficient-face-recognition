# Split Face Recognition System

This folder contains a practical implementation for your current hardware:

- `ESP32 DevKit V1` handles PIR, relay, buzzer, LEDs, and a Wi-Fi API
- laptop runs the camera, face engine, and web interface

This design keeps the ESP32 lightweight and reliable while letting the laptop run the heavier face recognition model.

## Folder Layout

- `esp32_firmware/`: Arduino sketch for the ESP32
- `python_server/`: Python app with ONNX inference, serial bridge, and web UI

## Runtime Flow

1. PIR goes high on the ESP32.
2. ESP32 records the event in its local API.
3. Python app auto-discovers the ESP32 and polls its event queue.
4. Python captures a frame from the laptop camera.
5. Python runs YuNet face detection and SFace face recognition.
6. Python decides:
   - `UNLOCK` for authorized user
   - `ALERT` for unknown person
7. Python sends the command to the ESP32 HTTP API.
8. ESP32 controls relay, buzzer, and LEDs.

## What You Need

### ESP32 side

- Arduino IDE
- your `ESP32 DevKit V1`
- PIR sensor
- relay
- buzzer
- status LEDs

### Laptop side

- Python 3.10+
- webcam
- OpenCV YuNet + SFace models

## Python Dependencies

Install:

```bash
pip install -r python_server/requirements.txt
```

## Quick Start

1. Edit Wi-Fi credentials inside [face_bridge.ino](d:\energy_efficient\split_face_system\esp32_firmware\face_bridge.ino).
2. Flash [face_bridge.ino](d:\energy_efficient\split_face_system\esp32_firmware\face_bridge.ino) to the ESP32.
3. Copy [python_server/.env.example](d:\energy_efficient\split_face_system\python_server\.env.example) to `.env` and adjust if needed.
4. Add reference face images under `python_server/data/known_faces/<person_name>/`.
5. Run:

```bash
python python_server/app.py
```

6. Open `http://127.0.0.1:5000`.

## Models Used

The Python app is already wired to these models:

- `face_detection_yunet_2023mar.onnx`
- `face_recognition_sface_2021dec.onnx`

The recognition logic is implemented in [face_engine.py](d:\energy_efficient\split_face_system\python_server\face_engine.py).

## ESP32 API

The ESP32 exposes:

- `GET /api/status`
- `GET /api/events?since=<id>`
- `POST /api/control`

The Python app auto-discovers the ESP32 using:

- mDNS service `_edgeface._tcp.local.`
- fallback local subnet scan against `/api/status`

This means you usually do not need to hardcode the board IP.
