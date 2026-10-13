# Trailer source

`../geopedia-trailer.mp4` is 29.6 s long, 1920x1080 at 30 fps, H.264 with AAC audio, and has an original score. None of this folder is used by the site.

## How it's made

1. **`capture.mjs`** drives the real site in headless Chromium on a virtual clock. Every frame has its camera, year and overlays set explicitly. The renderer waits for map tiles, borders and data at each cut, then captures a frame. Motion is perfectly smooth on any machine.
2. **`supervise.mjs`** renders every missing frame in 60-frame chunks, a few at a time, each in a fresh browser. A chunk that stalls is restarted from its first missing frame.
3. **`shots.json`** is the edit:
   - `shots` has one entry per cut: a time range, a camera move (`from`/`to` with centre, zoom, bearing and year), `chrome` (`clean`, `timeline` or `full`) and `bigYear`.
   - `texts` holds every line of copy with its timing.
4. **`encode.sh`** muxes the frames with `music/music.wav` into the MP4.

## Rendering

```
npm install playwright            # once, in this folder
python3 -m http.server 8766 -d ../..   # or any static server on the repo root (url in shots.json)
node supervise.mjs shots.json frames 3
sh encode.sh frames ../geopedia-trailer.mp4
```

Two environment variables control the browser:
- `CHROME` points at a Chromium binary if you're not using Playwright's own.
- Rendering uses software GL by default, so frames look the same everywhere. `SOFTWARE_GL=0` uses the GPU instead.

## Changing the copy

1. Edit the `html` of an entry in `texts`, and adjust its `t0`/`t1` if needed.
2. Delete the frames that line covers. At 30 fps, frame = seconds x 30.
3. Run `supervise.mjs` again: it only renders missing frames.
4. Run `encode.sh`.

Cuts land on the score's bars. At 100 BPM a bar is 2.4 s, so bars start at 0, 2.4, 4.8 and so on. The big end hit is at 26.4 s. Every beat, bar and section is listed in `music/cues.json`.

## The score

`music/` holds the score:
- `score.mid`
- `music.wav`, at -14 LUFS with a true peak of -1.6 dBTP
- the cue sheet
- `notes.md`, with the structure, instruments and licence

`music-src/build.sh` regenerates the score. The melody and harmony are written in `compose.py` with mido. The audio is rendered with TinySoundFont and FluidSynth from the MuseScore General soundfont (MIT), then mixed and mastered in numpy.

## Credits

- Music: an original cue written for Geopedia, rendered with the MuseScore General soundfont (MIT; see `music/notes.md`).
- Fonts: Cinzel and EB Garamond (SIL Open Font License; see `fonts/`). Inter is used too and is also OFL.
- Map data: OpenStreetMap contributors, Natural Earth, Wikidata and Wikipedia.
- Historical borders: historical-basemaps (GPL-3.0) and CShapes 2.0 (CC BY-NC-SA 4.0).
