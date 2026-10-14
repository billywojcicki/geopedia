# Trailer v2

30 s, 1920x1080, 30 fps, with an original 80s synth score. None of this folder is used by the site.

## The cut

| Time | What happens |
|---|---|
| 0 to 4 s | Comets race through space toward a dark Earth. |
| 4 to 8 s | A 2001-style dawn: the sun crests the horizon to timpani and brass, and "3000 BC" appears. |
| 8 s | The lead comet hits Mesopotamia. Flash, shockwave, drop. |
| 8 to 24 s | One continuous shot: the globe spins a full turn east and pulls back while the years run from 3000 BC to today. Time flies when history is sparse and slows as it gets dense. Fourteen callouts pop on the beat. |
| 24 to 27 s | Every era at once, and the copy. |
| 27 to 28 s | The world collapses into a point. |
| 28 to 30 s | The logo. |

The finished video is `../geopedia-trailer-v2.mp4` (43 MB).

## Files

- `cut.json` is the edit: timings, camera keyframes, the year curve, callouts and copy.
- `cut.mjs` turns the edit into camera, year and look at any moment.
- `overlay.js` and `overlay.css` draw everything over the map: the comets, the sun, the impact, the year counter, the timeline strip, callouts, copy, the implosion and the end card.
- `capture.mjs` drives the real site in headless Chromium and saves one JPEG per frame (quality 95).
- `supervise.mjs` renders the missing frames in chunks, a few browsers at a time, and restarts any chunk that stalls. Missing frames can be sparse: the frames of a 15 fps draft are the even frames at 30 fps, so a draft is never wasted.
- `encode.sh` muxes the frames and `music/music.wav` into the MP4 (about 43 MB), with a soft glow.
- `music-src/` builds the score (see below).

## Rendering

```
npm install playwright                    # once, in this folder
python3 -m http.server 8766 -d ../..      # or any static server on the repo root
sh fetch-images.sh                        # callout photos into cache/
FPS=15 node supervise.mjs draft 3         # a quick 15 fps draft
FPS=15 sh encode.sh draft draft.mp4
node supervise.mjs frames 3               # the real thing, 30 fps
sh encode.sh frames ../geopedia-trailer-v2.mp4
```

`CHROME` points at a Chromium binary if you're not using Playwright's own. Rendering uses software GL by default so frames look the same everywhere; `SOFTWARE_GL=0` uses the GPU. EB Garamond (year counter, end card) and Cinzel (payoff copy) are embedded from `fonts/`; the callout cards use Inter, which must be installed.

Frames are captured in real time, not on a virtual clock: each frame sets the camera, year and overlays itself, waits for tiles and data, and pins pop in by video time.

## Changing things

- **Copy**: edit `texts` in `cut.json`. Each line has its own `t0`, `t1` and fade.
- **Callouts**: edit `callouts` in `cut.json`: when it pops (`t`), which side the card goes (`side`), title, date, place and photo (a Wikimedia Commons path). Run `fetch-images.sh` for new photos. The score rings a bell at every callout time, so rebuild the music too.
- **Camera**: `rush.keys` holds `[time, longitude, latitude, zoom]` keyframes. Longitude keeps counting past 180 so the turn goes one way.

Then delete the frames for the changed times (frame = seconds x FPS) and run `supervise.mjs` again: it only renders missing frames.

## The score

120 BPM, so a beat is 0.5 s and a bar 2 s. In D minor:
- The race opens on the hook.
- The dawn is a fanfare of rising fifths with timpani and organ, a nod to *Also sprach Zarathustra* (public domain).
- The drop brings back the hook.
- At 20 s it changes key up a whole step to E minor.
- The payoff runs E minor, C, G, D.
- It ends on E major at 28 s.

The synths are written in numpy (`music-src/synth.py`): drums with a gated-reverb snare, a galloping octave bass, a square arpeggio, supersaw pads, brass stabs, a saw lead and FM bells. Timpani, brass, horns, organ, strings, choir and orchestra hits come from the MuseScore General soundfont (MIT) through FluidSynth.

```
SF2=/path/to/MuseScore_General.sf2 sh music-src/build.sh
```

`music/cues.json` lists the sections, chords and bell times.

## Credits

- Music: an original cue written for Geopedia. Orchestral samples are from MuseScore General (MIT).
- Fonts: EB Garamond, Cinzel, Inter and Inter Display (SIL Open Font License; see `fonts/`).
- Map data: OpenStreetMap contributors, Natural Earth, Wikidata and Wikipedia.
- Historical borders: historical-basemaps (GPL-3.0) and CShapes 2.0 (CC BY-NC-SA 4.0).
- Callout photos: Wikimedia Commons; see each file's page for its author and licence.
