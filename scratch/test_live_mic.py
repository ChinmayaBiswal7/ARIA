# -*- coding: utf-8 -*-
import sys
import os
import time
import pyaudio
import numpy as np

def main():
    print("=== ARIA Microphone Level Monitor ===")
    print("This script displays real-time microphone volume levels to check if PyAudio")
    print("is receiving sound from your device. Press Ctrl+C to exit.\n")
    
    p = pyaudio.PyAudio()
    
    # Try to open the default input stream
    try:
        default_device = p.get_default_input_device_info()
        device_name = default_device.get('name')
        device_index = default_device.get('index')
        sample_rate = int(default_device.get('defaultSampleRate'))
        print(f"Using default input device: {device_name} (Index: {device_index})")
        print(f"Sample Rate: {sample_rate} Hz")
    except Exception as e:
        print(f"Error accessing default recording device: {e}")
        p.terminate()
        return

    chunk_size = 1024
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            input=True,
            frames_per_buffer=chunk_size
        )
    except Exception as e:
        print(f"Error opening audio stream: {e}")
        p.terminate()
        return

    print("\nStream opened. Speak into your microphone now...")
    print("Gage: [ - - - - - - - - - - - - - - - - - - - - ] (Value)")
    
    try:
        while True:
            try:
                # Read audio chunk
                raw_data = stream.read(chunk_size, exception_on_overflow=False)
                if not raw_data:
                    continue
                audio_np = np.frombuffer(raw_data, dtype=np.int16)
                if len(audio_np) == 0:
                    continue
                # Calculate RMS
                rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2))
                
                # Draw level meter bar (max 30 bars, scaled to 5000 RMS)
                num_bars = int(min(30, (rms / 5000.0) * 30))
                meter = "|" * num_bars + " " * (30 - num_bars)
                
                # Print level meter dynamically
                sys.stdout.write(f"\rLevel: [{meter}] ({rms:.1f})")
                sys.stdout.flush()
            except IOError:
                pass
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()
