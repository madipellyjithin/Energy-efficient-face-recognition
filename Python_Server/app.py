from __future__ import annotations

import atexit
import base64
import csv
import time
from collections import deque

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request

from config import settings
from esp32_client import Esp32ApiClient
from face_engine import OpenCvFaceEngine


app = Flask(__name__)

esp32 = Esp32ApiClient(
    base_url=settings.esp32_api_base_url,
    discovery_enabled=settings.esp32_discovery_enabled,
    mdns_service=settings.esp32_mdns_service,
    scan_timeout_seconds=settings.esp32_scan_timeout_seconds,
)
engine: OpenCvFaceEngine | None = None

event_log: deque[str] = deque(maxlen=100)
attendance_log: deque[dict[str, str]] = deque(maxlen=100)
last_seen_at: dict[str, float] = {}
last_esp_event_id = 0
motion_sequence = 0
motion_sessions: dict[int, dict] = {}

system_state = {
    "browser_camera_active": False,
    "detection_running": False,
    "esp_connected": False,
    "esp_url": "",
    "esp_test_ok": False,
    "registered_people": [],
    "last_result": None,
    "motion_sequence": 0,
    "last_motion_event": "",
    "pir_state": False,
}


def log_event(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    event_log.appendleft(f"[{timestamp}] {message}")


def refresh_registered_people() -> None:
    labels = [] if engine is None else engine.registered_labels()
    system_state["registered_people"] = labels


def write_attendance(label: str, score: float) -> None:
    settings.attendance_log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not settings.attendance_log_path.exists()
    with settings.attendance_log_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if is_new:
            writer.writerow(["timestamp", "name", "score"])
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), label, f"{score:.4f}"])


def mark_attendance(label: str, score: float) -> bool:
    now = time.time()
    last = last_seen_at.get(label, 0.0)
    if now - last < settings.attendance_cooldown_seconds:
        return False

    last_seen_at[label] = now
    entry = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "name": label,
        "score": f"{score:.4f}",
    }
    attendance_log.appendleft(entry)
    write_attendance(label, score)
    log_event(f"Attendance marked for {label}")
    return True


def refresh_esp_events() -> None:
    global last_esp_event_id, motion_sequence

    if not esp32.state.connected:
        return

    try:
        payload = esp32.get_events(last_esp_event_id)
    except Exception as exc:
        system_state["esp_connected"] = False
        log_event(f"ESP event poll failed: {exc}")
        return

    for event in payload.get("events", []):
        event_id = int(event.get("id", 0))
        if event_id > last_esp_event_id:
            last_esp_event_id = event_id
        name = event.get("name", "")
        detail = event.get("detail", "")
        log_event(f"ESP event: {name} {detail}".strip())
        if name == "MOTION_DETECTED" and system_state["detection_running"]:
            motion_sequence += 1
            system_state["motion_sequence"] = motion_sequence
            system_state["last_motion_event"] = time.strftime("%Y-%m-%d %H:%M:%S")
            motion_sessions[motion_sequence] = {
                "known_scores": {},
                "unknown_seen": False,
                "face_seen": False,
                "decision": "",
            }


def decode_frame_from_request() -> np.ndarray:
    payload = request.get_json(silent=True) or {}
    image_data = payload.get("image", "")
    if not image_data:
        raise ValueError("image is required")

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    raw = base64.b64decode(image_data)
    arr = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("invalid image data")
    return frame


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def api_status():
    refresh_esp_events()
    return jsonify(
        {
            **system_state,
            "event_log": list(event_log),
            "attendance_log": list(attendance_log),
            "last_esp_message": esp32.state.last_message,
        }
    )


@app.post("/api/browser-camera/start")
def api_browser_camera_start():
    system_state["browser_camera_active"] = True
    log_event("Browser camera started")
    return jsonify({"ok": True})


@app.post("/api/browser-camera/stop")
def api_browser_camera_stop():
    system_state["browser_camera_active"] = False
    system_state["detection_running"] = False
    log_event("Browser camera stopped")
    return jsonify({"ok": True})


@app.post("/api/register-face")
def api_register_face():
    label = (request.get_json(silent=True) or {}).get("label", "").strip()
    if not label:
        return jsonify({"ok": False, "error": "name is required"}), 400
    if engine is None:
        return jsonify({"ok": False, "error": "face engine not ready"}), 500

    try:
        frame = decode_frame_from_request()
        ok, detail = engine.register_face(label, frame)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if not ok:
        return jsonify({"ok": False, "error": detail}), 400

    refresh_registered_people()
    log_event(f"Face registered for {label}")
    return jsonify({"ok": True, "saved": detail, "registered_people": system_state["registered_people"]})


@app.post("/api/esp/connect")
def api_esp_connect():
    try:
        base_url = esp32.rediscover()
        status = esp32.get_status()
    except Exception as exc:
        system_state["esp_connected"] = False
        return jsonify({"ok": False, "error": str(exc)}), 500

    system_state["esp_connected"] = True
    system_state["esp_url"] = base_url
    system_state["esp_test_ok"] = bool(status.get("ok", False))
    system_state["last_motion_event"] = ""
    system_state["pir_state"] = bool(status.get("pirState", False))
    log_event(f"ESP connected at {base_url}")
    return jsonify({"ok": True, "esp_url": base_url, "status": status})


@app.post("/api/esp/test")
def api_esp_test():
    try:
        payload = esp32.send_command("PING")
        status = esp32.get_status()
    except Exception as exc:
        system_state["esp_test_ok"] = False
        system_state["esp_connected"] = False
        return jsonify({"ok": False, "error": str(exc)}), 500

    system_state["esp_connected"] = True
    system_state["esp_test_ok"] = True
    system_state["esp_url"] = esp32.state.base_url
    system_state["pir_state"] = bool(status.get("pirState", False))
    log_event("ESP test successful")
    return jsonify({"ok": True, "ping": payload, "status": status})


@app.post("/api/esp/hardware-test/<item>")
def api_esp_hardware_test(item: str):
    item = item.lower()
    commands = {
        "relay": "TEST_RELAY",
        "buzzer": "TEST_BUZZER",
        "green": "TEST_GREEN",
        "red": "TEST_RED",
        "pir": "TEST_PIR",
    }
    command = commands.get(item)
    if not command:
        return jsonify({"ok": False, "error": "unsupported test item"}), 400

    try:
        payload = esp32.send_command(command)
        status = esp32.get_status()
    except Exception as exc:
        system_state["esp_connected"] = False
        return jsonify({"ok": False, "error": str(exc)}), 500

    system_state["esp_connected"] = True
    system_state["esp_url"] = esp32.state.base_url
    system_state["pir_state"] = bool(status.get("pirState", False))
    log_event(f"ESP hardware test: {item}")
    return jsonify({"ok": True, "command": command, "response": payload, "status": status})


@app.post("/api/detection/start")
def api_detection_start():
    system_state["detection_running"] = True
    log_event("Detection started")
    return jsonify({"ok": True})


@app.post("/api/detection/stop")
def api_detection_stop():
    system_state["detection_running"] = False
    log_event("Detection stopped")
    return jsonify({"ok": True})


@app.post("/api/detect-frame")
def api_detect_frame():
    if engine is None:
        return jsonify({"ok": False, "error": "face engine not ready"}), 500

    try:
        frame = decode_frame_from_request()
        payload = request.get_json(silent=True) or {}
        analysis = engine.recognize_all(frame)
        seq = int(payload.get("motion_sequence", 0))
        is_final = bool(payload.get("final", False))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if seq not in motion_sessions:
        motion_sessions[seq] = {
            "known_scores": {},
            "unknown_seen": False,
            "face_seen": False,
            "decision": "",
        }
    session = motion_sessions[seq]
    session["face_seen"] = session["face_seen"] or analysis.face_count > 0
    session["unknown_seen"] = session["unknown_seen"] or analysis.unknown_count > 0
    for face in analysis.faces:
        if face.matched:
            best = float(session["known_scores"].get(face.label, 0.0))
            if face.score > best:
                session["known_scores"][face.label] = face.score

    if session["known_scores"] and session["decision"] != "unlock":
        session["decision"] = "unlock"
        if esp32.state.connected:
            try:
                esp32.send_command("UNLOCK")
                log_event("ESP unlock sent for known person")
            except Exception as exc:
                log_event(f"ESP command failed: {exc}")

    if is_final and session["decision"] != "unlock" and session["unknown_seen"]:
        session["decision"] = "alert"
        if esp32.state.connected:
            try:
                esp32.send_command("ALERT")
                log_event("ESP alert sent for unknown person")
            except Exception as exc:
                log_event(f"ESP command failed: {exc}")

    if is_final and session["known_scores"]:
        for label, score in session["known_scores"].items():
            mark_attendance(label, float(score))

    response = {
        "ok": True,
        "matched": bool(session["known_scores"]),
        "labels": sorted(session["known_scores"].keys()),
        "face_count": analysis.face_count,
        "unknown_count": analysis.unknown_count,
        "details": analysis.details,
        "decision": session["decision"] or "pending",
    }

    system_state["last_result"] = response

    return jsonify(response)


def startup() -> None:
    global engine

    missing = [path for path in (settings.detector_model_path, settings.recognizer_model_path) if not path.exists()]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Model file not found: {joined}")

    settings.known_faces_dir.mkdir(parents=True, exist_ok=True)
    engine = OpenCvFaceEngine(
        settings.detector_model_path,
        settings.recognizer_model_path,
        settings.known_faces_dir,
        settings.match_threshold,
        settings.frame_width,
        settings.frame_height,
    )
    engine.load_known_faces()
    refresh_registered_people()
    log_event("Attendance app ready")


def shutdown() -> None:
    return


atexit.register(shutdown)


if __name__ == "__main__":
    startup()
    app.run(host="0.0.0.0", port=5000, debug=False)
