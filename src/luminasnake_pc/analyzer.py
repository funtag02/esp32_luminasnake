from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np
from scipy.signal import find_peaks

from .models import AnalysisFrame

BAND_EDGES = np.array(
    [20, 60, 120, 250, 500, 1000, 2000, 3500, 6000, 10_000, 15_000, 20_000],
    dtype=float,
)
GROUP_RANGES = ((20.0, 250.0), (250.0, 6000.0), (6000.0, 20_000.0))


@dataclass(slots=True)
class AnalyzerConfig:
    sample_rate: int = 48_000
    fft_size: int = 4096
    onset_fft_size: int = 1024
    silence_dbfs: float = -58.0
    full_scale_dbfs: float = -12.0
    onset_threshold: float = 0.12


class Analyzer:
    def __init__(self, config: AnalyzerConfig | None = None) -> None:
        self.config = config or AnalyzerConfig()
        self.window = np.hanning(self.config.fft_size).astype(np.float32)
        self.buffer = np.zeros(self.config.fft_size, dtype=np.float32)
        self.onset_window = np.hanning(self.config.onset_fft_size).astype(np.float32)
        self.onset_buffer = np.zeros(self.config.onset_fft_size, dtype=np.float32)
        self.flux_history: deque[tuple[int, float]] = deque(maxlen=800)
        self.previous_magnitude = np.zeros(self.config.fft_size // 2 + 1, dtype=np.float32)
        self.previous_onset_groups = np.zeros(3, dtype=np.float32)
        self.slow_groups = np.zeros(3, dtype=np.float32)
        self.onset_baselines = [deque(maxlen=96) for _ in range(3)]

    def process(self, samples: np.ndarray, timestamp_ns: int) -> AnalysisFrame:
        mono = np.asarray(samples, dtype=np.float32)
        if mono.ndim == 2:
            mono = mono.mean(axis=1)
        mono = mono.reshape(-1)
        if mono.size >= self.buffer.size:
            self.buffer[:] = mono[-self.buffer.size:]
        else:
            self.buffer[:-mono.size] = self.buffer[mono.size:]
            self.buffer[-mono.size:] = mono
        if mono.size >= self.onset_buffer.size:
            self.onset_buffer[:] = mono[-self.onset_buffer.size:]
        else:
            self.onset_buffer[:-mono.size] = self.onset_buffer[mono.size:]
            self.onset_buffer[-mono.size:] = mono
        rms = float(np.sqrt(np.mean(np.square(self.buffer), dtype=np.float64)))
        peak = float(np.max(np.abs(self.buffer)))
        loudness_dbfs = float(20.0 * np.log10(max(rms, 1e-6)))
        loudness_level = float(np.clip(
            (loudness_dbfs - self.config.silence_dbfs) /
            (self.config.full_scale_dbfs - self.config.silence_dbfs),
            0.0,
            1.0,
        ))
        magnitude = np.abs(np.fft.rfft(self.buffer * self.window)).astype(np.float32)
        frequencies = np.fft.rfftfreq(self.config.fft_size, 1 / self.config.sample_rate)
        valid = (frequencies >= 20.0) & (frequencies <= 20_000.0)
        power = np.square(magnitude, dtype=np.float64)
        total = float(power[valid].sum())
        centroid = float((frequencies[valid] * power[valid]).sum() / total) if total > 0 else 0.0
        dominant = float(frequencies[np.argmax(np.where(valid, magnitude, 0.0))]) if total > 0 else 0.0
        bands = np.zeros(BAND_EDGES.size - 1, dtype=np.float32)
        for index, (low, high) in enumerate(zip(BAND_EDGES[:-1], BAND_EDGES[1:], strict=True)):
            mask = (frequencies >= low) & (frequencies < high)
            bands[index] = float(np.sqrt(np.mean(power[mask]))) if np.any(mask) else 0.0
        # This per-frame normalization compares bands with each other; it is not an absolute level.
        absolute_bands = bands.copy()
        maximum = float(absolute_bands.max())
        relative_bands = absolute_bands / maximum if maximum > 0 else absolute_bands

        # The shorter window trades frequency resolution for faster changes in three broad groups.
        onset_magnitude = np.abs(np.fft.rfft(self.onset_buffer * self.onset_window)).astype(np.float32)
        onset_frequencies = np.fft.rfftfreq(
            self.config.onset_fft_size,
            1 / self.config.sample_rate,
        )
        onset_groups = np.array([
            float(np.sqrt(np.mean(np.square(onset_magnitude[
                (onset_frequencies >= low) & (onset_frequencies < high)
            ]))))
            for low, high in GROUP_RANGES
        ], dtype=np.float32)
        positive_change = np.maximum(0.0, onset_groups - self.previous_onset_groups)
        novelty = positive_change / np.maximum(onset_groups, 1e-9)
        novelty *= onset_groups / max(float(onset_groups.max()), 1e-9)
        self.previous_onset_groups[:] = onset_groups
        onset_strengths = np.zeros(3, dtype=np.float32)
        for index, value in enumerate(novelty):
            history = self.onset_baselines[index]
            baseline = float(np.median(history)) if history else 0.0
            threshold = max(self.config.onset_threshold, baseline * 2.5)
            onset_strengths[index] = float(np.clip((value - threshold) / max(1e-6, 1.0 - threshold), 0.0, 1.0))
            history.append(float(value))
        slow_alpha = 0.02
        # Emergence is a rise above this slow per-group background, not instrument recognition.
        self.slow_groups += slow_alpha * (onset_groups - self.slow_groups)
        emergence = np.clip(
            (onset_groups - self.slow_groups) / np.maximum(onset_groups, 1e-9),
            0.0,
            1.0,
        )
        flux = float(np.maximum(0.0, magnitude - self.previous_magnitude).sum())
        self.previous_magnitude[:] = magnitude
        self.flux_history.append((timestamp_ns, flux))
        bpm, confidence = self._tempo()
        return AnalysisFrame(
            timestamp_ns=timestamp_ns,
            rms=rms,
            peak=peak,
            dominant_hz=dominant,
            centroid_hz=centroid,
            bands=relative_bands,
            loudness_dbfs=loudness_dbfs,
            loudness_level=loudness_level,
            onset_low=float(onset_strengths[0]),
            onset_mid=float(onset_strengths[1]),
            onset_high=float(onset_strengths[2]),
            emergence_low=float(emergence[0]),
            emergence_mid=float(emergence[1]),
            emergence_high=float(emergence[2]),
            bpm=bpm,
            bpm_confidence=confidence,
            silent=loudness_dbfs <= self.config.silence_dbfs,
        )

    def _tempo(self) -> tuple[float | None, float]:
        if len(self.flux_history) < 120:
            return None, 0.0
        times = np.array([item[0] for item in self.flux_history], dtype=np.int64)
        values = np.array([item[1] for item in self.flux_history], dtype=float)
        threshold = np.median(values) + 1.5 * np.median(np.abs(values - np.median(values)))
        peaks, _ = find_peaks(values, height=threshold, distance=3)
        if peaks.size < 4:
            return None, 0.0
        intervals = np.diff(times[peaks]) / 1e9
        intervals = intervals[(intervals >= 60 / 220) & (intervals <= 60 / 60)]
        if intervals.size < 3:
            return None, 0.0
        median = float(np.median(intervals))
        spread = float(np.median(np.abs(intervals - median)))
        confidence = max(0.0, min(1.0, 1.0 - spread / max(median, 1e-6)))
        return 60.0 / median, confidence
