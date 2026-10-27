# Signal-Processing and Rendering Experiments

Last updated: 2026-10-27

## Goal and scope

This document describes the **Python desktop** side of LuminaSnake. The overall prototype aims to create a music-reactive LED strip; during this phase, the desktop application is the main project. The analysis and simulated rendering should be tuned before physical hardware behavior is treated as the reference.

The primary artistic goal is to make the elements a listener perceives as important stand out at a given moment: drums, claps, vocals, melody, synths, or bass, depending on the passage. A strong bass or kick should remain visible when it genuinely dominates, but continuous low-frequency energy should not systematically mask everything else. Full mode should produce a readable, musically convincing animation rather than simply display the strongest FFT bin.

This document distinguishes:

- **Observed state:** behavior already present in the code.
- **Hypothesis:** an explanation or direction to test, not yet demonstrated.
- **Proposed experiment:** an isolated change to compare before adopting a solution.

## Current state

### Active data path

1. `audio.py` captures Windows loopback audio or reads and plays blocks from a file.
2. `engine.py` puts blocks into a bounded PCM queue, then a worker thread analyzes them with `Analyzer`.
3. `analyzer.py` produces an `AnalysisFrame` containing level, dominant frequency, centroid, eleven bands, three onsets, three emergence values, and preliminary BPM.
4. The render thread in `engine.py` passes an analysis frame to `SimulationBank`.
5. `simulation.py` calls an independent renderer for each virtual strip.
6. `renderer.py` chooses brightness and color and advances the RGB pixel history of the snake.
7. `strip_preview.py` displays the five simulations, while `visualizer.py` displays the eleven frequency bands.
8. If transport is connected, `engine.py` converts virtual strip 1 to a physical frame, `protocol.py` packages it, and `transport.py` sends it over the serial port.

### Current analysis algorithm

`Analyzer.process` uses sliding windows:

- 4,096 samples at 48 kHz (~85.3 ms) for the main statistics and long-window FFT.
- 1,024 samples (~21.3 ms) for an FFT of three onset/emergence groups.

The FFT uses `numpy.fft.rfft` after multiplication by a Hann window. The dominant frequency is the largest-magnitude bin between 20 Hz and 20 kHz. The centroid is calculated as the center of gravity of spectral power.

The eleven bands have boundaries in Hz at `20, 60, 120, 250, 500, 1000, 2000, 3500, 6000, 10000, 15000, 20000`. Each band is calculated from the power of its bins; the spectrum value is the root-mean-square level. The eleven values are then divided by their instantaneous maximum.

Onsets are positive level changes in three broad groups (20–250 Hz, 250 Hz–6 kHz, and 6–20 kHz), compared with the previous block and then evaluated against a historical median. Emergence compares the current level to a slow envelope for each group. The renderer temporarily retains onsets and combines level, onset, and emergence to determine brightness.

### Current visual algorithm

- Continuous frequency-to-RGB palette: red in bass/low-mid frequencies, then magenta/violet, blue, cyan, and white.
- Full spectrum: dominant frequency, unless a low, mid, or high onset takes priority.
- Partial modes: strongest band within the selected range.
- Energy only: white, with no frequency-based color selection.
- The head enters at the first pixel; the strip history shifts according to a pixels-per-second speed independent of FPS.
- Dominant frequency, head color, spectrum bars, and strip simulation are separate displays. A high red bar or red head is not a direct measurement of “what the ear hears most.”

### Strengths

- Understandable separation between capture, analysis, rendering, UI, and transport.
- Analysis does not run in the capture thread, and bounded queues help limit latency.
- Two window lengths provide a trade-off between frequency resolution and responsiveness.
- Deterministic calculations and synthetic tests cover silence, tones, levels, onsets, and rendering.
- Five modes/simulations make it possible to compare frequency regions on the same audio.
- Pixel travel speed is independent of FPS; visual settings persist.
- Rendering can be evaluated without an ESP connection.

### Weaknesses and open questions

- Eleven relatively broad ranges do not describe timbre and musical role in much detail.
- Normalizing each frame by its maximum loses absolute scale and can visually amplify a weak band.
- Current spectral level is not a complete psychoacoustic loudness estimate.
- The dominant bin does not necessarily represent the most salient frequency or instrument.
- Dominant frequency and Full-mode color may stay red for a piano note or low-mid harmonic even when no audible sub-bass is present.
- The three onset groups are broad: an increase in 250 Hz–6 kHz could come from a clap, vocal, piano, or synth.
- The system does not perform source separation, instrument classification, or auditory-masking analysis.
- The Full score combines total level, onset, and emergence using fixed coefficients. Color selection can follow a different rule from brightness selection.
- Thresholds, smoothing, and temporal memory have not yet been evaluated against representative passages annotated according to the artistic goal.
- Unit tests establish local properties, not subjective fidelity on Drum and Bass.
- BPM is preliminary and should not be treated as a ground-truth rhythm signal.

## Experimental principles

1. **Keep a baseline:** use the same settings, excerpts, source, and passage before and after a change.
2. **Change one family of parameters at a time:** frequency representation, normalization, change detection, Full-mode selection, or smoothing.
3. **Separate objectives:** diagnostic bars can show a stable measurement while the renderer uses a dynamic salience score.
4. **Test with synthetic data before listening:** silence, sine waves, tone mixtures, noise, impulses, and attacks over a continuous background.
5. **Compare against listener intent:** algorithms propose candidates; excerpts and human annotations determine whether they match the desired output.
6. **Do not equate frequency with instrument:** describe any frequency-based heuristic as a heuristic.
7. **Do not add commercial recordings to the repository.** Listening tests can use locally available, legally accessed files; keep timecodes and observations rather than the audio files.

For each listening test, record:

| Field | Example note |
|---|---|
| Excerpt and timecode | local track, 00:32–00:45 |
| Passage | vocal/piano intro, build-up, drop |
| What stands out by ear | entering clap, vocal, kick, synth motif |
| What stands out in the rendering | continuous red, cyan flash, no change |
| Attack and hold | too early/late, too short/long |
| Stability | stable color or flicker |
| Decision | better, unchanged, or worse than baseline |

Track names mentioned in discussion (for example *Closer* or *Air*) are personal listening examples, not project dependencies. Exact timecodes and observations should be filled in during testing.

## Proposed experiments

### E0 — Establish a rendering baseline

**Question:** What does the current version actually do in the reference passages?

**Procedure:**

1. Keep the current settings and use simulation only.
2. Try a piano/vocal intro, a build-up with claps/synths, a DnB drop, and a calm/acoustic passage.
3. For each passage, separately observe the spectrum, dominant marker, head color, and five simulations.
4. Note visible values (dBFS, dominant frequency, onsets) alongside what stands out subjectively.

**Expected result:** a reproducible list of cases and perceptual goals, not an algorithm change yet.

### E1 — Improve how the spectrum bars are interpreted

**Question:** Does the red dominance come from the color palette, the band grouping, or genuinely strong energy in those ranges?

**Variants to compare:**

- current relative spectrum (divided by its instantaneous maximum);
- dB levels with explicit, time-stable floor and ceiling;
- optionally, a per-octave relative view alongside the absolute view.

**Caution:** wider bands accumulate more energy. A narrow and a wide band should not be compared without specifying whether the measurement represents total energy, average per bin, or a width-compensated value.

**Measurements:** silence, equal-amplitude tones at different frequencies, pink/white noise, then music excerpts; visual stability of each band from frame to frame.

**Decision criterion:** the visualizer helps explain the levels without implying that the loudest band in a frame is automatically the most perceptually dominant element.

### E2 — Use more useful frequency bands

**Question:** Would finer, logarithmic bands better locate piano, vocals, claps, synths, and low-frequency elements?

**Proposal:**

- Keep the FFT; it is the method used to calculate frequency content.
- Change only the grouping of FFT bins in `analyzer.py`, using logarithmic boundaries or bands of comparable octave width.
- Produce per-band energy values and document the chosen width compensation.
- Temporarily keep the old fields or provide an adapter so the renderer does not break before it is migrated.

**Measurements:** correct localization of known synthetic tones, behavior at band boundaries, no gaps or duplicate bins, CPU load, then listening comparisons.

**Decision criterion:** better frequency differentiation without making bass appear to win artificially because of band grouping.

### E3 — Measure energy without per-frame normalization

**Question:** Would per-band energy in dB be more stable and interpretable?

**Candidate variant:**

1. Convert each band's energy to dB, using epsilon to avoid `log(0)`.
2. Apply a silence floor and a fixed display dynamic range.
3. Test any perceptual weighting separately; do not confuse it with automatic mix equalization.
4. Display levels consistently over time instead of always mapping the highest band to 100%.

**Caution:** no simple weighting curve perfectly models human perception across all levels, equipment, and mixes. Treat it as an experimental variant, not universal truth.

### E4 — Build a per-band salience score

**Question:** What rule makes an entering clap/synth stand out in a build-up while still showing a strong kick in a drop?

**Score components to explore for each band:**

- current absolute level or level in dB;
- recent increase relative to that same band (positive spectral flux);
- difference from a slow per-band background envelope;
- perceptual weighting or user preference, tested separately;
- simple masking by neighboring-band energy, only if experiments show that it helps.

Full mode could then select the band or group with the highest combined score. A strong low-frequency attack could stand out in a drop; a clear mid/high increase could take priority during a build-up even while continuous bass remains present.

**Important:** this is a salience heuristic, not stem separation. Different instruments can share the same spectrum.

**Criteria:**

- a one-off kick beats continuous bass only when its onset/contrast is genuinely important;
- a clap entering during a build-up can take visual priority despite a continuous low end;
- a continuous sound does not trigger a new attack on every frame;
- noise, fades, or global volume changes do not cause constant flashes.

### E5 — Tune attack and hold timing

**Question:** For how long should a new component influence color and brightness?

Compare:

- the current 1,024-sample short window (~21 ms);
- multiple window lengths or a multi-resolution measurement per band;
- fixed threshold versus threshold relative to recent background noise;
- explicit attack and release time constants instead of per-render-call decay;
- hysteresis between the current candidate and a new candidate to avoid color flicker.

**Measurements:** latency on a timestamped synthetic event, hold time, band-selection change rate on a stable sound, and ability to track closely spaced hits.

### E6 — Separate color, brightness, and movement decisions

**Question:** Should the same score choose both color and brightness?

Explore separate paths:

- **brightness:** total energy or energy contrast;
- **color:** the band with the highest salience;
- **movement/event:** detected attack or novelty, with a limited hold.

Compare this with the current renderer, where Full uses the dominant frequency or an onset class for color, while level, onsets, and emergence contribute to brightness.

### E7 — Create a small set of annotated reference passages

Create a table (without adding the audio files) of reference passages: intro, clap entry, transition, drop, break, and section with continuous bass. For each passage, note the desired events and their relative importance.

Automated tests can use non-copyrighted synthetic fixtures to verify DSP behavior; musical excerpts are for reproducible human evaluation. Do not qualify the BPM algorithm or an instrument detector without an appropriate dataset and metric.

### E8 — Validate robustness and cost

After each candidate change:

- run the desktop tests;
- check silence, low/high levels, finite values, dimensions, and band boundaries;
- measure analysis time per block and count queue drops;
- listen at fixed FPS and verify that pixels-per-second speed remains constant;
- compare virtual rendering before and after on exactly the same passages.

PC FPS alone does not prove that frames were received or displayed physically. ESP/USB/power stability is a separate validation outside the scope of this DSP plan.

## Recommended order

1. E0 — record a baseline and define visual criteria.
2. E1 — make the diagnostic spectrum more honest and readable.
3. E2, then E3 — improve band grouping and measurement scale.
4. E4 — experiment with per-band salience and define Full-mode behavior.
5. E5, then E6 — tune hold timing and separate color/brightness/event paths.
6. E7, then E8 — formalize reference passages and validate regressions and performance.

For each experiment, record its variant, parameters, passing tests, listened excerpts/timecodes, and decision (keep, reject, or revisit). Avoid stacking multiple DSP changes without comparisons; otherwise, it becomes difficult to tell what actually improved the result.

## Existing Python tests

The test suite is in `tests/` and can be run from the repository root:

```powershell
uv run --project desktop --group dev pytest desktop/tests
```

- `tests/test_settings_analyzer.py`: settings bounds/persistence, known tone, silence, amplitude effect, low/mid onset distinction, and kick over continuous bass.
- `tests/test_protocol_renderer.py`: COBS and frame round-trips, rejection of a corrupted packet, history during silence, mode identifiers, different onset colors, level/brightness relationship, palette anchors, kick headroom, and decay without retriggering.
- `tests/test_simulation.py`: independence of the five strips, disabling, geometry adaptation, and speed independent of FPS.
- `tests/test_transport.py`: DTR/RTS disabled, incompatible protocol rejection, disconnect not blocking on a simulated read, and handling of the Windows pySerial close race.
- `tests/test_protocol_vectors.py`: standard CRC32 vector and the COBS boundary at 254 nonzero bytes.

These tests cover code invariants, not musical perception on real tracks. New salience tests should verify the hypotheses in E4–E6 using known synthetic signals, then be complemented by comparative listening.
