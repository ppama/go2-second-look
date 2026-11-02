"""Shared ffmpeg and slide helpers for the demo videos."""
import subprocess

from PIL import Image, ImageDraw, ImageFont

SIZE = (1280, 720)
FIT = f"scale={SIZE[0]}:{SIZE[1]}:force_original_aspect_ratio=decrease,pad={SIZE[0]}:{SIZE[1]}:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p"
BOLD, REGULAR = "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"


def font(name, size):
    return ImageFont.truetype(name, size)


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def slide(path, heading, lines):
    img = Image.new("RGB", SIZE, "#111418")
    draw = ImageDraw.Draw(img)
    draw.text((90, 150), heading, fill="white", font=font(BOLD, 48))
    y = 250
    for line in lines:
        draw.text((90, y), line, fill="#d0d4da", font=font(REGULAR, 28))
        y += 52
    img.save(path)


def still(image, seconds, out):
    ffmpeg("-loop", "1", "-t", str(seconds), "-i", str(image), "-vf", FIT, "-an", str(out))


def caption(path, text):
    img = Image.new("RGB", (SIZE[0], 56), "#111418")
    ImageDraw.Draw(img).text((24, 13), text, fill="white", font=font(REGULAR, 25))
    img.save(path)


def concat(parts, list_file, out):
    list_file.write_text("".join(f"file '{p}'\n" for p in parts))
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out))
