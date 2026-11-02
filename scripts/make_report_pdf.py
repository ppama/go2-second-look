#!/usr/bin/env python
"""Build the report PDF with Chrome: make_report_pdf.py OUT.pdf [--video URL]"""
import argparse
import base64
import html
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ('body{font:10.5pt/1.55 "Noto Sans CJK JP",sans-serif;margin:0}h1{font-size:17pt}h2{font-size:12.5pt;margin:14px 0 4px;'
       'border-bottom:1px solid #999}h3{font-size:11pt;margin:10px 0 3px}table{border-collapse:collapse;width:100%;margin:6px 0}'
       'th,td{border:1px solid #999;padding:3px 6px;text-align:left}th{background:#eee}p{margin:5px 0}@page{margin:18mm}')


def inline(text):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(text))


def to_html(lines):
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        head = re.match(r"(#+) (.*)", line)
        image = re.match(r"!\[(.*)\]\((.*)\)", line)
        if image:
            data = base64.b64encode((ROOT / "docs" / image[2]).read_bytes()).decode()
            out.append(f'<img alt="{html.escape(image[1])}" style="width:100%;margin-top:6px" src="data:image/png;base64,{data}">')
            i += 1
        elif head:
            out.append(f"<h{len(head[1])}>{inline(head[2])}</h{len(head[1])}>")
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows[2:])
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr>" + body + "</table>")
        elif re.match(r"(- |\d+\. )", line):
            tag = "ul" if line[0] == "-" else "ol"
            out.append(f"<{tag}>")
            while i < len(lines) and re.match(r"(- |\d+\. )", lines[i]):
                out.append("<li>" + inline(re.sub(r"^(- |\d+\. )", "", lines[i])) + "</li>")
                i += 1
            out.append(f"</{tag}>")
        else:
            if line.strip():
                out.append(f"<p>{inline(line)}</p>")
            i += 1
    return "".join(out)


p = argparse.ArgumentParser()
p.add_argument("out")
p.add_argument("--video", default="[link]")
args = p.parse_args()
text = (ROOT / "docs" / "REPORT_DRAFT.md").read_text().replace("[link]", args.video)
page = f'<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>Second Look</title><style>{CSS}</style></head><body>{to_html(text.splitlines())}</body></html>'
with tempfile.TemporaryDirectory() as tmp:
    source = Path(tmp) / "report.html"
    source.write_text(page)
    subprocess.run(["google-chrome", "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
                    f"--print-to-pdf={Path(args.out).resolve()}", f"--user-data-dir={tmp}/chrome", source.as_uri()], check=True, capture_output=True, timeout=60)
print("saved", args.out)
