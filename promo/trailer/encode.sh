#!/bin/sh
# Frames + score -> X-ready MP4 (1920x1080, 30 fps, H.264 High, AAC 256k).
#   sh encode.sh frames out.mp4
set -e
FRAMES=${1:-frames}
OUT=${2:-geopedia-trailer.mp4}
DIR=$(dirname "$0")
ffmpeg -y -loglevel error \
  -framerate 30 -i "$FRAMES/f%04d.png" \
  -i "$DIR/music/music.wav" \
  -c:v libx264 -preset slow -crf 16 -profile:v high -pix_fmt yuv420p -tune film \
  -vf "format=yuv420p" -r 30 -g 60 \
  -c:a aac -b:a 256k -ar 48000 \
  -shortest -movflags +faststart "$OUT"
ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate -of compact "$OUT"
