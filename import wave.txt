import wave
import pyaudio
import os

p = pyaudio.PyAudio()
folder = "samples/aria"

files = sorted(os.listdir(folder))
total = len(files)

for idx, fname in enumerate(files):
    filename = os.path.join(folder, fname)
    print(f"\nPlaying {idx+1}/{total} — {fname}")

    with wave.open(filename, "rb") as wf:
        stream = p.open(
            format=p.get_format_from_width(wf.getsampwidth()),
            channels=wf.getnchannels(),
            rate=wf.getframerate(),
            output=True
        )
        data = wf.readframes(1024)
        while data:
            stream.write(data)
            data = wf.readframes(1024)
        stream.stop_stream()
        stream.close()

    choice = input("Enter=keep  b=delete: ")
    if choice.lower() == "b":
        os.remove(filename)
        print(f"Deleted {fname}")

p.terminate()
print(f"\nDone! Run: python train_aria.py")