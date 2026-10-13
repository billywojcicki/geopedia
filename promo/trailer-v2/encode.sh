#!/bin/sh
# Frames + score -> MP4 (1920x1080, 30 fps, H.264 High, AAC 256k), with a
# soft glow over the picture. No film grain: it triples the file size, and X
# re-encodes uploads, which smears it away anyway.
#   sh encode.sh frames out.mp4          (FPS=15 for a 15 fps draft)
set -e
FRAMES=${1:-frames}
OUT=${2:-geopedia-trailer.mp4}
FPS=${FPS:-30}
DIR=$(dirname "$0")
ffmpeg -y -loglevel error \
  -framerate "$FPS" -i "$FRAMES/f%04d.jpg" \
  -i "$DIR/music/music.wav" \
  -filter_complex "[0:v]format=gbrp,split[a][b];[b]gblur=sigma=14[g];[a][g]blend=all_mode=screen:all_opacity=0.16,format=yuv420p[v]" \
  -map "[v]" -map 1:a \
  -c:v libx264 -preset slow -crf 17 -maxrate 16M -bufsize 32M -profile:v high -tune film -r 30 -g 60 \
  -c:a aac -b:a 256k -ar 48000 \
  -shortest -movflags +faststart "$OUT"
ffprobe -v error -show_entries format=duration,size:stream=codec_name,width,height,r_frame_rate -of compact "$OUT"
