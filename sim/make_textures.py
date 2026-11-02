"""Station label textures for the sim scene."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "generated"


def build():
    OUT.mkdir(exist_ok=True)
    for letter in "ABC":
        img = Image.new("RGB", (256, 256), "white")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 190)
        except OSError:
            font = ImageFont.load_default(190)
        draw.text((128, 128), letter, fill="black", font=font, anchor="mm")
        img.save(OUT / f"label_{letter}.png")


if __name__ == "__main__":
    build()
