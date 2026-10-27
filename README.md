# LuminaSnake Desktop

Last updated: 2026-10-27

## Purpose

LuminaSnake is a prototype for music-reactive LED strips. The intended system captures or plays audio on a computer, analyzes it, and creates an animation that can be sent to an LED strip through an ESP32. **For the current phase, the desktop application is the main project**: the goal is to understand, test, and improve the signal processing and visual output before returning to hardware integration.

The Python application can run without an ESP32. It displays the audio spectrum and simulates five virtual LED strips. The first simulation is the one that would be sent to the hardware; the other four make it possible to compare analysis modes.

## Run the application

From the repository root:

```powershell
uv sync --project desktop --dev
uv run --project desktop luminasnake-pc
```

The active audio-capture backend is currently implemented and tested first on Windows. To run without hardware, select **Windows output capture** or a local audio file, then click **Start**. **Connect ESP** is only needed for serial output.

The file picker supports WAV, FLAC, and MP3. MP3 decoding depends on the libsndfile build available in the environment.

Run the desktop tests:

```powershell
uv run --project desktop --group dev pytest desktop/tests
```

## Processing flow

```text
Windows audio output ─┐
                      ├─> audio.py ─> PCM queue ─> analyzer.py
Local audio file ─────┘                            │
                                                   ▼
                                     AnalysisFrame (models.py)
                                                   │
                                                   ▼
                                     engine.py: periodic rendering
                                                   │
                         ┌─────────────────────────┴────────────────────┐
                         ▼                                              ▼
             simulation.py / renderer.py                      Qt GUI / visualizers
             five virtual strips                               visualizer.py
                         │                                     strip_preview.py
                         └──────────────────┬───────────────────────────┘
                                            │ if the ESP is connected
                                            ▼
                             protocol.py ─> transport.py ─> serial port
```

Audio capture, analysis, rendering, and serial connection management use separate threads. For any one audio block, the order is still capture → queue → analysis. Rendering can process a previous block while capture receives the next one. The PCM queue is limited to eight blocks; if analysis falls behind, an older block can be discarded to keep latency down.

## Current audio analysis

The analyzer in `src/luminasnake_pc/analyzer.py` receives floating-point samples, converts stereo channels to mono, and maintains two sliding windows at 48 kHz:

- **4,096 samples (~85.3 ms):** RMS, peak, dBFS level, main FFT, dominant frequency, spectral centroid, and eleven band levels.
- **1,024 samples (~21.3 ms):** a shorter FFT used to track energy changes in three broad groups: 20–250 Hz, 250 Hz–6 kHz, and 6–20 kHz.

At 48 kHz, FFT-bin spacing is about 11.7 Hz for the 4,096-sample window and 46.9 Hz for the 1,024-sample window. A shorter window responds faster, but distinguishes nearby frequencies less precisely.

The current eleven bands use these boundaries in Hz: `20, 60, 120, 250, 500, 1000, 2000, 3500, 6000, 10000, 15000, 20000`. For each band, the analyzer calculates an RMS-like level from the power of its FFT bins. It then divides all band levels by the largest level in that frame. This is a relative comparison within one frame, not an absolute or perceptual loudness scale.

The analyzer also calculates:

- **Attack/onset:** a positive increase between consecutive short-window levels, with a threshold based on recent history. This identifies a change in a frequency region; it does not recognize a kick, clap, or instrument.
- **Emergence:** a comparison of each broad group's current level to its slowly moving envelope (`slow_groups`). This can indicate that a region is becoming more prominent without a very abrupt attack.
- **Preliminary BPM:** intervals between spectral-flux peaks. This is experimental and has not been qualified against a music corpus.

These calculations do not separate sound sources or fully model human perception. The current state and limitations are documented in [`experiments.md`](experiments.md).

## Rendering and visual controls

`src/luminasnake_pc/renderer.py` turns the analysis into an RGB head and a pixel history:

- **Full spectrum** uses the dominant frequency, with temporary priority for low, mid, or high onsets.
- **Bass**, **Low-mid**, **High-mid**, and **High** select the strongest band in their respective ranges.
- **Energy only** renders a white head whose brightness follows the level and audio changes.
- Brightness combines energy, onset, and emergence.
- A new head is inserted at the beginning of the strip, and older pixels move along it.
- Scroll speed is measured in pixels per second and is independent of render FPS.

The palette maps frequency to color: lower frequencies are red, while higher frequencies progress through cyan to white. Red in Full mode alone does not prove that deep bass is musically dominant; it can result from the selected dominant frequency or the palette.

## Modules

| File | Responsibility |
|---|---|
| `src/luminasnake_pc/app.py` | Creates the Qt application and main window. |
| `src/luminasnake_pc/__main__.py` | Entry point for `python -m luminasnake_pc`. |
| `src/luminasnake_pc/gui.py` | Window, controls, Qt signals, and status presentation. |
| `src/luminasnake_pc/models.py` | Shared types for modes, analysis frames, connection, and telemetry. |
| `src/luminasnake_pc/settings.py` | Settings, validation, and JSON persistence. |
| `src/luminasnake_pc/audio.py` | Windows loopback capture and audio-file playback. |
| `src/luminasnake_pc/engine.py` | Threads, queues, analysis/render orchestration, frame rate, and transport. |
| `src/luminasnake_pc/analyzer.py` | Signal measurements, FFT, bands, onset, emergence, and preliminary BPM. |
| `src/luminasnake_pc/renderer.py` | Palette, visual-value selection, and strip animation. |
| `src/luminasnake_pc/simulation.py` | Five independent renderers and physical-geometry adaptation. |
| `src/luminasnake_pc/visualizer.py` | Spectrum bars and dominant-frequency marker. |
| `src/luminasnake_pc/strip_preview.py` | Drawing the five virtual strips. |
| `src/luminasnake_pc/protocol.py` | Python-side RGB packets, COBS, and CRC. |
| `src/luminasnake_pc/transport.py` | Serial-port opening, handshake, keepalive, sending, and status reception. |
| `tests/` | Unit and regression tests for analysis, rendering, settings, simulation, and transport. |
| `pyproject.toml` | Dependencies, launch command, pytest configuration, and development tools. |

## Useful listening controls

- Use **One range per strip** to compare the five modes. Only virtual strip 1 represents physical output.
- **Visual intensity** controls overall brightness; **Scroll speed** controls pixel movement.
- FPS controls render cadence, not travel speed.
- Settings are saved automatically in the user's configuration directory.
- Transport counters are only available while the ESP is communicating. `Effective FPS` is calculated from the PC render cadence and does not guarantee that the physical LEDs displayed every frame.

## Current limitations

- Spectrum bars are normalized by the instantaneous maximum; they are not a loudness measurement.
- Full spectrum selects a dominant frequency or a broad onset class; it does not yet select the musical element that is most salient to a listener.
- Onsets are grouped into only three frequency regions and do not identify instruments.
- The Qt preview is not a photometric model of the physical LED strip.
- Audio capture, perceived rendering on real music, and hardware transport must be validated separately.

See [`experiments.md`](experiments.md) for the signal-processing roadmap, hypotheses, experiments, and validation criteria.
