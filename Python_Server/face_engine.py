from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

import cv2
import numpy as np


@dataclass
class RecognitionResult:
    matched: bool
    label: str
    score: float
    details: str
    face_count: int


@dataclass
class DetectionResult:
    face_count: int
    details: str
    annotated_frame: np.ndarray


@dataclass
class AnnotatedRecognitionResult:
    recognition: RecognitionResult
    annotated_frame: np.ndarray


@dataclass
class FacePrediction:
    label: str
    score: float
    matched: bool
    box: tuple[int, int, int, int]


@dataclass
class MultiFaceRecognitionResult:
    faces: list[FacePrediction]
    known_labels: list[str]
    unknown_count: int
    face_count: int
    details: str
    annotated_frame: np.ndarray


class OpenCvFaceEngine:
    def __init__(
        self,
        detector_model_path: Path,
        recognizer_model_path: Path,
        known_faces_dir: Path,
        match_threshold: float,
        frame_width: int,
        frame_height: int,
    ) -> None:
        self.detector_model_path = detector_model_path
        self.recognizer_model_path = recognizer_model_path
        self.known_faces_dir = known_faces_dir
        self.match_threshold = match_threshold
        self.frame_size = (frame_width, frame_height)

        self.detector = cv2.FaceDetectorYN.create(
            str(detector_model_path),
            "",
            self.frame_size,
            0.9,
            0.3,
            5000,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_model_path), "")
        self.known_embeddings: dict[str, list[np.ndarray]] = {}

    def load_known_faces(self) -> None:
        self.known_embeddings = {}
        if not self.known_faces_dir.exists():
            return

        for person_dir in sorted(self.known_faces_dir.iterdir()):
            if not person_dir.is_dir():
                continue

            vectors: list[np.ndarray] = []
            for image_path in sorted(person_dir.iterdir()):
                if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
                    continue

                image = cv2.imread(str(image_path))
                if image is None:
                    continue

                embedding = self._extract_embedding(image)
                if embedding is not None:
                    vectors.append(embedding)

            if vectors:
                self.known_embeddings[person_dir.name] = vectors

    def detect_only(self, frame: np.ndarray) -> DetectionResult:
        elapsed_ms, faces = self._detect_faces(frame)
        annotated = self._draw_faces(frame, faces)
        count = 0 if faces is None else len(faces)

        return DetectionResult(
            face_count=count,
            details=f"detect_ms={elapsed_ms:.1f}",
            annotated_frame=annotated,
        )

    def recognize(self, frame: np.ndarray) -> RecognitionResult:
        _, faces = self._detect_faces(frame)

        if faces is None or len(faces) == 0:
            return RecognitionResult(False, "unknown", 0.0, "no face detected", 0)

        best_face = max(faces, key=lambda row: float(row[2] * row[3]))
        embedding = self._extract_embedding_from_face(frame, best_face)
        if embedding is None:
            return RecognitionResult(False, "unknown", 0.0, "face alignment failed", len(faces))

        label, score = self._match_embedding(embedding)
        matched = label != "unknown" and score >= self.match_threshold
        return RecognitionResult(
            matched=matched,
            label=label if matched else "unknown",
            score=score,
            details=f"faces={len(faces)} threshold={self.match_threshold:.3f}",
            face_count=len(faces),
        )

    def recognize_annotated(self, frame: np.ndarray) -> AnnotatedRecognitionResult:
        elapsed_ms, faces = self._detect_faces(frame)
        annotated = self._draw_faces(frame, faces)
        recognition = self.recognize(frame)

        if faces is not None and len(faces) > 0:
            best_face = max(faces, key=lambda row: float(row[2] * row[3]))
            x, y, _, _ = [int(v) for v in best_face[:4]]
            label = recognition.label if recognition.matched else "unknown"
            color = (30, 140, 70) if recognition.matched else (20, 30, 180)
            cv2.putText(
                annotated,
                f"{label} {recognition.score:.2f}",
                (x, max(25, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                color,
                2,
                cv2.LINE_AA,
            )
            recognition.details = f"{recognition.details} detect_ms={elapsed_ms:.1f}"

        return AnnotatedRecognitionResult(recognition=recognition, annotated_frame=annotated)

    def recognize_all(self, frame: np.ndarray) -> MultiFaceRecognitionResult:
        elapsed_ms, faces = self._detect_faces(frame)
        annotated = frame.copy()

        if faces is None or len(faces) == 0:
            return MultiFaceRecognitionResult(
                faces=[],
                known_labels=[],
                unknown_count=0,
                face_count=0,
                details=f"faces=0 detect_ms={elapsed_ms:.1f}",
                annotated_frame=annotated,
            )

        predictions: list[FacePrediction] = []
        known_labels: list[str] = []
        unknown_count = 0

        for face in faces:
            x, y, w, h = [int(v) for v in face[:4]]
            embedding = self._extract_embedding_from_face(frame, face)
            label = "unknown"
            score = 0.0
            matched = False
            if embedding is not None:
                label, score = self._match_embedding(embedding)
                matched = label != "unknown" and score >= self.match_threshold
                if not matched:
                    label = "unknown"
            if matched:
                known_labels.append(label)
            else:
                unknown_count += 1

            predictions.append(
                FacePrediction(
                    label=label,
                    score=score,
                    matched=matched,
                    box=(x, y, w, h),
                )
            )

            color = (30, 140, 70) if matched else (20, 30, 180)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)
            cv2.putText(
                annotated,
                f"{label} {score:.2f}",
                (x, max(25, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                color,
                2,
                cv2.LINE_AA,
            )

        return MultiFaceRecognitionResult(
            faces=predictions,
            known_labels=sorted(set(known_labels)),
            unknown_count=unknown_count,
            face_count=len(predictions),
            details=f"faces={len(predictions)} known={len(set(known_labels))} unknown={unknown_count} detect_ms={elapsed_ms:.1f}",
            annotated_frame=annotated,
        )

    def _extract_embedding(self, image_bgr: np.ndarray) -> np.ndarray | None:
        _, faces = self._detect_faces(image_bgr)
        if faces is None or len(faces) == 0:
            return None
        best_face = max(faces, key=lambda row: float(row[2] * row[3]))
        return self._extract_embedding_from_face(image_bgr, best_face)

    def _extract_embedding_from_face(self, image_bgr: np.ndarray, face: np.ndarray) -> np.ndarray | None:
        try:
            aligned = self.recognizer.alignCrop(image_bgr, face)
            feature = self.recognizer.feature(aligned)
        except cv2.error:
            return None

        embedding = np.asarray(feature, dtype=np.float32).reshape(-1)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def _match_embedding(self, embedding: np.ndarray) -> tuple[str, float]:
        best_label = "unknown"
        best_score = -1.0

        for label, vectors in self.known_embeddings.items():
            for known in vectors:
                score = float(np.dot(embedding, known))
                if score > best_score:
                    best_score = score
                    best_label = label

        if best_score < 0:
            return "unknown", 0.0
        return best_label, best_score

    def registered_labels(self) -> list[str]:
        return sorted(self.known_embeddings.keys())

    def register_face(self, label: str, frame: np.ndarray) -> tuple[bool, str]:
        label = label.strip()
        if not label:
            return False, "label is required"

        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = self.detector.detect(frame)
        if faces is None or len(faces) == 0:
            return False, "no face detected"

        best_face = max(faces, key=lambda row: float(row[2] * row[3]))
        x, y, w, h = [int(v) for v in best_face[:4]]

        margin = 20
        x1 = max(0, x - margin)
        y1 = max(0, y - margin)
        x2 = min(frame.shape[1], x + w + margin)
        y2 = min(frame.shape[0], y + h + margin)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return False, "invalid crop"

        person_dir = self.known_faces_dir / label
        person_dir.mkdir(parents=True, exist_ok=True)
        filename = person_dir / f"{int(time.time())}.jpg"
        ok = cv2.imwrite(str(filename), crop)
        if not ok:
            return False, "failed to save face image"

        self.load_known_faces()
        return True, str(filename)

    def _detect_faces(self, frame: np.ndarray) -> tuple[float, np.ndarray | None]:
        self.detector.setInputSize((frame.shape[1], frame.shape[0]))
        start = time.perf_counter()
        _, faces = self.detector.detect(frame)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return elapsed_ms, faces

    @staticmethod
    def _draw_faces(frame: np.ndarray, faces: np.ndarray | None) -> np.ndarray:
        annotated = frame.copy()
        if faces is None:
            return annotated
        for face in faces:
            x, y, w, h = [int(v) for v in face[:4]]
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (10, 124, 102), 2)
        return annotated
