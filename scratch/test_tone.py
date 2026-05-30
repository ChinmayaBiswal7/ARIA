import time
import numpy as np
import pygame

def generate_tone(frequency, duration=0.3, sample_rate=44100):
    pygame.mixer.init(frequency=sample_rate, size=-16, channels=2)
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    envelope = np.exp(-4 * t / duration)  # decay envelope
    wave = np.sin(2 * np.pi * frequency * t) * envelope * 16384  # lower volume (16384 instead of 32767)
    wave = wave.astype(np.int16)
    stereo_wave = np.column_stack((wave, wave))
    sound = pygame.sndarray.make_sound(stereo_wave)
    return sound

def main():
    print("Generating sounds for C, E, G (major triad)...")
    c_note = generate_tone(261.63) # C4
    e_note = generate_tone(329.63) # E4
    g_note = generate_tone(392.00) # G4
    
    print("Playing C...")
    c_note.play()
    time.sleep(0.4)
    print("Playing E...")
    e_note.play()
    time.sleep(0.4)
    print("Playing G...")
    g_note.play()
    time.sleep(0.4)
    
    print("Done.")

if __name__ == "__main__":
    main()
