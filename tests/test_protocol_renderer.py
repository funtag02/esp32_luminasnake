import numpy as np
import pytest

from luminasnake_pc.models import AnalysisFrame, VisualMode
from luminasnake_pc.protocol import MessageType, cobs_decode, cobs_encode, decode_packet, frame_packet
from luminasnake_pc.renderer import SnakeRenderer, frequency_color_name, frequency_rgb


def test_cobs_round_trip_with_zeroes():
    data = bytes([0, 1, 2, 0, 255, 0])
    assert cobs_decode(cobs_encode(data)) == data


def test_frame_packet_round_trip():
    frame = np.arange(360, dtype=np.uint16).astype(np.uint8).reshape(1, 120, 3)
    kind, sequence, delay, strips, leds, payload = decode_packet(frame_packet(7, 150_000, frame))
    assert (kind, sequence, delay, strips, leds) == (MessageType.FRAME, 7, 150_000, 1, 120)
    assert payload == frame.tobytes()


def test_corrupt_packet_is_rejected():
    packet = bytearray(frame_packet(1, 100_000, np.zeros((1, 120, 3), dtype=np.uint8)))
    packet[5] ^= 1
    with pytest.raises(ValueError):
        decode_packet(bytes(packet))


def test_silence_pushes_black_without_clearing_history():
    renderer = SnakeRenderer()
    loud = AnalysisFrame(
        timestamp_ns=0,
        rms=0.1,
        peak=0.2,
        dominant_hz=100.0,
        centroid_hz=100.0,
        bands=np.ones(11),
        loudness_level=0.8,
        silent=False,
    )
    silent = AnalysisFrame(
        timestamp_ns=1,
        rms=0.0,
        peak=0.0,
        dominant_hz=0.0,
        centroid_hz=0.0,
        bands=np.zeros(11),
        loudness_level=0.0,
        silent=True,
    )
    renderer.render(loud, VisualMode.FULL)
    frame = renderer.render(silent, VisualMode.FULL)
    assert np.all(frame[:, 0] == 0)
    assert np.any(frame[:, 1] != 0)


def test_mode_shortcuts_cover_expected_modes():
    assert [mode.value for mode in VisualMode] == [
        "full-spectrum", "bass", "low-mid", "high-mid", "high", "energy-only"
    ]


def test_kick_and_snare_transients_get_distinct_colors():
    renderer = SnakeRenderer()
    kick = AnalysisFrame(
        0, 0.1, 0.2, 2000.0, 2000.0, np.ones(11),
        loudness_level=0.5, onset_low=1.0, silent=False,
    )
    snare = AnalysisFrame(
        1, 0.1, 0.2, 2000.0, 2000.0, np.ones(11),
        loudness_level=0.5, onset_mid=1.0, silent=False,
    )
    kick_head = renderer.render(kick, VisualMode.FULL)[0, 0]
    snare_head = renderer.render(snare, VisualMode.FULL)[0, 0]
    assert kick_head[0] > kick_head[2]
    assert snare_head[2] > snare_head[0]


def test_same_frequency_louder_signal_is_brighter():
    quiet_renderer = SnakeRenderer()
    loud_renderer = SnakeRenderer()
    quiet = AnalysisFrame(
        0, 0.01, 0.02, 1000.0, 1000.0, np.ones(11),
        loudness_level=0.2, silent=False,
    )
    loud = AnalysisFrame(
        0, 0.5, 0.7, 1000.0, 1000.0, np.ones(11),
        loudness_level=0.9, silent=False,
    )
    assert quiet_renderer.render(quiet, VisualMode.FULL)[0, 0].sum() < loud_renderer.render(loud, VisualMode.FULL)[0, 0].sum()


def test_frequency_legend_matches_palette_anchors():
    assert frequency_color_name(100) == "Red"
    assert frequency_color_name(6000) == "Cyan to pale cyan"
    assert frequency_color_name(16_000) == "White"
    assert np.array_equal(frequency_rgb(300).astype(np.uint8), np.array([255, 0, 0], dtype=np.uint8))
    assert np.array_equal(frequency_rgb(15_000).astype(np.uint8), np.array([255, 255, 255], dtype=np.uint8))


def test_kick_has_brightness_headroom_over_loud_continuous_bass():
    bass_renderer = SnakeRenderer()
    kick_renderer = SnakeRenderer()
    bass = AnalysisFrame(
        timestamp_ns=0, rms=0.3, peak=0.4, dominant_hz=80.0, centroid_hz=100.0,
        bands=np.ones(11), loudness_level=1.0, silent=False,
    )
    kick = AnalysisFrame(
        timestamp_ns=0, rms=0.4, peak=0.9, dominant_hz=80.0, centroid_hz=100.0,
        bands=np.ones(11), loudness_level=1.0, onset_low=1.0, silent=False,
    )
    bass_head = bass_renderer.render(bass, VisualMode.FULL)[0, 0]
    kick_head = kick_renderer.render(kick, VisualMode.FULL)[0, 0]
    assert kick_head.sum() > bass_head.sum()
    assert kick_head[0] == 255


def test_one_kick_creates_a_short_decaying_segment_without_retriggering():
    renderer = SnakeRenderer()
    kick = AnalysisFrame(
        timestamp_ns=1, rms=0.4, peak=0.9, dominant_hz=80.0, centroid_hz=100.0,
        bands=np.ones(11), loudness_level=0.3, onset_low=1.0, silent=False,
    )
    first = renderer.render(kick, VisualMode.FULL)[0, 0].sum()
    second = renderer.render(kick, VisualMode.FULL)[0, 0].sum()
    third = renderer.render(kick, VisualMode.FULL)[0, 0].sum()
    assert first > second > third > 0
