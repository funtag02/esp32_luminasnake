from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np


class AudioSource(StrEnum):
    LOOPBACK = "loopback"
    FILE = "file"


class VisualMode(StrEnum):
    FULL = "full-spectrum"
    BASS = "bass"
    LOW_MID = "low-mid"
    HIGH_MID = "high-mid"
    HIGH = "high"
    ENERGY = "energy-only"


class FpsPolicy(StrEnum):
    LOCKED_60 = "locked-60"
    CUSTOM = "custom"
    MAX_STABLE = "max-stable"


@dataclass(slots=True)
class AnalysisFrame:
    timestamp_ns: int
    rms: float
    peak: float
    dominant_hz: float
    centroid_hz: float
    bands: np.ndarray
    loudness_dbfs: float = -120.0
    loudness_level: float = 0.0
    onset_low: float = 0.0
    onset_mid: float = 0.0
    onset_high: float = 0.0
    emergence_low: float = 0.0
    emergence_mid: float = 0.0
    emergence_high: float = 0.0
    bpm: float | None = None
    bpm_confidence: float = 0.0
    silent: bool = True


@dataclass(slots=True)
class ConnectionState:
    connected: bool = False
    port: str | None = None
    protocol_version: int | None = None
    strips: int = 0
    leds_per_strip: int = 0
    negotiated_max_fps: int = 0
    sent_frames: int = 0
    errors: int = 0
    accepted_frames: int = 0
    rejected_packets: int = 0
    late_frames: int = 0
    queue_drops: int = 0
    last_error: str = ""


@dataclass(slots=True)
class RuntimeTelemetry:
    analysis: AnalysisFrame | None = None
    connection: ConnectionState = field(default_factory=ConnectionState)
    effective_fps: float = 0.0
    active_source: str = "stopped"
    dropped_sends: int = 0
    last_error: str = ""
    rendered_rgb: tuple[int, int, int] = (0, 0, 0)
    rendered_frequency_hz: float = 0.0
    audio_queue_drops: int = 0
    capture_discontinuities: int = 0
    simulation_frames: tuple[np.ndarray, ...] = ()
    target_fps: int = 60
