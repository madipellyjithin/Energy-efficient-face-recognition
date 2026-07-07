from __future__ import annotations

import threading

import cv2
import numpy as np


class CameraService:
    def __init__(self, camera_index: int, width: int, height: int) -> None:
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.cap: cv2.VideoCapture | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        # Defer actual camera open until the first frame request to avoid
        # blocking Flask startup on systems where camera init is slow.
        return

    def get_frame(self) -> np.ndarray:
        with self._lock:
            if self.cap is None:
                self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            if self.cap is None or not self.cap.isOpened():
                raise RuntimeError("Failed to open camera")
            ok, frame = self.cap.read()
            if not ok or frame is None:
                raise RuntimeError("Failed to capture frame from camera")
            return frame

    def stop(self) -> None:
        with self._lock:
            if self.cap is not None:
                self.cap.release()
                self.cap = None
