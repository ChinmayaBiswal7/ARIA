# -*- coding: utf-8 -*-
import sys
import os
import time
import asyncio
import edge_tts
import pygame
import speech_recognition as sr
import numpy as np

async def generate_speech(text, filename):
    communicate = edge_tts.Communicate(text, 'en-US-AriaNeural')
    await communicate.save(filename)

def main():
    print("=== Testing Audio Output (Edge-TTS + Pygame) ===")
    filename = "test_greeting.mp3"
    try:
        if os.path.exists(filename):
            os.remove(filename)
    except Exception:
        pass
        
    try:
        asyncio.run(generate_speech("Hello, I am testing the audio playback system.", filename))
        print("Speech generated successfully.")
    except Exception as e:
        print(f"Edge-TTS generation failed: {e}")
        return

    try:
        pygame.mixer.init(frequency=24000)
        print("Pygame mixer initialized at 24000 Hz.")
        pygame.mixer.music.load(filename)
        print("Playing audio...")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        pygame.mixer.music.unload()
        print("Audio playback completed.")
    except Exception as e:
        print(f"Pygame mixer playback failed: {e}")

    print("\n=== Testing Audio Input (SpeechRecognition + PyAudio) ===")
    r = sr.Recognizer()
    try:
        mic = sr.Microphone()
        print("Microphone device initialized successfully.")
        print("Listening for 3 seconds — please make some noise...")
        with mic as source:
            r.adjust_for_ambient_noise(source, duration=1.0)
            print("Calibrated ambient noise. Speak now...")
            audio = r.listen(source, timeout=3.0, phrase_time_limit=3.0)
        
        raw_bytes = audio.get_raw_data()
        audio_np = np.frombuffer(raw_bytes, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_np.astype(np.float32) ** 2)) if len(audio_np) > 0 else 0.0
        print(f"Recorded audio successfully. Duration: {len(raw_bytes)/(audio.sample_rate*audio.sample_width):.2f}s, RMS: {rms:.2f}")
        if rms > 10.0:
            print("Microphone test PASSED! It captured your voice successfully.")
        else:
            print("Microphone test FAILED: Captured signal is silence.")
    except Exception as e:
        print(f"Microphone test failed: {e}")

if __name__ == "__main__":
    main()
