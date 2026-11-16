# Signal-Processing and Rendering Experiments

Last updated: 2026-11-16

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

**Purpose:** document current behavior before changing analysis or rendering code. E0 is the reference against which later variants are compared; it is not itself an algorithm change.

#### E0 test protocol

1. Use simulation only. Record the application revision, audio source, sample rate if known, input gain, analyzer/render settings, and selected simulation mode. Do not change these during an A/B comparison.
2. Use the same local audio source and exact time range for every run. Do not normalize or otherwise process the source between runs.
3. For each passage, capture the visualizer, dominant marker, Full-mode strip, and the five simulations. Record displayed dBFS and dominant frequency at the same checkpoints; note whether the value is instantaneous or an estimate.
4. Choose three checkpoints per passage: before the target event (if applicable), during its onset, and during the sustained passage. Record the target heard by ear before judging the rendering.
5. Rate the intended element's visibility and unwanted bass masking using the rubric below. Keep the notes and screenshots for the baseline and every later variant.

**Listening rubric**

| Score | Target element visibility | Unwanted bass / sub-bass masking |
|---|---|---|
| 0 | Not distinguishable in the rendering | No meaningful masking |
| 1 | Intermittent or weak | Present but does not obscure the intended element |
| 2 | Clearly present, but less prominent than intended | Frequently competes with or obscures the intended element |
| 3 | Clearly visible with the intended prominence | Dominates although it is not the intended focus |

Use the numbers to compare the same passage across variants, not as an objective measure of musical quality. Also note the specific failure (for example, Full stays red, hats fail to appear, or strings are absent); the score alone is not enough.

#### Reference passage matrix

The following are user-reported first-pass observations. They are valuable leads, not controlled measurements: settings and checkpoints were not consistently recorded. Fill the empty fields during the controlled baseline run.

| ID / source | Passage | Heard target / intent | First-pass analyzer and rendering observation | dBFS | Baseline checkpoint readings and rubric |
|---|---|---|---|---|---|
| M1 — Sub Focus, “Siren” | 0:00–0:20, before rolling techno-style bass enters | Hats/rides and snares; no need to emphasize sub-bass | No high-mid activity observed; Full was all red across bass/low-mid. Hats/rides and snares were detected very well. The passage became more chaotic after 0:20. | About -30 on average | To record: exact settings, three timestamps, dominant Hz, band display, Full color, five simulations, target-visibility and masking scores. |
| M2 — Sub Focus, “Siren” | 0:43–1:03 | Heavy bass synth in the drop; keep its audible prominence distinct from sub-bass | Low-mid activity followed the heavy bass synth in time and relative to itself, but looked weaker than it sounded. Dominant stayed in bass, around 47 Hz on average. | About -19 when the synth was playing; about -24 when it was not, with other drop elements also contributing | To record: exact settings, three timestamps, low-mid and bass display, Full color, five simulations, target-visibility and masking scores. |
| M3 — John Summit & Sub Focus, “Go Back” | 0:50–1:00 | Drums should stand out more than the comparatively subtle bass | Full was all red. High drums were missing or poorly detected despite being much more perceptually prominent than the bass. | About -18 to -22 dBFS for this passage only | To record: exact settings, three timestamps, high-band display, Full color, five simulations, drum visibility and bass-masking scores. |
| M4 — Netsky & Hybrid Minds, “Let Me Hold You” | Stages: piano only; piano + vocals; pad build-up; drop | Drums and audible string parts should be represented; ideally the strings should have a distinguishable display | Drums were detected but the display felt chaotic. Full was all red. The strings were audible but not detected as a distinct element. Reported levels by stage: piano only ~-30 dBFS; piano + vocals ~-25 dBFS; pad build-up ~-21 dBFS; drop ~-18 to -20 dBFS. The desired behavior is to represent the strings, not necessarily classify the instrument by name. | As reported above; verify in controlled run | For each stage, record its timestamp, exact settings, three checkpoints, mid/high-band display, Full color, five simulations, drum/string visibility and bass-masking scores. |
| M5 — Fisher, “Atmosphere” (parked; lower priority) | House drop / sections where kick and bass interact; exact stage boundaries TBD | Open hats should remain visible alongside the kick and bass | All observed open hats were detected. Bass readings around 47–189 Hz dominated after the drop, though less problematically than in DnB. Possible explanations are kick/bass sidechain interaction or bass notes filling gaps between kicks; neither is verified. | Do not use dBFS as a comparison criterion; reported values varied roughly -16 to -32 across stages. | Keep as a qualitative, lower-priority comparison. If revisited, label the musical stages and record exact checkpoints and the perceived kick/bass relationship. |
| M6 — Circadian, “Energy in Motion (AMC Remix)” | Intro 0:00–0:20; pre-build-up 0:21–0:44; build-up; drop 1:18–1:28 | In the drop, show the main bass/synth without letting the low bass mask it; drums also matter | Intro: average dominant ~100 Hz; Full nearly all red, with some drums missed. Pre-build-up: dominant ~47–100 Hz; Full all red with variations from drums/synths, attributed to a mild sidechain effect. Build-up: no notable issue reported; bass dominance seems expected. Drop: main bass/synth appeared on low-mid and high-mid bands and was detected roughly 70–80% of the time, but seemed too weak and attenuated by bass. Dominant reading ranged ~47–248 Hz. | Not recorded | For each listed stage, record exact settings, three checkpoints, band display, Full color, five simulations, main-synth/drum visibility and bass-masking scores. |

#### Isolated-sound observations

These readings help check the analyzer but do not by themselves establish which sound should control Full mode.

| Source | First-pass observation | Follow-up needed |
|---|---|---|
| Vital init preset (saw wave) | Dominant frequency: C0 ~23 Hz, C4 ~129 Hz, C7 ~527 Hz. The highest tested note was not identified; its reading was ~12,539 Hz. Level was about -19.1 dBFS across octaves 2–8 and about -21 dBFS for the highest notes. | Record note names, MIDI notes if available, gain, and stable readings. |
| FL Keys piano | C3 ~129 Hz. C7 fluctuated between ~1,043 and 2,109 Hz. Highest note B10 read ~12,574 Hz. | Repeat at fixed note duration and gain. |
| Hi-hat / DnB top loop | Hi-hat around 12 kHz; top-loop dominant readings above roughly 5–7 kHz. | Record the source, exact loop, and whether the value is the dominant marker or a band measurement. |
| Snare | Readings varied, roughly 250 Hz–2 kHz. | Repeat with several fixed hits and distinguish peak from sustained reading. |
| Kick | Most reported dominant readings were below 354 Hz, sometimes higher depending on the sound. A reported range of roughly 17.3–35 Hz needs clarification. | Determine whether 17.3–35 Hz refers to a spectral peak, filter setting, or another display; the analyzer's documented dominant-frequency search starts at 20 Hz. |
| Vocal | Some vocal readings appeared between about 707 Hz and 1.4 kHz, including female voices. | Record the excerpt, note whether the reading is fundamental or a harmonic, and do not infer gender or source identity from frequency alone. |

With silence, the level read about -120 dBFS. Notes were reported between roughly -25 and -75 dBFS, more often around -25 to -35 dBFS; octave changes did not appear to affect the level much. The dominant marker appeared to match the visual color consistently. Verify these observations with the same gain and record whether a value is a momentary reading or a time summary.

#### Cross-passage priorities to test

- The listener currently prefers not to visualize sub-bass because it is often part of the visual problem. Treat this as a preference to test, not a decision to remove low-frequency analysis.
- For liquid DnB, drums and pads are often the main visual priorities.
- A persistent ~47 Hz dominant reading should not automatically outweigh audible drums, pads, or strings. It is not yet known whether it is the bass fundamental, a harmonic, or another persistent component.
- Existing red color or dominant-frequency readings are not evidence that the bass is the most perceptually important element.

#### Deferred objectives (outside the current experiment focus)

- **Drum/instrument separation:** the long-term goal is to distinguish drums from instruments and synths. Defer source-separation work until after the current analysis and rendering experiments; it is not the main focus now.
- **Pitch movement within an octave:** a later goal is to show that an instrument played a higher note within the same octave. The current model is not expected to make that pitch difference perceptible on the LED strip. Defer this objective and *Friction — “Set Me Free”* as a test passage for it; do not mix it into the current bass/salience experiments.

#### Experiment log template

Use one row per passage, variant, and checkpoint. Keep the original baseline row rather than overwriting it.

| Run / variant | Passage ID and checkpoint | Build / settings / input gain | Change from baseline | dBFS / dominant Hz | Band values or screenshot | Intended element visibility (0–3) | Bass masking (0–3) | Full color / simulations / stability | Decision and notes |
|---|---|---|---|---|---|---:|---:|---|---|
| Baseline / A | M__ / before, onset, or sustained | Record exact values | None | Record | Attach or describe | Score | Score | Record | Reference |
| Candidate / B | M__ / same checkpoint as A | Record exact values | One change family only | Record | Attach or describe | Score | Score | Record | Keep / reject / revisit |

For each experiment E1–E8, copy the same passage IDs and checkpoints into the log. Change one parameter family at a time, compare A and B on the same input, and note tests and decision criteria from that experiment. This makes changes in measurement, color selection, and subjective salience separately traceable.

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
