from __future__ import annotations

import threading
import time
import warnings
from collections import deque
from collections.abc import Callable
from math import ceil, gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

AudioCallback = Callable[[np.ndarray, int], None]
WarningCallback = Callable[[str], None]


class LoopbackCapture:
    @staticmethod
    def devices() -> list[tuple[str, str]]:
        import soundcard as sc

        return [(speaker.id, speaker.name) for speaker in sc.all_speakers()]

    def run(self, callback: AudioCallback, stop: threading.Event, device_id: str = "default",
            sample_rate: int = 48_000, block_size: int = 1024,
            on_discontinuity: WarningCallback | None = None) -> None:
        import soundcard as sc

        speaker = sc.default_speaker() if device_id == "default" else next(
            item for item in sc.all_speakers() if item.id == device_id)
        try:
            microphone = sc.get_microphone(speaker.id, include_loopback=True)
        except (IndexError, ValueError) as error:
            raise RuntimeError(f"No loopback capture is available for {speaker.name}") from error
        with microphone.recorder(samplerate=sample_rate, channels=2, blocksize=block_size) as recorder:
            while not stop.is_set():
                with warnings.catch_warnings(record=True) as captured:
                    warnings.simplefilter("always")
                    samples = recorder.record(block_size)
                for warning in captured:
                    if on_discontinuity is not None:
                        on_discontinuity(str(warning.message))
                callback(samples, time.perf_counter_ns())


class LocalFilePlayer:
    @staticmethod
    def supported(path: str) -> bool:
        return Path(path).suffix.lower() in {".wav", ".flac", ".mp3"}

    def run(self, path: str, callback: AudioCallback, stop: threading.Event,
            device_id: str = "default", block_size: int = 256,
            lookahead_ms: int = 150) -> None:
        import soundcard as sc
        import soundfile as sf

        if not self.supported(path):
            raise ValueError("Only WAV, FLAC and MP3 are supported")
        speaker = sc.default_speaker() if device_id == "default" else next(
            item for item in sc.all_speakers() if item.id == device_id)
        with sf.SoundFile(path) as source:
            with speaker.player(samplerate=source.samplerate, channels=source.channels,
                                blocksize=block_size) as player:
                block_duration_ns = round(block_size * 1e9 / source.samplerate)
                lookahead_blocks = max(1, ceil(lookahead_ms * 1e6 / block_duration_ns))
                next_presentation_ns = time.perf_counter_ns() + lookahead_ms * 1_000_000
                pending: deque[tuple[np.ndarray, int]] = deque()

                def read_and_analyze() -> bool:
                    nonlocal next_presentation_ns
                    block = source.read(block_size, dtype="float32", always_2d=True)
                    if block.size == 0:
                        return False
                    valid_frames = block.shape[0]
                    if valid_frames < block_size:
                        padding = np.zeros((block_size - valid_frames, block.shape[1]), dtype=np.float32)
                        block = np.vstack((block, padding))
                    if source.samplerate == 48_000:
                        analysis_block = block
                    else:
                        divisor = gcd(source.samplerate, 48_000)
                        analysis_block = resample_poly(
                            block,
                            48_000 // divisor,
                            source.samplerate // divisor,
                            axis=0,
                        ).astype(np.float32)
                    callback(analysis_block, next_presentation_ns)
                    pending.append((block[:valid_frames], next_presentation_ns))
                    next_presentation_ns += block_duration_ns
                    return True

                for _ in range(lookahead_blocks):
                    if not read_and_analyze():
                        break
                while not stop.is_set() and pending:
                    block, presentation_ns = pending.popleft()
                    remaining_ns = presentation_ns - time.perf_counter_ns()
                    if remaining_ns > 0:
                        stop.wait(remaining_ns / 1e9)
                    if stop.is_set():
                        break
                    player.play(block)
                    read_and_analyze()
