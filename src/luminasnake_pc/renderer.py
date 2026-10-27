from __future__ import annotations

import numpy as np

from .models import AnalysisFrame, VisualMode

ANCHORS = np.array([
    [0, 255, 0, 0], [300, 255, 0, 0], [800, 255, 0, 115],
    [1800, 115, 0, 255], [3500, 0, 64, 255], [6000, 0, 255, 255],
    [10_000, 115, 255, 255], [15_000, 255, 255, 255], [20_000, 255, 255, 255],
], dtype=float)
MODE_RANGES = {
    VisualMode.FULL: (20.0, 20_000.0), VisualMode.BASS: (20.0, 250.0),
    VisualMode.LOW_MID: (250.0, 2000.0), VisualMode.HIGH_MID: (2000.0, 6000.0),
    VisualMode.HIGH: (6000.0, 20_000.0), VisualMode.ENERGY: (20.0, 20_000.0),
}

COLOR_REGIONS = (
    (0.0, 300.0, "Red"),
    (300.0, 800.0, "Red to magenta"),
    (800.0, 1800.0, "Magenta to violet"),
    (1800.0, 3500.0, "Violet to blue"),
    (3500.0, 6000.0, "Blue to cyan"),
    (6000.0, 10_000.0, "Cyan to pale cyan"),
    (10_000.0, 15_000.0, "Pale cyan to white"),
    (15_000.0, 20_000.0, "White"),
)


def frequency_rgb(frequency_hz: float) -> np.ndarray:
    return np.array([
        np.interp(frequency_hz, ANCHORS[:, 0], ANCHORS[:, channel])
        for channel in range(1, 4)
    ])


def frequency_color_name(frequency_hz: float) -> str:
    bounded = float(np.clip(frequency_hz, 0.0, 20_000.0))
    for low, high, name in COLOR_REGIONS:
        if low <= bounded < high or (bounded == 20_000.0 and high == 20_000.0):
            return name
    return "Unknown"


class SnakeRenderer:
    def __init__(self, strips: int = 1, leds: int = 120) -> None:
        self.frame = np.zeros((strips, leds, 3), dtype=np.uint8)
        self.last_frequency_hz = 0.0
        self.last_analysis_timestamp_ns = -1
        self.onset_envelope = np.zeros(3, dtype=float)
        self.scroll_phase = 0
        self.pending_head = np.zeros(3, dtype=np.uint8)

    def render(self, analysis: AnalysisFrame, mode: VisualMode, intensity: float = 1.0,
               scroll_speed_pps: float = 60.0, elapsed_seconds: float = 1 / 60,
               elapsed_ns: int | None = None) -> np.ndarray:
        fresh_onsets = np.zeros(3, dtype=float)
        # Render ticks can reuse one analysis frame; only a new audio frame may retrigger an onset.
        if analysis.timestamp_ns != self.last_analysis_timestamp_ns:
            fresh_onsets[:] = (analysis.onset_low, analysis.onset_mid, analysis.onset_high)
            self.last_analysis_timestamp_ns = analysis.timestamp_ns
        self.onset_envelope = np.maximum(fresh_onsets, self.onset_envelope * 0.55)
        energy, frequency, onset, emergence = self._mode_values(analysis, mode)
        self.last_frequency_hz = frequency
        level = np.clip(0.65 * energy + 0.55 * onset + 0.25 * emergence, 0.0, 1.0) ** 0.8
        if analysis.silent or level <= 0:
            head = np.zeros(3, dtype=np.uint8)
        elif mode == VisualMode.ENERGY:
            head = np.rint(np.array([255, 255, 255]) * level * intensity).clip(0, 255).astype(np.uint8)
        else:
            rgb = frequency_rgb(frequency)
            head = np.rint(rgb * level * intensity).clip(0, 255).astype(np.uint8)
        if int(head.sum()) >= int(self.pending_head.sum()):
            self.pending_head = head
        # Accumulate elapsed time so pixel travel stays independent of render FPS.
        elapsed_ns = max(0, elapsed_ns if elapsed_ns is not None
                 else round(elapsed_seconds * 1_000_000_000))
        speed_milli_pps = max(0, round(scroll_speed_pps * 1000))
        phase_denominator = 1_000_000_000 * 1000
        self.scroll_phase += elapsed_ns * speed_milli_pps
        steps = min(self.frame.shape[1], self.scroll_phase // phase_denominator)
        if steps > 0:
            self.scroll_phase -= steps * phase_denominator
            if steps < self.frame.shape[1]:
                self.frame[:, steps:] = self.frame[:, :-steps]
            self.frame[:, :steps] = self.pending_head
            self.pending_head = np.zeros(3, dtype=np.uint8)
        return self.frame.copy()

    def _mode_values(self, analysis: AnalysisFrame, mode: VisualMode) -> tuple[float, float, float, float]:
        low, high = MODE_RANGES[mode]
        if mode in (VisualMode.FULL, VisualMode.ENERGY):
            onsets = self.onset_envelope
            emergences = np.array([
                analysis.emergence_low,
                analysis.emergence_mid,
                analysis.emergence_high,
            ])
            onset_index = int(np.argmax(onsets))
            onset = float(onsets[onset_index])
            emergence = float(emergences.max())
            transient_frequencies = (100.0, 1800.0, 8000.0)
            frequency = transient_frequencies[onset_index] if onset > 0.10 else analysis.dominant_hz
            return analysis.loudness_level, frequency, onset, emergence
        edges = np.array([20, 60, 120, 250, 500, 1000, 2000, 3500, 6000, 10_000, 15_000, 20_000])
        centers = np.sqrt(edges[:-1] * edges[1:])
        mask = (centers >= low) & (centers < high)
        if not np.any(mask):
            return 0.0, (low + high) / 2, 0.0, 0.0
        selected = analysis.bands[mask]
        index = int(np.argmax(selected))
        if mode is VisualMode.BASS:
            onset = float(self.onset_envelope[0])
            emergence = analysis.emergence_low
        elif mode in (VisualMode.LOW_MID, VisualMode.HIGH_MID):
            onset = float(self.onset_envelope[1])
            emergence = analysis.emergence_mid
        else:
            onset = float(self.onset_envelope[2])
            emergence = analysis.emergence_high
        energy = analysis.loudness_level * float(selected[index])
        return energy, float(centers[mask][index]), onset, emergence
