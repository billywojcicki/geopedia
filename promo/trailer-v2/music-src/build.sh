#!/bin/sh
# Score -> premaster -> master (-14 LUFS, true peak under -1.5 dBTP).
# Needs: Python with numpy, scipy, mido and pyfluidsynth; FluidSynth; ffmpeg;
# and MuseScore_General.sf2 (MIT), path in SF2.
set -e
T=$(cd "$(dirname "$0")/.." && pwd)
PY=${PY:-python3}
SF2=${SF2:?set SF2 to MuseScore_General.sf2}
mkdir -p "$T/work"
$PY -I "$T/music-src/score.py" "$SF2" "$T/work"
cp "$T/work/cues.json" "$T/music/cues.json"
DURATION=30 $PY -I "$T/music-src/master.py" "$T/work/premaster.wav" "$T/music" "$T/work"
rm -f "$T/music/music.m4a"
