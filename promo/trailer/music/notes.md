# Geopedia trailer music: "Sweep of History" (original cue)

An original ~30 s orchestral cue for the Geopedia trailer: epic, warm and hopeful, with a sense of wonder. The melody and harmony were written for this project. They do not quote or imitate any existing theme, including the Civilization themes and "Baba Yetu".

| | |
|---|---|
| Files | `score.mid` (MIDI), `music.wav` (48 kHz, 16-bit stereo, TPDF dither), `music.m4a` (AAC-LC 256 kb/s, 48 kHz), `cues.json` |
| Length | 29.600 s (1,420,800 samples). The final chord rings out and fades over the last ~3 s; the last 1.0 s is a smooth fade to digital silence. |
| Tempo / metre | 100 BPM, 4/4, fixed (beat = 0.600 s, bar = 2.400 s). Beat *n* is at *n* x 0.6 s. |
| Key | D major, with a modal-mixture cadence (Bb to C to D, i.e. bVI-bVII-I) into the final chord |
| Loudness | music.wav: -14.0 LUFS integrated, true peak -1.6 dBTP. music.m4a: -14.1 LUFS, -1.5 dBTP. LRA about 9 LU (ffmpeg ebur128) |

## Structure (times in seconds)

| Section | Bars | Time | What happens |
|---|---|---|---|
| intro | 1 | 0.0 - 2.4 | High string tremolo (D add9), celesta twinkles, choir "ooh" pad and a low D pedal. A soft timpani roll and cymbal swell build into bar 2. |
| journey | 2 - 8 | 2.4 - 19.2 | 3+3+2 ostinato on cellos and basses, with taiko, timpani and a soft triangle. The main horn melody enters at 2.4. Every downbeat is accented. Layers are added at 7.2 (shaker, off-beat timpani) and 12.0 (phrase 2: violins double the horns, violas, choir "aahs", snare, splash). Bar 8 (16.8) is a dominant build: rolls, a viola run and a harp glissando. |
| climax | 9 - 11 | 19.2 - 26.4 | Crash and full orchestra at 19.2. The melody is in octaves: violins, horns, and trombones an octave below the horns. Trumpets, tuba and full choir join. Bar 11 (24.0) is the Bb to C cadence, with a drum and low-string fill from 25.8. Sustained parts release at 26.16, leaving a short breath before the hit. |
| endCard | 12 - | 26.4 - 29.6 | **endHit at 26.4**: timpani, bass drums, taiko and crash on a full D major chord, plus a rolled harp chord. The chord rings and decays under the logo, with a celesta arpeggio and bell tree. The fade starts at 28.6. |

Chords by bar: 1 Dadd9 | 2 D | 3 Bm | 4 G, Em7 | 5 Asus4, A7 | 6 G (lydian colour) | 7 D/F#, Em7 | 8 G/A, A | 9 D | 10 Bm, G | 11 Bb, C | 12 D.

`cues.json` contains:
* every beat (`beatTimes`, and `beats` with bar and beat numbers)
* every bar start (`barTimes`, `bars`)
* `sections` (intro / journey / climax / endCard)
* named `markers`, including `endHit` = 26.4, `climaxHit` = 19.2 and `riser` = 16.8
* `downbeatAccents`

## Instruments (General MIDI channels in score.mid)

| Ch | Part | GM patch |
|---|---|---|
| 0 | Violins | 48 Strings |
| 1 | String pad | 49 Slow Strings |
| 2 | High tremolo | 44 Tremolo Strings |
| 3 | Cellos ostinato | 42 Cello |
| 15 | Violas ostinato | 41 Viola |
| 4 | Basses | 43 Contrabass |
| 5 | French horns | 60 |
| 6 | Trombones | 57 |
| 7 | Trumpets | 56 |
| 8 | Tuba | 58 |
| 10 | Choir aahs | 52 |
| 11 | Choir oohs | 53 |
| 12 | Harp | 46 |
| 13 | Celesta | 8 |
| 14 | Timpani | 47 |
| 9 | Percussion | GS/GM2 Orchestra Kit (program 48): bass drum, taiko, snare, crash, splash, triangle, shaker, bell tree |

Expression is written as CC11 swells, and section markers are written into the MIDI conductor track.

## How it was produced

1. **Composition**: `score.mid` is written by a Python script with mido (scripts in `../scripts/`, run all steps with `build.sh`). The script includes a harmony and semitone-clash check.
2. **Rendering**: each channel is rendered to its own stem. Strings, choir, harp, celesta and percussion use TinySoundFont 0.3.7. Brass uses FluidSynth 2.3.4 (pyfluidsynth), so that the SoundFont's velocity-to-timbre modulators apply.
   * Most sections are layered 2-3 times with +-4 to 8 cent detune, small onset offsets and different pan positions, which gives an ensemble width.
   * Brass and short-release strings are rendered note by note with a smooth custom release, so no note-off clicks.
   * Slow-attack patches are shifted 10-60 ms earlier so they speak on the beat.
3. **Mix** (numpy/scipy):
   * CC11 is applied as a smoothed gain curve, using the GM 40·log10 law.
   * Expression-dependent high-band "brightness" for strings and brass.
   * Per-stem EQ and orchestral seating pan.
   * Stems are balanced automatically to target K-weighted levels per section.
   * True-stereo convolution hall reverb: a synthetic, frequency-dependent IR with RT60 about 2.7 s at low frequencies and 0.8 s at 8-16 kHz, early reflections and 24 ms pre-delay.
   * Mono below 140 Hz, slight extra width above.
   * Gentle master EQ and 2:1 glue compression (about 0.6 dB average gain reduction in the climax).
4. **Master**:
   * Gain, then a 4x-oversampled true-peak look-ahead limiter. It reduces gain by more than 1 dB only on a few climax hits and the endHit, at most about 3.4 dB.
   * ffmpeg `loudnorm`, two-pass (I = -14, TP = -1.5, LRA = 20), stayed in **linear** mode.
   * A +0.1 dB trim to land at exactly -14.0 LUFS on ebur128.
   * 16-bit TPDF dither, then AAC 256k.

## SoundFont and licence

* **MuseScore_General.sf2 v0.2** by S. Christian Collins. Downloaded from https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/. SHA-256 `ee51d2c4b1525e70f19a45909c4fd7a2e26d91d115fa89dbf5a6bc413d8b9bf3`.
* **Licence: MIT.** This permits commercial use, modification and redistribution, including the rendered audio in a video. The SoundFont itself is not redistributed here.
* Required acknowledgement (include in credits or "About" if convenient): *Instrument samples: MuseScore_General SoundFont (MIT): FluidR3 (c) 2000-2002, 2008 Frank Wen; FluidR3Mono (c) 2014-17 Michael Cowgill; adaptation (c) 2018-19 S. Christian Collins; Temple Blocks (c) 2002 Ethan Winer; Drumline Cymbals (c) 2016 Michael Schorsch.*
* The MIT permission notice: Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

## Notes for the editor

* Cut on any value in `beatTimes`. The strongest cut points are the downbeats in `downbeatAccents`, with 19.2 (crash) and 26.4 (endHit) the biggest.
* The AAC file carries standard encoder-delay metadata. Most editors align it sample-accurately; if in doubt, use the WAV for the edit.
