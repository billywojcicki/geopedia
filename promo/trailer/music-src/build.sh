#!/bin/sh
# Full pipeline: compose -> render stems -> mix -> master -> analyze
set -e
# Needs: Python with numpy, scipy, matplotlib, mido and tinysoundfont; FluidSynth;
# ffmpeg; and MuseScore_General.sf2 (MIT), path in SF2.
T=$(cd "$(dirname "$0")/.." && pwd)
S="$T/music-src"
PY=${PY:-python3}
SF2=${SF2:?set SF2 to MuseScore_General.sf2}
mkdir -p "$T/work/analysis"
cd "$T/work"
$PY $S/compose.py $T/music
$PY $S/render_stems.py $T/music/score.mid "$SF2" $T/work/stems_raw.npz > $T/work/analysis/render_log.txt 2>/dev/null
$PY $S/mix.py $T/work/stems_raw.npz $T/music/score.mid $S/render_stems.py $T/work/premaster.wav $T/work/analysis
$PY $S/master.py $T/work/premaster.wav $T/music $T/work
$PY $S/analyze.py $T/music/music.wav $T/work/analysis/final.png $T/music/cues.json
$PY $S/pianoroll.py $T/music/score.mid $T/work/analysis/pianoroll.png
