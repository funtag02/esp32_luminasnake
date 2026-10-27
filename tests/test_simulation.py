import numpy as np

from luminasnake_pc.models import AnalysisFrame, VisualMode
from luminasnake_pc.settings import VirtualStripSettings
from luminasnake_pc.simulation import SimulationBank


def analysis() -> AnalysisFrame:
    return AnalysisFrame(
        timestamp_ns=1,
        rms=0.2,
        peak=0.5,
        dominant_hz=1000.0,
        centroid_hz=1200.0,
        bands=np.linspace(0.1, 1.0, 11, dtype=np.float32),
        loudness_level=0.7,
        onset_low=0.8,
        onset_mid=0.2,
        silent=False,
    )


def test_five_virtual_strips_keep_independent_lengths_and_modes():
    configurations = [
        VirtualStripSettings(mode=VisualMode.FULL, length=120),
        VirtualStripSettings(mode=VisualMode.BASS, length=60),
        VirtualStripSettings(mode=VisualMode.LOW_MID, length=120),
        VirtualStripSettings(mode=VisualMode.HIGH_MID, length=60),
        VirtualStripSettings(mode=VisualMode.HIGH, length=120),
    ]
    frames = SimulationBank(configurations).render(
        analysis(), configurations, 1.0, scroll_speed_pps=60.0, elapsed_seconds=1 / 60
    )
    assert len(frames) == 5
    assert [len(frame) for frame in frames] == [120, 60, 120, 60, 120]
    assert not np.array_equal(frames[1][0], frames[4][0])


def test_disabled_virtual_strip_is_black():
    configurations = [VirtualStripSettings(enabled=False) for _ in range(5)]
    frames = SimulationBank(configurations).render(
        analysis(), configurations, 1.0, scroll_speed_pps=60.0, elapsed_seconds=1 / 60
    )
    assert all(np.all(frame == 0) for frame in frames)


def test_first_virtual_strip_resizes_to_physical_geometry():
    source = np.arange(60 * 3, dtype=np.uint8).reshape(60, 3)
    physical = SimulationBank.physical_frame(source, strip_count=1, leds_per_strip=120)
    assert physical.shape == (1, 120, 3)
    assert np.array_equal(physical[0, 0], source[0])
    assert np.array_equal(physical[0, -1], source[-1])


def test_scroll_speed_is_independent_from_render_fps():
    configuration = [VirtualStripSettings() for _ in range(5)]
    at_60 = SimulationBank(configuration)
    at_100 = SimulationBank(configuration)
    elapsed_60 = [1_000_000_000 // 60] * 60
    elapsed_60[-1] += 1_000_000_000 - sum(elapsed_60)
    for frame_index in range(60):
        signal = analysis()
        signal.timestamp_ns = frame_index
        frame_60 = at_60.render(
            signal, configuration, 1.0, scroll_speed_pps=30.0,
            elapsed_seconds=1 / 60, elapsed_ns=elapsed_60[frame_index]
        )[0]
    for frame_index in range(100):
        signal = analysis()
        signal.timestamp_ns = frame_index
        frame_100 = at_100.render(
            signal, configuration, 1.0, scroll_speed_pps=30.0,
            elapsed_seconds=1 / 100, elapsed_ns=10_000_000
        )[0]
    assert np.count_nonzero(frame_60.sum(axis=1)) == np.count_nonzero(frame_100.sum(axis=1))