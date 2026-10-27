from __future__ import annotations

import threading
import time
from copy import copy
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from queue import Empty, Full, Queue

import numpy as np

from .analyzer import Analyzer
from .audio import LocalFilePlayer, LoopbackCapture
from .models import AnalysisFrame, AudioSource, FpsPolicy, RuntimeTelemetry
from .simulation import SimulationBank
from .settings import Settings
from .transport import SerialTransport


class Engine:
    def __init__(self, settings: Settings, on_telemetry: Callable[[RuntimeTelemetry], None]) -> None:
        self.settings = settings
        self.on_telemetry = on_telemetry
        self.telemetry = RuntimeTelemetry()
        self.transport = SerialTransport(self._connection_changed)
        self.analyzer = Analyzer()
        self.simulation = SimulationBank(settings.virtual_strips)
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.analysis_worker: threading.Thread | None = None
        self.render_worker: threading.Thread | None = None
        self.audio_queue: Queue[tuple[np.ndarray, int]] = Queue(maxsize=8)
        self.analysis_frames: deque[AnalysisFrame] = deque(maxlen=256)
        self.analysis_lock = threading.Lock()
        self.connection_stop = threading.Event()
        self.connection_worker: threading.Thread | None = None
        self.last_send_ns = 0
        self.next_send_ns = 0
        self.previous_send_ns = 0
        self.frame_interval_ns = int(1e9 / settings.fps)
        self.adaptive_fps = 60
        self.stable_frames = 0
        self.last_pressure = (0, 0, 0, 0, 0, 0)

    def connect(self) -> bool:
        connected = self.transport.connect(self.settings.serial_port)
        return connected

    def start_connection_manager(self) -> None:
        if self.connection_worker and self.connection_worker.is_alive():
            if not self.connection_stop.is_set():
                return
            self.connection_worker.join(timeout=1.0)
        self.connection_stop.clear()
        self.connection_worker = threading.Thread(target=self._connection_loop, daemon=True)
        self.connection_worker.start()

    def start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.start_connection_manager()
        self.analysis_worker = threading.Thread(target=self._analysis_loop, daemon=True)
        self.render_worker = threading.Thread(target=self._render_loop, daemon=True)
        self.analysis_worker.start()
        self.render_worker.start()
        target = self._run_loopback if self.settings.audio_source == AudioSource.LOOPBACK else self._run_file
        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def apply_runtime_settings(self) -> None:
        self.simulation.configure(self.settings.virtual_strips)
        self._update_frame_interval()

    def stop(self) -> None:
        self.stop_event.set()
        self.connection_stop.set()
        self.transport.disconnect()
        self.telemetry.active_source = "stopped"
        self._notify()

    def _run_loopback(self) -> None:
        self.telemetry.active_source = "Windows loopback"
        try:
            LoopbackCapture().run(
                self._audio_block,
                self.stop_event,
                self.settings.audio_device_id,
                on_discontinuity=self._capture_discontinuity,
            )
        except Exception as error:
            self._report_error(error)

    def _run_file(self) -> None:
        self.telemetry.active_source = "Local file"
        try:
            LocalFilePlayer().run(self.settings.last_file, self._audio_block, self.stop_event,
                                  self.settings.output_device_id,
                                  lookahead_ms=self.settings.lookahead_ms)
        except Exception as error:
            self._report_error(error)

    def _audio_block(self, samples, timestamp_ns: int) -> None:
        item = (np.asarray(samples, dtype=np.float32).copy(), timestamp_ns)
        try:
            self.audio_queue.put_nowait(item)
        except Full:
            # Keep the stream near real time by replacing the oldest queued block.
            try:
                self.audio_queue.get_nowait()
            except Empty:
                pass
            try:
                self.audio_queue.put_nowait(item)
            except Full:
                pass
            self.telemetry.audio_queue_drops += 1

    def _analysis_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                samples, timestamp_ns = self.audio_queue.get(timeout=0.1)
            except Empty:
                continue
            analysis = self.analyzer.process(samples, timestamp_ns)
            with self.analysis_lock:
                self.analysis_frames.append(analysis)
            self.telemetry.analysis = analysis

    def _render_loop(self) -> None:
        next_tick_ns = time.perf_counter_ns()
        previous_tick_ns = next_tick_ns
        while not self.stop_event.is_set():
            now_ns = time.perf_counter_ns()
            remaining_ns = next_tick_ns - now_ns
            if remaining_ns > 0:
                self.stop_event.wait(remaining_ns / 1e9)
                continue
            analysis = self._analysis_for_render(now_ns)
            if analysis is not None:
                elapsed_render_ns = max(0, now_ns - previous_tick_ns)
                previous_tick_ns = now_ns
                simulation_frames = self.simulation.render(
                    analysis,
                    self.settings.virtual_strips,
                    self.settings.intensity,
                    self.settings.scroll_speed_pps,
                    elapsed_render_ns / 1e9,
                    elapsed_render_ns,
                )
                self.telemetry.simulation_frames = simulation_frames
                primary = simulation_frames[0]
                self.telemetry.rendered_rgb = tuple(int(channel) for channel in primary[0])
                self.telemetry.rendered_frequency_hz = self.simulation.renderers[0].last_frequency_hz
                delay_ms = min(
                    500,
                    max(0, round((analysis.timestamp_ns - now_ns) / 1e6) + self.settings.offset_ms),
                )
                if self.transport.snapshot().connected:
                    try:
                        state = self.transport.snapshot()
                        physical = SimulationBank.physical_frame(
                            primary,
                            state.strips or 1,
                            state.leds_per_strip or 120,
                        )
                        self.transport.send_frame(physical, delay_ms * 1000)
                    except ConnectionError as error:
                        self.telemetry.dropped_sends += 1
                        self.telemetry.last_error = str(error)
                if self.previous_send_ns:
                    # This is render-loop cadence, even when no ESP frame is sent or acknowledged.
                    instantaneous_fps = 1e9 / max(1, now_ns - self.previous_send_ns)
                    if self.telemetry.effective_fps == 0.0:
                        self.telemetry.effective_fps = instantaneous_fps
                    else:
                        self.telemetry.effective_fps += 0.10 * (
                            instantaneous_fps - self.telemetry.effective_fps
                        )
                self.previous_send_ns = now_ns
                self._adapt_fps()
                self._notify()
            interval_ns = self.frame_interval_ns
            next_tick_ns += interval_ns
            if next_tick_ns < now_ns - interval_ns:
                next_tick_ns = now_ns + interval_ns

    def _analysis_for_render(self, now_ns: int) -> AnalysisFrame | None:
        with self.analysis_lock:
            if not self.analysis_frames:
                return None
            if self.settings.audio_source != AudioSource.FILE:
                return self.analysis_frames[-1]
            target_ns = now_ns + self.settings.lookahead_ms * 1_000_000
            selected = self.analysis_frames[0]
            for candidate in self.analysis_frames:
                if candidate.timestamp_ns > target_ns:
                    break
                selected = candidate
            while len(self.analysis_frames) > 1 and self.analysis_frames[1].timestamp_ns <= selected.timestamp_ns:
                self.analysis_frames.popleft()
            return selected

    def _fps_limit(self) -> int:
        negotiated = self.transport.snapshot().negotiated_max_fps
        return negotiated if negotiated > 0 else 120

    def _update_frame_interval(self) -> None:
        policy = FpsPolicy(self.settings.fps_policy)
        if policy == FpsPolicy.LOCKED_60:
            target = min(60, self._fps_limit())
        elif policy == FpsPolicy.CUSTOM:
            target = min(self.settings.fps, self._fps_limit())
        else:
            target = min(self.adaptive_fps, self._fps_limit())
        target = max(30, target)
        self.telemetry.target_fps = target
        self.frame_interval_ns = int(1e9 / target)

    def _adapt_fps(self) -> None:
        if FpsPolicy(self.settings.fps_policy) != FpsPolicy.MAX_STABLE:
            self._update_frame_interval()
            return
        state = self.transport.snapshot()
        pressure = (
            state.late_frames,
            state.queue_drops,
            state.rejected_packets,
            self.telemetry.dropped_sends,
            self.telemetry.audio_queue_drops,
            self.telemetry.capture_discontinuities,
        )
        if pressure != self.last_pressure:
            self.adaptive_fps = max(30, self.adaptive_fps - 10)
            self.stable_frames = 0
            self.last_pressure = pressure
        else:
            self.stable_frames += 1
            if self.stable_frames >= self.adaptive_fps * 5:
                self.adaptive_fps = min(self._fps_limit(), self.adaptive_fps + 5)
                self.stable_frames = 0
        self._update_frame_interval()

    def _connection_changed(self, state) -> None:
        self.telemetry.connection = state
        self._notify()

    def _connection_loop(self) -> None:
        while not self.connection_stop.is_set():
            if not self.transport.snapshot().connected:
                if self.connect():
                    continue
            self.connection_stop.wait(3.0)

    def _report_error(self, error: Exception) -> None:
        self.telemetry.last_error = str(error)
        self.telemetry.active_source = "error"
        self._notify()

    def _capture_discontinuity(self, message: str) -> None:
        self.telemetry.capture_discontinuities += 1
        self.telemetry.last_error = message

    def _notify(self) -> None:
        snapshot = copy(self.telemetry)
        snapshot.connection = replace(self.telemetry.connection)
        snapshot.simulation_frames = tuple(frame.copy() for frame in self.telemetry.simulation_frames)
        self.on_telemetry(snapshot)
