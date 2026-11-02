#!/usr/bin/env python
"""Japanese video abstract: Japanese slides and subtitles, English generated narration.

make_video_abstract_ja.py OUT.mp4 --room-ref a.mp4 --room-after b.mp4
Narration text goes to the edge-tts voice service. Numbers come from the logs and docs/VLM_EVAL.md.
"""
import argparse
import asyncio
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from scout import videokit
from scout.videokit import FIT, SIZE, caption, concat, ffmpeg, font, slide, still

videokit.BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
videokit.REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
BOLD, REGULAR = videokit.BOLD, videokit.REGULAR
SPEED, VOICE = 2, "en-US-AriaNeural"
INK, MUTED, BG, ACCENT = "white", "#d0d4da", "#111418", "#4ea1ff"


def clip(room, camera, start, end, camera_start, label, out):
    cap = out.with_suffix(".png")
    caption(cap, label)
    graph = (f"[0:v]setpts=PTS/{SPEED},{FIT}[v];[2:v]setpts=PTS/{SPEED},scale=420:-2,drawbox=c=white:t=3[c];"
             f"[v][c]overlay=W-w-16:16[a];[a][1:v]overlay=0:{SIZE[1] - 56}[o]")
    ffmpeg("-ss", str(start), "-t", str(end - start), "-i", str(room), "-i", str(cap), "-ss", str(camera_start), "-t", str(end - start),
           "-i", str(camera), "-filter_complex", graph, "-map", "[o]", "-an", str(out))


def diagram(path):
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    d.text((90, 60), "手法", fill=INK, font=font(BOLD, 46))
    boxes = [("Go2の巡回", "決められた地点"), ("画像の保存", "基準と現在"), ("ローカルVLM", "比較"), ("点検ログ", "変化を記録")]
    w, h, gap, y = 230, 130, 50, 180
    for k, (top, sub) in enumerate(boxes):
        x = 75 + k * (w + gap)
        d.rounded_rectangle((x, y, x + w, y + h), 14, outline=ACCENT, width=3)
        d.text((x + 20, y + 28), top, fill=INK, font=font(BOLD, 28))
        d.text((x + 20, y + 76), sub, fill=MUTED, font=font(REGULAR, 22))
        if k < 3:
            d.line((x + w + 6, y + h / 2, x + w + gap - 8, y + h / 2), fill=MUTED, width=4)
            d.polygon([(x + w + gap - 6, y + h / 2), (x + w + gap - 20, y + h / 2 - 9), (x + w + gap - 20, y + h / 2 + 9)], fill=MUTED)
    for k, line in enumerate(["オドメトリで移動し、各地点で停止して画像を保存します。", "VLMは保存画像を読むだけで、ロボットに指令できません。", "基準と現在の画像は、1枚の左右並べ画像として渡します。"]):
        d.text((90, 370 + k * 52), line, fill=MUTED, font=font(REGULAR, 27))
    img.save(path)


def table(path):
    img = Image.new("RGB", SIZE, BG)
    d = ImageDraw.Draw(img)
    d.text((90, 50), "シミュレーション: 誤検出数", fill=INK, font=font(BOLD, 42))
    d.text((90, 118), "水準ごとに未使用の18地点。全手法が変化を6件中6件検出。ドリフトは仮定値。", fill=MUTED, font=font(REGULAR, 24))
    rows = [["ドリフト", "VLM", "学習済み検出器", "画素差分"], ["基準", "3 / 12", "5 / 12", "12 / 12"], ["2倍", "7 / 12", "6 / 12", "12 / 12"],
            ["4倍", "9 / 12", "11 / 12", "12 / 12"], ["8倍", "9 / 12", "11 / 12", "12 / 12"]]
    for k, row in enumerate(rows):
        for x, cell in zip((90, 330, 590, 900), row):
            d.text((x, 180 + k * 62), cell, fill=INK if k else ACCENT, font=font(BOLD if k == 0 or x == 330 else REGULAR, 28))
    img.save(path)


def split(ref, after, out):
    a, b = Image.open(ref).convert("RGB").resize((640, 360)), Image.open(after).convert("RGB").resize((640, 360))
    img = Image.new("RGB", SIZE, BG)
    img.paste(a, (0, 110))
    img.paste(b, (640, 110))
    d = ImageDraw.Draw(img)
    d.text((40, 30), "人が場面を変更", fill=INK, font=font(BOLD, 40))
    d.text((40, 480), "変更前", fill=ACCENT, font=font(BOLD, 26))
    d.text((680, 480), "変更後", fill=ACCENT, font=font(BOLD, 26))
    d.text((40, 530), "地点A: 岩を追加   地点B: 岩を移動   地点C: 物を除去", fill=MUTED, font=font(REGULAR, 27))
    img.save(out)


async def speak(text, out):
    import edge_tts

    await edge_tts.Communicate(text, VOICE, rate="+6%").save(str(out))


def seconds(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, check=True).stdout)


def stamp(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


p = argparse.ArgumentParser()
p.add_argument("out")
p.add_argument("--room-ref", required=True)
p.add_argument("--room-after", required=True)
args = p.parse_args()
logs = ROOT / "logs"
out_path = Path(args.out).resolve()

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    png = lambda name: tmp / f"{name}.png"
    slide(png("title"), "Second Look", ["Unitree Go2と視覚言語モデルによる", "作業現場の変化の検出", "", "ビデオアブストラクト。ロボットの映像は実機で2倍速です。"])
    slide(png("problem"), "現場は訪れるたびに変わる", ["作業現場の地図はすぐに古くなります。", "ロボットは同じ視点へ戻って見直せます。", "", "小さな停止誤差と本当の変化を区別できるでしょうか。"])
    diagram(png("method"))
    ffmpeg("-ss", "50", "-i", args.room_ref, "-frames:v", "1", str(tmp / "room_a.png"))
    ffmpeg("-ss", "55", "-i", args.room_after, "-frames:v", "1", str(tmp / "room_b.png"))
    split(tmp / "room_a.png", tmp / "room_b.png", png("change"))
    slide(png("real"), "実機の結果", ["前後比較: 6地点すべて正解。3件検出、誤検出は3件中0件。", "基準なしの単一画像: 変化3件をすべて見逃し。", "正解既知の画像ペア: 8件中8件正解。", "変化の種類の完全一致は3件中1件。危険フラグは3件中0件。", "モデル: ローカルのqwen3.6。変更あり1回と対照1回。"])
    slide(png("finding"), "重要な発見(シミュレーション)", ["2枚の画像を別々に渡すと、変化は12件中12件検出。", "しかし正解既知のペアは12件中7件のみ正解。", "モデルは主に地点ごとに同じ答えを返していました。", "", "1枚の左右並べ画像では、12件中12件正解。"])
    table(png("sim"))
    slide(png("limits"), "限界", ["1つの模擬現場での少ない標本です。", "VLMの結果は巡回後に保存画像から算出しました。", "帰還誤差はオドメトリで約0.1 m。真の誤差は未測定です。", "手持ちリモコン停止は未検証。ロボットは有線接続です。", "月面現場の点検は想定用途で、実証結果ではありません。"])
    slide(png("end"), "Second Look", ["推論のみのAIを使用。VLMは画像を読むだけで、", "ロボットに指令することはできません。"])
    clip(args.room_ref, logs / "go2_ref2" / "camera.mp4", 0, 44, 8, "巡回1: 3地点で基準画像を保存(実機、2倍速、右上はロボットのカメラ)", tmp / "p1.mp4")
    clip(args.room_after, logs / "go2_1" / "camera.mp4", 3, 52, 2.5, "巡回2: 同じ経路、変更後の場面(実機、2倍速、右上はロボットのカメラ)", tmp / "p2.mp4")

    # name, image or None for a clip, minimum seconds, narration, subtitle
    segments = [
        ("title", png("title"), 4, "Second Look. Finding what changed at a work site, with a Go2 and a vision language model.", "Second Look。Go2と視覚言語モデルで、作業現場の変化を見つけます。"),
        ("problem", png("problem"), 4, "Site maps go out of date. Can a robot tell a real change from a small stop error?", "現場の地図はすぐに古くなります。ロボットは小さな停止誤差と本当の変化を区別できるでしょうか。"),
        ("method", png("method"), 4, "The robot stops at each station and saves a view. A local model compares old and new views. It only reads images, and cannot command the robot.", "ロボットは各地点で停止して画像を保存します。ローカルモデルが新旧の画像を比較します。モデルは画像を読むだけで、ロボットには指令できません。"),
        ("p1", None, 0, "On the first patrol, the real robot saves a reference view at three stations. The inset shows its own camera, at double speed.", "1回目の巡回では、実機が3地点で基準画像を保存します。右上はロボット自身のカメラで、2倍速です。"),
        ("change", png("change"), 4, "Then a person changes the scene. The robot is not told what changed.", "次に人が場面を変更します。ロボットには何が変わったかを伝えません。"),
        ("p2", None, 0, "On the second patrol, the robot takes new views on the same route. The model compares them afterwards, from the saved frames.", "2回目の巡回では、同じ経路で新しい画像を撮ります。モデルは巡回の後、保存画像から比較します。"),
        ("A", logs / "go2_1" / "cards" / "A.png", 3, "At station A, it correctly reports an added rock.", "地点Aでは、岩の追加を正しく報告しました。"),
        ("B", logs / "go2_1" / "cards" / "B.png", 3, "At station B, it detects the change, but calls the moved rock removed.", "地点Bでは変化を検出しましたが、移動した岩を除去と報告しました。"),
        ("C", logs / "go2_1" / "cards" / "C.png", 3, "At station C, it detects a change, but names the moved blocks.", "地点Cでも変化を検出しましたが、挙げたのはブロックの移動でした。"),
        ("control", logs / "go2_2" / "cards" / "B.png", 3, "With no change, it reports none at all three stations.", "変更がない場面では、3地点すべてで変化なしと報告しました。"),
        ("real", png("real"), 5, "On the real robot, before and after comparison got six of six stations right. A single image missed all three changes. Change type was exact only once.", "実機では前後比較が6地点すべて正解でした。単一画像は変化を3件とも見逃しました。種類の完全一致は1回のみでした。"),
        ("finding", png("finding"), 5, "In simulation, two separate images caught every change, but failed known answer tests. One side by side picture passed all twelve.", "シミュレーションでは、2枚を別々に渡すと全変化を検出しましたが、正解既知の試験に失敗しました。1枚の左右並べ画像では12件すべて正解しました。"),
        ("sim", png("sim"), 4, "False alarms rise with drift. The model is close to a trained detector.", "誤検出はドリフトとともに増えます。モデルは学習済み検出器に近い性能です。"),
        ("simfig", ROOT / "docs" / "images" / "sim_results_ja.png", 4, "These are selected examples from MuJoCo.", "これらはMuJoCoから選んだ例です。"),
        ("limits", png("limits"), 5, "This is a small sample from one mock-up. True return error and the remote stop were not tested. Lunar use is intended, not demonstrated.", "これは1つの模擬現場での少ない標本です。真の帰還誤差とリモコン停止は未検証です。月面利用は想定であり、実証結果ではありません。"),
        ("end", png("end"), 3, "Second Look.", "Second Look"),
    ]

    parts, srt, t, cue = [], [], 0.0, 1
    for name, image, minimum, narration, subtitle in segments:
        audio = tmp / f"{name}.mp3"
        asyncio.run(speak(narration, audio))
        spoken = seconds(audio)
        video = tmp / f"{name}.mp4"
        filters = []
        if image is None:
            length = seconds(video)
            if spoken > length - 0.3:
                rate = spoken / (length - 0.3)
                filters = ["-af", f"atempo={rate:.3f}"]
                spoken /= rate
                print(f"{name}: narration sped up {rate:.2f}x")
        else:
            length = max(minimum, spoken + 0.5)
            still(image, length, video)
        final = tmp / f"{name}_av.mp4"
        ffmpeg("-i", str(video), "-i", str(audio), *filters, "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
               "-c:a", "aac", "-ar", "48000", "-ac", "2", "-t", str(length), str(final))
        parts.append(final)
        chunks = [c for c in re.findall(r"[^。]+。?", subtitle) if c.strip()]
        total, at = sum(map(len, chunks)), t + 0.1
        for chunk in chunks:
            span = spoken * len(chunk) / total
            srt.append(f"{cue}\n{stamp(at)} --> {stamp(at + span)}\n{chunk}\n")
            at += span
            cue += 1
        t += seconds(final)

    joined = tmp / "joined.mp4"
    concat(parts, tmp / "list.txt", joined)
    subs = out_path.with_suffix(".srt")
    subs.write_text("\n".join(srt))
    style = "FontName=Noto Sans CJK JP,FontSize=20,Outline=2,Shadow=0,MarginV=34,BorderStyle=1,PrimaryColour=&H00FFFFFF&,OutlineColour=&H00000000&"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", "joined.mp4", "-vf", f"subtitles='{subs}':force_style='{style}'", "-c:a", "copy", str(out_path)], cwd=tmp, check=True)
print("saved", out_path)
