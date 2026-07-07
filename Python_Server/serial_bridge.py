from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

import serial


@dataclass
class SerialState:
    connected: bool = False
    last_message: str = ""
    history: list[str] = field(default_factory=list)


class Esp32SerialBridge:
    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.serial_conn: serial.Serial | None = None
        self.state = SerialState()
        self.events: "queue.Queue[str]" = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def connect(self) -> None:
        self.serial_conn = serial.Serial(self.port, self.baudrate, timeout=1)
        self.state.connected = True
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def close(self) -> None:
        self._running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        self.state.connected = False

    def send(self, command: str) -> None:
        with self._lock:
            if not self.serial_conn or not self.serial_conn.is_open:
                raise RuntimeError("ESP32 serial connection is not open")
            self.serial_conn.write((command.strip() + "\n").encode("utf-8"))
            self.serial_conn.flush()
            self._append_history(f"TX:{command.strip()}")

    def get_event(self, timeout: float = 0.1) -> str | None:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def _reader_loop(self) -> None:
        while self._running:
            try:
                if not self.serial_conn or not self.serial_conn.is_open:
                    time.sleep(0.2)
                    continue

                raw = self.serial_conn.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                self.state.last_message = line
                self._append_history(f"RX:{line}")
                self.events.put(line)
            except Exception as exc:
                self._append_history(f"ERROR:{exc}")
                self.state.connected = False
                time.sleep(1)

    def _append_history(self, line: str) -> None:
        self.state.history.append(line)
        if len(self.state.history) > 100:
            self.state.history = self.state.history[-100:]

