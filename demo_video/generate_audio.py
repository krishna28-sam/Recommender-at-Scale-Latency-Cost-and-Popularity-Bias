#!/usr/bin/env python3
"""
Generate a subtle, high-quality ambient background audio track of exactly 180.0 seconds
using mathematical harmonic synthesis (sine waves + soft harmonic chords + fade in/out).
"""
import numpy as np
import wave
import struct

sample_rate = 44100
duration = 180.0 # Exactly 180.0 seconds
num_samples = int(duration * sample_rate)

t = np.linspace(0, duration, num_samples, endpoint=False)

# Ambient harmonic progression: subtle, low-frequency warmth (peaceful presentation backdrop)
# Frequencies: A2 (110 Hz), E3 (164.81 Hz), C#3 (138.59 Hz), G#2 (103.83 Hz)
chord1 = 0.15 * np.sin(2 * np.pi * 110.0 * t) + 0.10 * np.sin(2 * np.pi * 164.81 * t)
chord2 = 0.12 * np.sin(2 * np.pi * 138.59 * t) + 0.08 * np.sin(2 * np.pi * 220.0 * t)

# Slow, calming modulation (breathing cycle: 0.1 Hz)
envelope_mod = 0.7 + 0.3 * np.sin(2 * np.pi * 0.08 * t)

audio = (chord1 + chord2) * envelope_mod

# 3-second fade-in and 3-second fade-out
fade_samples = int(sample_rate * 3.0)
fade_in = np.linspace(0, 1, fade_samples)
fade_out = np.linspace(1, 0, fade_samples)

audio[:fade_samples] *= fade_in
audio[-fade_samples:] *= fade_out

# Normalize to safe amplitude (-12 dB peak)
audio = audio / np.max(np.abs(audio)) * 0.25

# Convert to 16-bit PCM stereo
audio_int16 = (audio * 32767).astype(np.int16)
stereo_data = np.empty((num_samples * 2,), dtype=np.int16)
stereo_data[0::2] = audio_int16
stereo_data[1::2] = audio_int16

out_wav = "/home/krishna/Big_Data/demo_video/ambient_track.wav"
with wave.open(out_wav, 'wb') as wav_file:
    wav_file.setnchannels(2)
    wav_file.setsampwidth(2)
    wav_file.setframerate(sample_rate)
    wav_file.writeframes(stereo_data.tobytes())

print(f"Ambient presentation audio track successfully written: {out_wav} (180.0s)")
