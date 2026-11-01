#!/bin/bash
set -e

FRAMES_DIR="/home/krishna/Big_Data/demo_video/frames"
AUDIO_FILE="/home/krishna/Big_Data/demo_video/ambient_track.wav"
OUTPUT_MP4="/home/krishna/Big_Data/demo_video/final_demo.mp4"

# Generate concat demuxer file with exact segment timing
# 1. Slide 1 (Title & Motivation): 25s
# 2. Slide 2 (Architecture): 30s
# 3. Slide 3 (Popularity Bias & Pareto): 30s
# 4. Slide 4 (Live Smoke Pipeline): 30s
# 5. Slide 5 (Benchmark Matrix Results): 40s
# 6. Slide 6 (Limitations & Conclusion): 25s
# Total = 25 + 30 + 30 + 30 + 40 + 25 = 180s (Exactly 3:00)

CONCAT_FILE="/home/krishna/Big_Data/demo_video/slides_concat.txt"
cat << 'CONCAT_EOF' > "$CONCAT_FILE"
file 'frames/slide_01.png'
duration 25.0
file 'frames/slide_02.png'
duration 30.0
file 'frames/slide_03.png'
duration 30.0
file 'frames/slide_04.png'
duration 30.0
file 'frames/slide_05.png'
duration 40.0
file 'frames/slide_06.png'
duration 25.0
file 'frames/slide_06.png'
CONCAT_EOF

echo "Encoding 1920x1080 H.264 video with AAC stereo audio..."
ffmpeg -y -f concat -safe 0 -i "$CONCAT_FILE" \
       -i "$AUDIO_FILE" \
       -vf "fps=30,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \
       -c:v libx264 -preset medium -crf 18 -tune stillimage \
       -c:a aac -b:a 192k -ar 44100 \
       -t 180.0 \
       -movflags +faststart \
       "$OUTPUT_MP4"

echo "Video compilation complete: $OUTPUT_MP4"
