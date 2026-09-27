#!/usr/bin/env python3
"""scriptcut: edit a video by editing its transcript. Built for coding agents.

    scriptcut transcribe talk.mp4            # talk.words.json + talk.edit.txt
    (delete lines or words in talk.edit.txt, by hand or with Claude Code / Codex)
    scriptcut plan talk.mp4                  # JSON cut list, nothing rendered
    scriptcut render talk.mp4 -o cut.mp4     # frame-accurate cut with ffmpeg

The edit file is plain text, one sentence per line, each line starts with its id.
Delete a line to cut the sentence. Delete words inside a line to cut those words.
Everything runs locally: stdlib + ffmpeg, openai-whisper only for `transcribe`.
MIT License.
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time

FILLERS = {"um", "uh", "er", "ah", "erm", "hmm", "mm", "uhm"}
LINE_RE = re.compile(r"^\[(\d+)\]\s?(.*)$")


def norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def paths(video):
    base = os.path.splitext(video)[0]
    return base + ".words.json", base + ".edit.txt"


# ---------- transcribe ----------

def transcribe(video, model="small", language=None):
    import whisper  # optional dependency, only needed here
    m = whisper.load_model(model)
    res = m.transcribe(video, word_timestamps=True, language=language, fp16=False)
    lines = []
    for seg in res["segments"]:
        words = [{"w": w["word"].strip(), "s": round(w["start"], 3), "e": round(w["end"], 3)}
                 for w in seg.get("words", []) if w["word"].strip()]
        if words:
            lines.append(words)
    return lines


def write_edit(lines, edit_path):
    with open(edit_path, "w") as f:
        f.write("# scriptcut edit file. Delete a line to cut it, delete words to cut them.\n")
        for i, words in enumerate(lines):
            f.write("[%04d] %s\n" % (i, " ".join(w["w"] for w in words)))


# ---------- plan ----------

def read_edit(edit_path):
    kept = {}
    with open(edit_path) as f:
        text = f.read().splitlines()
    for raw in text:
        m = LINE_RE.match(raw)
        if m:
            kept[int(m.group(1))] = m.group(2).split()
    return kept


def kept_words(lines, edit, drop_fillers=False):
    """Return (global index, word) for every original word that survives the edit."""
    out, base = [], 0
    for i, words in enumerate(lines):
        if i in edit:
            orig = [norm(w["w"]) for w in words]
            new = [norm(w) for w in edit[i]]
            sm = difflib.SequenceMatcher(a=orig, b=new, autojunk=False)
            for a, _, n in sm.get_matching_blocks():
                for k in range(a, a + n):
                    if not (drop_fillers and orig[k] in FILLERS):
                        out.append((base + k, words[k]))
        base += len(words)
    return out


def plan(lines, edit, max_gap=None, drop_fillers=False, pad=0.06, duration=None):
    """Kept words become time spans. Words that were neighbours in the original stay
    joined (their pause is kept) unless the pause is longer than max_gap."""
    kept = kept_words(lines, edit, drop_fillers)
    spans, prev = [], None
    for idx, w in kept:
        s, e = max(0.0, w["s"] - pad), w["e"] + pad
        if duration:
            e = min(e, duration)
        joined = prev is not None and idx == prev[0] + 1 and (
            max_gap is None or w["s"] - prev[1]["e"] <= max_gap)
        if joined or (spans and s <= spans[-1][1]):
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
        prev = (idx, w)
    total = sum(e - s for s, e in spans)
    return {"spans": [[round(s, 3), round(e, 3)] for s, e in spans],
            "kept_seconds": round(total, 3), "kept_words": len(kept),
            "total_words": sum(len(l) for l in lines)}


def probe_duration(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", video], capture_output=True, text=True)
    return float(out.stdout.strip() or 0)


# ---------- render ----------

def render(video, spans, out, crf=20):
    parts, labels = [], []
    for i, (s, e) in enumerate(spans):
        parts.append("[0:v]trim=%.3f:%.3f,setpts=PTS-STARTPTS[v%d];" % (s, e, i))
        parts.append("[0:a]atrim=%.3f:%.3f,asetpts=PTS-STARTPTS[a%d];" % (s, e, i))
        labels.append("[v%d][a%d]" % (i, i))
    graph = "".join(parts) + "".join(labels) + "concat=n=%d:v=1:a=1[v][a]" % len(spans)
    script = out + ".filter.txt"
    with open(script, "w") as f:
        f.write(graph)
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", video, "-filter_complex_script", script,
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", str(crf), "-c:a", "aac", "-b:a", "128k", out]
    subprocess.run(cmd, check=True)
    os.remove(script)


# ---------- cli ----------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="scriptcut", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transcribe", help="write <video>.words.json and <video>.edit.txt")
    t.add_argument("video")
    t.add_argument("--model", default="small")
    t.add_argument("--language")
    for name in ("plan", "render"):
        p = sub.add_parser(name)
        p.add_argument("video")
        p.add_argument("--edit", help="edit file (default <video>.edit.txt)")
        p.add_argument("--max-gap", type=float, help="shorten every pause to this many seconds")
        p.add_argument("--no-fillers", action="store_true", help="cut um, uh, er, ah")
        if name == "render":
            p.add_argument("-o", "--out", required=True)
    a = ap.parse_args(argv)
    words_path, edit_path = paths(a.video)
    if a.cmd == "transcribe":
        t0 = time.time()
        lines = transcribe(a.video, a.model, a.language)
        json.dump(lines, open(words_path, "w"))
        write_edit(lines, edit_path)
        print(json.dumps({"words": words_path, "edit": edit_path, "lines": len(lines),
                          "seconds": round(time.time() - t0, 1)}))
        return 0
    lines = json.load(open(words_path))
    edit = read_edit(a.edit or edit_path)
    p = plan(lines, edit, a.max_gap, a.no_fillers, duration=probe_duration(a.video))
    if a.cmd == "plan":
        print(json.dumps(p))
        return 0
    if not p["spans"]:
        print(json.dumps({"error": "edit keeps nothing"}))
        return 2
    t0 = time.time()
    render(a.video, p["spans"], a.out)
    print(json.dumps({"out": a.out, "spans": len(p["spans"]), "kept_seconds": p["kept_seconds"],
                      "seconds": round(time.time() - t0, 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
