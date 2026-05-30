# record_samples.py — run this and say "Aria" 50 times

import pyaudio
import wave
import os
import time

os.makedirs("samples/aria", exist_ok=True)

try:
    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=480
    )
except Exception as e:
    print(f"Error initializing PyAudio. Make sure your microphone is connected and configured: {e}")
    exit(1)

print("Say 'Aria' clearly — recording 50 samples.")
print("Press Enter before each recording.\n")

for i in range(50):
    try:
        input(f"Sample {i+1}/50 — Press Enter then say 'Aria'")
        time.sleep(0.3)
        frames = []
        # Record for ~1.6s (53 chunks of 480 samples @ 16kHz)
        for _ in range(53):
            data = stream.read(480, exception_on_overflow=False)
            frames.append(data)
        
        filename = f"samples/aria/aria_{i+1:03d}.wav"
        with wave.open(filename, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"".join(frames))
        
        print(f"  Saved {filename}")
    except KeyboardInterrupt:
        print("\nRecording aborted by user.")
        break
    except Exception as e:
        print(f"Error capturing sample: {e}")

stream.stop_stream()
stream.close()
p.terminate()
print("\nDone! Please run 'python train_aria.py' next to train your model.")
