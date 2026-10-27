from pathlib import Path

import numpy as np

from luminasnake_pc.analyzer import Analyzer
from luminasnake_pc.models import FpsPolicy, VisualMode
from luminasnake_pc.settings import Settings, SettingsStore, VirtualStripSettings


def test_settings_are_clamped_and_persisted(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = Settings(fps=999, offset_ms=-999, intensity=4)
    store.save(settings)
    loaded = store.load()
    assert loaded.fps == 120
    assert loaded.offset_ms == -500
    assert loaded.intensity == 2.0


def test_legacy_zero_intensity_migrates_to_default():
    settings = Settings(intensity=0.0)
    settings.validate()
    assert settings.intensity == 1.0


def test_scroll_speed_is_clamped():
    slow = Settings(scroll_speed_pps=0)
    fast = Settings(scroll_speed_pps=999)
    slow.validate()
    fast.validate()
    assert slow.scroll_speed_pps == 1.0
    assert fast.scroll_speed_pps == 120.0


def test_removed_legacy_fields_do_not_reset_valid_settings(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"fps": 90, "intensity": 1.5, "removed_legacy_option": true}',
        encoding="utf-8",
    )
    loaded = SettingsStore(path).load()
    assert loaded.fps == 90
    assert loaded.intensity == 1.5


def test_five_virtual_strips_and_fps_policy_persist(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    settings = Settings(
        fps_policy=FpsPolicy.MAX_STABLE,
        virtual_strips=[
            VirtualStripSettings(mode=VisualMode.BASS, length=60),
            VirtualStripSettings(enabled=False, mode=VisualMode.HIGH, length=120),
        ],
    )
    store.save(settings)
    loaded = store.load()
    assert loaded.fps_policy == FpsPolicy.MAX_STABLE
    assert len(loaded.virtual_strips) == 5
    assert loaded.virtual_strips[0].mode == VisualMode.BASS
    assert loaded.virtual_strips[0].length == 60
    assert not loaded.virtual_strips[1].enabled


def test_analyzer_finds_one_khz_tone():
    analyzer = Analyzer()
    t = np.arange(4096) / 48_000
    frame = analyzer.process(np.sin(2 * np.pi * 1000 * t).astype(np.float32), 0)
    assert 980 <= frame.dominant_hz <= 1020
    assert not frame.silent


def test_analyzer_marks_digital_silence():
    frame = Analyzer().process(np.zeros(4096, dtype=np.float32), 0)
    assert frame.silent
    assert frame.rms == 0
    assert frame.loudness_level == 0


def test_loudness_increases_with_amplitude_at_same_frequency():
    time = np.arange(4096) / 48_000
    quiet = Analyzer().process((0.01 * np.sin(2 * np.pi * 1000 * time)).astype(np.float32), 0)
    loud = Analyzer().process((0.5 * np.sin(2 * np.pi * 1000 * time)).astype(np.float32), 0)
    assert quiet.dominant_hz == loud.dominant_hz
    assert quiet.loudness_level < loud.loudness_level
    assert loud.loudness_level == 1.0


def test_low_and_mid_attacks_are_classified_separately():
    silence = np.zeros(4096, dtype=np.float32)
    time = np.arange(4096) / 48_000
    low_analyzer = Analyzer()
    low_analyzer.process(silence, 0)
    low = low_analyzer.process(np.sin(2 * np.pi * 100 * time).astype(np.float32), 100_000_000)
    mid_analyzer = Analyzer()
    mid_analyzer.process(silence, 0)
    mid = mid_analyzer.process(np.sin(2 * np.pi * 1800 * time).astype(np.float32), 100_000_000)
    assert low.onset_low > low.onset_mid
    assert low.onset_low > low.onset_high
    assert mid.onset_mid > mid.onset_low
    assert mid.onset_mid > mid.onset_high


def test_kick_is_detected_over_continuous_bass():
    analyzer = Analyzer()
    time = np.arange(1024) / 48_000
    bass = (0.18 * np.sin(2 * np.pi * 80 * time)).astype(np.float32)
    baseline = None
    for index in range(12):
        baseline = analyzer.process(bass, index * 21_333_333)
    kick_envelope = np.exp(-time * 24.0)
    kick = (0.75 * kick_envelope * np.sin(2 * np.pi * 100 * time)).astype(np.float32)
    transient = analyzer.process(bass + kick, 13 * 21_333_333)
    assert baseline is not None
    assert transient.onset_low > 0.25
    assert transient.onset_low > transient.onset_mid
    assert transient.loudness_level >= baseline.loudness_level
