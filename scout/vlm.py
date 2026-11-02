"""Before/after scene comparison. Any VLM failure returns an error record and never moves the robot."""
import base64
import io
import json
import os
import re
import time
import urllib.request

import numpy as np
from PIL import Image

COMPARE_PROMPT = """You are the inspection camera of a robot at site station "{name}".
Image 1 is the reference view saved on an earlier patrol. Image 2 is the same station now.
Viewpoints may differ slightly. Ignore small viewpoint shifts, lighting, shadows, image noise,
and footprints or tracks in the sand. An object that enters or leaves the view only at an image
edge has not changed: compare what both images can see. Report only physical objects that were
added, removed, moved, or fallen over.

Reply with JSON only, in this format:
{{"changed": true or false,
  "hazard": true or false,
  "changes": [{{"type": "added|removed|moved|fallen", "label": "<object>",
               "box_2d": [ymin, xmin, ymax, xmax]}}],
  "summary": "<one short sentence>"}}
box_2d is for image 2, as integers normalized to 0-1000. For a removed object, use where it was.
"hazard" means something could block a route or damage equipment."""

# For models that merge two images: one picture, reference on the left, current on the right.
SIDE_PROMPT = COMPARE_PROMPT.replace(
    "Image 1 is the reference view saved on an earlier patrol. Image 2 is the same station now.",
    "This picture has two halves split by a white line. The left half is the reference view saved on an "
    "earlier patrol. The right half is the same station now.",
).replace("box_2d is for image 2, as integers normalized to 0-1000.", "box_2d is for the right half alone, as integers normalized to 0-1000.")

SINGLE_PROMPT = """You are the inspection camera of a robot at site station "{name}".
You have only this current view. Does anything look out of place or hazardous?
Reply with JSON only: {{"changed": true or false, "hazard": true or false, "summary": "<one short sentence>"}}
Use "changed": true if anything looks out of place."""


def parse_reply(text):
    """Pull one JSON object out of a reply, which may have fences or text around it."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        raise ValueError("no JSON object in reply")
    data = json.loads(match.group(0))
    if not isinstance(data.get("changed"), bool) or not isinstance(data.get("hazard"), bool):
        raise ValueError("'changed' and 'hazard' must be booleans")
    changes = []
    for c in data.get("changes", []) or []:
        box = c.get("box_2d")
        valid = isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) and 0 <= v <= 1000 for v in box)
        changes.append({"type": str(c.get("type", "")), "label": str(c.get("label", "")), "box_2d": box if valid else None})
    return {"changed": data["changed"], "hazard": data["hazard"], "changes": changes, "summary": str(data.get("summary", ""))}


class GeminiVlm:
    backend = "gemini"

    def __init__(self, cfg):
        from google import genai
        from google.genai import types

        if not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY is not set")
        self.cfg, self.types = cfg, types
        self.client = genai.Client()
        self.calls = 0
        self.last_call = -1e9

    def _image(self, frame):
        width = self.cfg["image_width"]
        img = Image.fromarray(frame)
        return img.resize((width, round(width * img.height / img.width)), Image.Resampling.LANCZOS)

    def _ask(self, contents):
        config = self.types.GenerateContentConfig(
            temperature=self.cfg["temperature"],
            thinking_config=self.types.ThinkingConfig(thinking_budget=self.cfg["thinking_budget"]),
        )
        # Free-tier quota is daily: a rate-limit error is never retried, and a lost
        # station can be rerun from its saved frames with scripts/revlm.py.
        last = None
        for _ in range(self.cfg["retries"] + 1):
            wait = self.cfg["min_call_gap_s"] - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.monotonic()
            self.calls += 1
            try:
                reply = self.client.models.generate_content(model=self.cfg["model"], contents=contents, config=config)
                return {**parse_reply(reply.text), "raw": reply.text}
            except Exception as e:
                last = e
                if "429" in str(e):
                    break
        return {"error": repr(last)}

    def compare(self, before, after, name):
        return self._ask([self._image(before), self._image(after), COMPARE_PROMPT.format(name=name)])

    def single(self, after, name):
        return self._ask([self._image(after), SINGLE_PROMPT.format(name=name)])


class OllamaVlm:
    """Local model through Ollama, so no rate limit. It holds most of the GPU while loaded."""

    backend = "ollama"

    def __init__(self, cfg):
        self.cfg, self.model = cfg, cfg.get("ollama_model", "qwen3.6:latest")
        self.calls = 0

    def _image(self, frame):
        width = self.cfg.get("ollama_width", self.cfg["image_width"])
        img = Image.fromarray(frame)
        img = img.resize((width, round(width * img.height / img.width)), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, "JPEG", quality=90)
        return base64.b64encode(buffer.getvalue()).decode()

    def _side_by_side(self, before, after):
        gap = 8
        height, width = after.shape[:2]
        sheet = np.full((height, 2 * width + gap, 3), 255, np.uint8)
        sheet[:, :width] = np.array(Image.fromarray(before).resize((width, height)))
        sheet[:, width + gap:] = after
        return sheet

    def _ask(self, images, prompt):
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt, "images": images}], "stream": False,
                "think": False, "keep_alive": "2m", "options": {"temperature": self.cfg["temperature"], "num_predict": 500, "num_ctx": 8192}}
        request = urllib.request.Request("http://localhost:11434/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
        self.calls += 1
        try:
            with urllib.request.urlopen(request, timeout=170) as reply:
                text = json.load(reply)["message"]["content"]
            return {**parse_reply(text), "raw": text}
        except Exception as e:
            return {"error": repr(e)}

    def compare(self, before, after, name):
        if self.cfg.get("overlap"):
            from scout.align import overlap

            # No match: compare the raw views, because declining could hide a real change.
            before, after = overlap(before, after) or (before, after)
        if self.cfg.get("side_by_side"):
            return self._ask([self._image(self._side_by_side(before, after))], SIDE_PROMPT.format(name=name))
        return self._ask([self._image(before), self._image(after)], COMPARE_PROMPT.format(name=name))

    def single(self, after, name):
        return self._ask([self._image(after)], SINGLE_PROMPT.format(name=name))


class MockVlm:
    """Pixel difference for offline tests. Its output is never a VLM result."""

    backend = "mock"
    calls = 0

    def __init__(self, threshold=0.005):
        self.threshold = threshold

    def compare(self, before, after, name):
        if before.shape != after.shape:
            return {"error": "frame sizes differ"}
        diff = np.abs(before.astype(float) - after.astype(float)).mean(axis=2)
        score = float((diff > 40).mean())
        changed = score > self.threshold
        return {"changed": changed, "hazard": changed, "changes": [], "summary": f"MOCK pixel difference {score:.3f}"}

    def single(self, after, name):
        return {"changed": False, "hazard": False, "summary": "MOCK no single-frame check"}
