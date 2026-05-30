import qrcode
from PIL import Image, ImageDraw, ImageFont
import os

url = "https://aria-3e1da.web.app"
out = r"C:/Users/KIIT/.gemini/antigravity/brain/1e2f7c53-b3ab-4f8b-acc8-f4787a0ba59d/aria_qr.png"

qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=12, border=3)
qr.add_data(url)
qr.make(fit=True)

img = qr.make_image(fill_color="#00e5ff", back_color="#0b0b16")
img.save(out)
print("QR saved:", out)
