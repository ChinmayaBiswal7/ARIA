import pygame

try:
    pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=4096)
    print("Direct Pygame mixer init succeeded.")
    pygame.mixer.quit()
except Exception as e:
    print("Direct init error:", e)
