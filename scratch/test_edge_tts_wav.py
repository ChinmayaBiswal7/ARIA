import os

pkg_dir = r"C:\Users\KIIT\AppData\Local\Programs\Python\Python313\Lib\site-packages\edge_tts"
for root, dirs, files in os.walk(pkg_dir):
    for file in files:
        if file.endswith(".py"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                if "audio-" in content or "format" in content.lower() or "riff" in content.lower():
                    # print matching lines
                    lines = content.split("\n")
                    for i, l in enumerate(lines):
                        if "audio-" in l or "format" in l.lower() or "riff" in l.lower() or "mp3" in l.lower():
                            if any(kw in l for kw in ["24khz", "16khz", "mp3", "riff"]):
                                print(f"{file}:{i+1}: {l.strip()}")
