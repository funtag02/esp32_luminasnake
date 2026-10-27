from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from .audio import LoopbackCapture
from .engine import Engine
from .models import AudioSource, FpsPolicy, RuntimeTelemetry, VisualMode
from .renderer import COLOR_REGIONS, frequency_color_name
from .settings import Settings, SettingsStore
from .transport import SerialTransport
from .strip_preview import StripPreviewWidget
from .visualizer import SpectrumWidget

MODE_DESCRIPTIONS = {
    VisualMode.FULL.value: "Full spectrum (20 Hz-20 kHz): loudness drives brightness; the strongest transient or dominant frequency drives color.",
    VisualMode.BASS.value: "Bass (20-250 Hz): prioritizes sub-bass, kick drums and bass notes.",
    VisualMode.LOW_MID.value: "Low-mid (250 Hz-2 kHz): body of instruments, lower vocals and snare weight.",
    VisualMode.HIGH_MID.value: "High-mid (2-6 kHz): attack, snare crack, presence and melodic detail.",
    VisualMode.HIGH.value: "High (6-20 kHz): hi-hats, cymbals, air and bright transients.",
    VisualMode.ENERGY.value: "Energy only (20 Hz-20 kHz): white snake; only absolute loudness changes brightness.",
}


class TelemetryBridge(QObject):
    updated = Signal(object)
    audio_devices_loaded = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LuminaSnake PC")
        self.resize(900, 850)
        self.loading = True
        self.store = SettingsStore()
        self.settings = self.store.load()
        self.bridge = TelemetryBridge()
        self.bridge.updated.connect(self._show_telemetry)
        self.bridge.audio_devices_loaded.connect(self._show_audio_devices)
        self.engine = Engine(self.settings, self.bridge.updated.emit)
        self._build_ui()
        self._load_values()
        self.loading = False
        self._apply()
        self._install_shortcuts()
        threading.Thread(target=self._enumerate_audio_devices, daemon=True).start()
        self.engine.start_connection_manager()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        form = QFormLayout()
        self.source = QComboBox()
        self.source.addItem("Windows output capture", AudioSource.LOOPBACK.value)
        self.source.addItem("Local WAV / MP3 / FLAC", AudioSource.FILE.value)
        form.addRow("Audio source", self.source)
        self.audio_device = QComboBox()
        self.audio_device.addItem("Default output", "default")
        form.addRow("Output / loopback device", self.audio_device)
        file_row = QHBoxLayout()
        self.file_label = QLabel("No file selected")
        file_button = QPushButton("Choose file")
        file_button.clicked.connect(self._choose_file)
        file_row.addWidget(self.file_label, 1)
        file_row.addWidget(file_button)
        form.addRow("Precise player", file_row)
        self.port = QComboBox()
        self.port.addItem("Automatic", "auto")
        for port in SerialTransport.ports():
            self.port.addItem(port, port)
        form.addRow("ESP serial port", self.port)
        self.mode = QComboBox()
        for index, mode in enumerate(VisualMode, 1):
            self.mode.addItem(f"{index}  {mode.value}", mode.value)
            self.mode.setItemData(self.mode.count() - 1, MODE_DESCRIPTIONS[mode.value], Qt.ToolTipRole)
        self.mode.addItem("Stems (future)", "stems")
        self.mode.model().item(self.mode.count() - 1).setEnabled(False)
        form.addRow("Visual mode", self.mode)
        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        form.addRow("Mode details", self.mode_description)
        self.strip_enabled: list[QCheckBox] = []
        self.strip_modes: list[QComboBox] = []
        self.strip_lengths: list[QComboBox] = []
        for strip_index in range(5):
            row = QHBoxLayout()
            enabled = QCheckBox("Enabled")
            mode = QComboBox()
            for visual_mode in VisualMode:
                mode.addItem(visual_mode.value, visual_mode.value)
                mode.setItemData(mode.count() - 1, MODE_DESCRIPTIONS[visual_mode.value], Qt.ToolTipRole)
            length = QComboBox()
            length.addItem("120 LEDs", 120)
            length.addItem("60 LEDs", 60)
            row.addWidget(enabled)
            row.addWidget(mode, 1)
            row.addWidget(length)
            form.addRow(f"Virtual strip {strip_index + 1}", row)
            self.strip_enabled.append(enabled)
            self.strip_modes.append(mode)
            self.strip_lengths.append(length)
        preset_row = QHBoxLayout()
        same_button = QPushButton("All strips: selected mode")
        same_button.clicked.connect(self._preset_all_same)
        split_button = QPushButton("One range per strip")
        split_button.clicked.connect(self._preset_split_ranges)
        preset_row.addWidget(same_button)
        preset_row.addWidget(split_button)
        form.addRow("Virtual presets", preset_row)
        self.physical_mapping = QLabel("Physical output: virtual strip 1")
        form.addRow("Hardware mapping", self.physical_mapping)
        self.fps_policy = QComboBox()
        self.fps_policy.addItem("Locked 60 FPS", FpsPolicy.LOCKED_60.value)
        self.fps_policy.addItem("Custom FPS", FpsPolicy.CUSTOM.value)
        self.fps_policy.addItem("Maximum stable (adaptive)", FpsPolicy.MAX_STABLE.value)
        form.addRow("FPS policy", self.fps_policy)
        self.fps = QSpinBox()
        self.fps.setRange(30, 120)
        self.fps.setSuffix(" FPS")
        form.addRow("Target rate", self.fps)
        self.offset = QSlider(Qt.Horizontal)
        self.offset.setRange(-500, 500)
        self.offset_value = QLabel()
        self.offset.valueChanged.connect(lambda value: self.offset_value.setText(f"{value:+d} ms"))
        offset_row = QHBoxLayout()
        offset_row.addWidget(self.offset, 1)
        offset_row.addWidget(self.offset_value)
        form.addRow("LED synchronization offset", offset_row)
        self.lookahead = QSpinBox()
        self.lookahead.setRange(20, 500)
        self.lookahead.setSuffix(" ms")
        form.addRow("Look-ahead", self.lookahead)
        self.intensity = QSlider(Qt.Horizontal)
        self.intensity.setRange(10, 200)
        self.intensity_value = QLabel()
        self.intensity.valueChanged.connect(
            lambda value: self.intensity_value.setText(f"{value}%")
        )
        intensity_row = QHBoxLayout()
        intensity_row.addWidget(self.intensity, 1)
        intensity_row.addWidget(self.intensity_value)
        form.addRow("Visual intensity", intensity_row)
        self.scroll_speed = QSlider(Qt.Horizontal)
        self.scroll_speed.setRange(1, 120)
        self.scroll_speed.setToolTip(
            "Snake movement in physical pixels per second; independent from render FPS"
        )
        self.scroll_speed_value = QLabel()
        self.scroll_speed.valueChanged.connect(
            lambda value: self.scroll_speed_value.setText(f"{value} px/s")
        )
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.scroll_speed, 1)
        speed_row.addWidget(self.scroll_speed_value)
        form.addRow("Scroll speed", speed_row)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.connect_button = QPushButton("Connect ESP")
        self.connect_button.clicked.connect(self._connect)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.engine.stop)
        actions.addWidget(self.connect_button)
        actions.addWidget(self.start_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)
        self.strip_preview = StripPreviewWidget()
        layout.addWidget(self.strip_preview)
        self.spectrum = SpectrumWidget()
        layout.addWidget(self.spectrum)
        color_row = QHBoxLayout()
        self.color_swatch = QLabel()
        self.color_swatch.setFixedSize(48, 48)
        self.color_swatch.setToolTip("Actual RGB head color sent by the desktop renderer")
        self.color_text = QLabel("Visual color: off | 0 Hz | RGB(0, 0, 0)")
        color_row.addWidget(self.color_swatch)
        color_row.addWidget(self.color_text, 1)
        layout.addLayout(color_row)
        legend = "  |  ".join(
            f"{low / 1000:g}-{high / 1000:g} kHz: {name}" if high >= 1000
            else f"{low:g}-{high:g} Hz: {name}"
            for low, high, name in COLOR_REGIONS
        )
        self.color_legend = QLabel(legend)
        self.color_legend.setWordWrap(True)
        layout.addWidget(self.color_legend)
        self.connection = QLabel("ESP: disconnected")
        self.source_status = QLabel("Source: stopped")
        self.bpm = QLabel("BPM: --")
        self.signal = QLabel("Level: -- | onsets low/mid/high: -- | dominant: --")
        self.performance = QLabel("Effective FPS: --")
        for label in (self.connection, self.source_status, self.bpm, self.signal, self.performance):
            layout.addWidget(label)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        self.mode.currentIndexChanged.connect(self._runtime_changed)
        self.mode.currentIndexChanged.connect(self._update_mode_description)
        self.mode.currentIndexChanged.connect(self._primary_mode_changed)
        self.fps_policy.currentIndexChanged.connect(self._fps_policy_changed)
        self.fps.valueChanged.connect(self._runtime_changed)
        self.offset.valueChanged.connect(self._runtime_changed)
        self.lookahead.valueChanged.connect(self._runtime_changed)
        self.intensity.valueChanged.connect(self._runtime_changed)
        self.scroll_speed.valueChanged.connect(self._runtime_changed)
        self.audio_device.currentIndexChanged.connect(self._device_changed)
        for enabled, mode, length in zip(
            self.strip_enabled, self.strip_modes, self.strip_lengths, strict=True
        ):
            enabled.toggled.connect(self._virtual_changed)
            mode.currentIndexChanged.connect(self._virtual_changed)
            length.currentIndexChanged.connect(self._virtual_changed)

    def _load_values(self) -> None:
        for widget, value in ((self.source, self.settings.audio_source),
                              (self.audio_device, self.settings.audio_device_id),
                              (self.port, self.settings.serial_port),
                              (self.mode, self.settings.visual_mode)):
            index = widget.findData(value)
            if index >= 0:
                widget.setCurrentIndex(index)
        self.fps.setValue(self.settings.fps)
        policy_index = self.fps_policy.findData(self.settings.fps_policy)
        self.fps_policy.setCurrentIndex(policy_index if policy_index >= 0 else 0)
        self.offset.setValue(self.settings.offset_ms)
        self.lookahead.setValue(self.settings.lookahead_ms)
        self.intensity.setValue(round(self.settings.intensity * 100))
        self.scroll_speed.setValue(round(self.settings.scroll_speed_pps))
        if self.settings.last_file:
            self.file_label.setText(self.settings.last_file)
        for index, configuration in enumerate(self.settings.virtual_strips):
            self.strip_enabled[index].setChecked(configuration.enabled)
            mode_index = self.strip_modes[index].findData(configuration.mode)
            self.strip_modes[index].setCurrentIndex(mode_index if mode_index >= 0 else 0)
            length_index = self.strip_lengths[index].findData(configuration.length)
            self.strip_lengths[index].setCurrentIndex(length_index if length_index >= 0 else 0)
        self._update_mode_description()
        self._fps_policy_changed()

    def _apply(self) -> None:
        if self.loading:
            return
        previous_device = self.settings.output_device_id
        self.settings.device_offsets_ms[previous_device] = self.offset.value()
        self.settings.audio_source = self.source.currentData()
        self.settings.audio_device_id = self.audio_device.currentData()
        self.settings.output_device_id = self.audio_device.currentData()
        self.settings.serial_port = self.port.currentData()
        self.settings.visual_mode = self.mode.currentData()
        self.settings.fps = self.fps.value()
        self.settings.fps_policy = self.fps_policy.currentData()
        self.settings.offset_ms = self.offset.value()
        self.settings.lookahead_ms = self.lookahead.value()
        self.settings.intensity = self.intensity.value() / 100
        self.settings.scroll_speed_pps = float(self.scroll_speed.value())
        for index, configuration in enumerate(self.settings.virtual_strips):
            configuration.enabled = self.strip_enabled[index].isChecked()
            configuration.mode = self.strip_modes[index].currentData()
            configuration.length = self.strip_lengths[index].currentData()
        self.settings.visual_mode = self.settings.virtual_strips[0].mode
        primary = self.settings.virtual_strips[0]
        state = "enabled" if primary.enabled else "disabled / physical LEDs off"
        self.physical_mapping.setText(
            f"Physical output: virtual strip 1, {primary.mode}, {primary.length} LEDs, {state}"
        )
        self.settings.device_offsets_ms[self.settings.output_device_id] = self.settings.offset_ms
        self.settings.validate()
        self.store.save(self.settings)
        self.engine.apply_runtime_settings()

    def _runtime_changed(self, *_args) -> None:
        if self.mode.currentData() == "stems":
            return
        self._apply()

    def _update_mode_description(self, *_args) -> None:
        mode = self.mode.currentData()
        self.mode_description.setText(
            MODE_DESCRIPTIONS.get(mode, "Future source-separation mode; not implemented.")
        )

    def _primary_mode_changed(self, *_args) -> None:
        if self.loading:
            return
        mode = self.mode.currentData()
        if mode in {item.value for item in VisualMode}:
            index = self.strip_modes[0].findData(mode)
            self.strip_modes[0].blockSignals(True)
            self.strip_modes[0].setCurrentIndex(index)
            self.strip_modes[0].blockSignals(False)
            self._apply()

    def _virtual_changed(self, *_args) -> None:
        if self.loading:
            return
        primary_mode = self.strip_modes[0].currentData()
        mode_index = self.mode.findData(primary_mode)
        if mode_index >= 0 and self.mode.currentIndex() != mode_index:
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(mode_index)
            self.mode.blockSignals(False)
            self._update_mode_description()
        self._apply()

    def _preset_all_same(self) -> None:
        selected = self.mode.currentData()
        self.loading = True
        for enabled, mode in zip(self.strip_enabled, self.strip_modes, strict=True):
            enabled.setChecked(True)
            mode.setCurrentIndex(mode.findData(selected))
        self.loading = False
        self._apply()

    def _preset_split_ranges(self) -> None:
        modes = (VisualMode.FULL, VisualMode.BASS, VisualMode.LOW_MID,
                 VisualMode.HIGH_MID, VisualMode.HIGH)
        self.loading = True
        for enabled, selector, mode in zip(
            self.strip_enabled, self.strip_modes, modes, strict=True
        ):
            enabled.setChecked(True)
            selector.setCurrentIndex(selector.findData(mode.value))
        self.loading = False
        self._apply()

    def _fps_policy_changed(self, *_args) -> None:
        self.fps.setEnabled(self.fps_policy.currentData() == FpsPolicy.CUSTOM.value)
        self._apply()

    def _device_changed(self, *_args) -> None:
        device_id = self.audio_device.currentData()
        if device_id is None:
            return
        previous_device = self.settings.output_device_id
        self.settings.device_offsets_ms[previous_device] = self.offset.value()
        self.settings.audio_device_id = device_id
        self.settings.output_device_id = device_id
        self.offset.blockSignals(True)
        self.offset.setValue(self.settings.device_offsets_ms.get(device_id, 0))
        self.offset.blockSignals(False)
        self._apply()

    def _enumerate_audio_devices(self) -> None:
        try:
            result = (LoopbackCapture.devices(), "")
        except Exception as error:
            result = ([], str(error))
        self.bridge.audio_devices_loaded.emit(result)

    def _show_audio_devices(self, result) -> None:
        devices, error = result
        selected = self.settings.audio_device_id
        self.audio_device.blockSignals(True)
        self.audio_device.clear()
        self.audio_device.addItem("Default output", "default")
        for device_id, name in devices:
            self.audio_device.addItem(name, device_id)
        index = self.audio_device.findData(selected)
        self.audio_device.setCurrentIndex(index if index >= 0 else 0)
        self.audio_device.blockSignals(False)
        if error:
            self.statusBar().showMessage(f"Audio device discovery failed: {error}")

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose audio", "", "Audio (*.wav *.flac *.mp3)")
        if path:
            self.settings.last_file = path
            self.file_label.setText(path)
            self.source.setCurrentIndex(self.source.findData(AudioSource.FILE.value))

    def _connect(self) -> None:
        self._apply()
        self.connection.setText("ESP: connecting...")
        self.engine.transport.disconnect()
        self.engine.start_connection_manager()

    def _start(self) -> None:
        self._apply()
        if self.settings.audio_source == AudioSource.FILE and not self.settings.last_file:
            self._choose_file()
            if not self.settings.last_file:
                return
        self.engine.start()

    def _show_telemetry(self, telemetry: RuntimeTelemetry) -> None:
        state = telemetry.connection
        self.connection.setText(f"ESP: {'connected ' + str(state.port) if state.connected else 'disconnected'}")
        self.source_status.setText(f"Source: {telemetry.active_source}")
        if telemetry.analysis:
            analysis = telemetry.analysis
            self.spectrum.set_analysis(analysis)
            bpm = f"{analysis.bpm:.1f} ({analysis.bpm_confidence:.0%})" if analysis.bpm else "--"
            self.bpm.setText(f"BPM: {bpm}")
            self.signal.setText(
                f"Level: {analysis.loudness_dbfs:.1f} dBFS / {analysis.loudness_level:.0%} | "
                f"onsets: {analysis.onset_low:.2f}/{analysis.onset_mid:.2f}/{analysis.onset_high:.2f} | "
                f"dominant: {analysis.dominant_hz:.0f} Hz"
            )
            red, green, blue = telemetry.rendered_rgb
            visual_frequency = telemetry.rendered_frequency_hz
            color_name = frequency_color_name(visual_frequency) if red + green + blue else "Off"
            self.color_swatch.setStyleSheet(
                f"background-color: rgb({red}, {green}, {blue}); border: 1px solid #6f7d89;"
            )
            self.color_text.setText(
                f"Visual color: {color_name} | {visual_frequency:.0f} Hz | "
                f"RGB({red}, {green}, {blue})"
            )
            labels = tuple(
                f"{index + 1}: {configuration.mode} ({configuration.length})"
                for index, configuration in enumerate(self.settings.virtual_strips)
            )
            self.strip_preview.set_frames(telemetry.simulation_frames, labels)
        maximum = state.negotiated_max_fps or 120
        if state.connected and self.fps.maximum() != maximum:
            self.fps.blockSignals(True)
            self.fps.setMaximum(maximum)
            self.fps.setValue(min(self.fps.value(), maximum))
            self.fps.blockSignals(False)
        self.performance.setText(
            f"Effective FPS: {telemetry.effective_fps:.1f} / target {telemetry.target_fps} | ESP max: {maximum} | "
            f"accepted: {state.accepted_frames} late: {state.late_frames} "
            f"rejected: {state.rejected_packets} dropped: {state.queue_drops} "
            f"PC send errors: {telemetry.dropped_sends} | "
            f"capture gaps: {telemetry.capture_discontinuities} "
            f"audio queue drops: {telemetry.audio_queue_drops}"
        )
        if telemetry.last_error:
            self.statusBar().showMessage(telemetry.last_error)

    def _install_shortcuts(self) -> None:
        for index in range(6):
            shortcut = QShortcut(QKeySequence(str(index + 1)), self)
            shortcut.activated.connect(lambda selected=index: self.mode.setCurrentIndex(selected))

    def closeEvent(self, event) -> None:
        self._apply()
        self.engine.stop()
        self.engine.transport.disconnect()
        super().closeEvent(event)
