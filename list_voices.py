import pyttsx3
engine = pyttsx3.init()
voices = engine.getProperty('voices')
for v in voices:
    print(f"ID: {v.id}")
    print(f"Name: {v.name}")
    print("---")
