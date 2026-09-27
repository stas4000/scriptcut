"""Build film.json (optional: put Instrument Serif and JetBrains Mono ttf files in video/fonts) for the pain-quote film from the real benchmark run (bench/result.json,
the clip's words.json and its audio). Usage: python make_film.py /tmp/cutbench/clip.mp4 film.json"""
import array, json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scriptcut as sc

video, out = sys.argv[1], sys.argv[2]
lines = json.load(open(sc.paths(video)[0]))
res = json.load(open(os.path.join(os.path.dirname(__file__), "..", "bench", "result.json")))
cut = {i for i in range(len(lines)) if i % 3 == 2}
edit = {i: [w["w"] for w in l] for i, l in enumerate(lines) if i not in cut}
dur = sc.probe_duration(video)
p = sc.plan(lines, edit, max_gap=0.4, duration=dur)
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                     capture_output=True, check=True).stdout
pcm = array.array("h", raw)
bins = 160
step = len(pcm) // bins
env = []
for b in range(bins):
    seg = pcm[b * step:(b + 1) * step:4]
    env.append((sum(x * x for x in seg) / max(1, len(seg))) ** 0.5)
top = max(env)
film = {
    "quote": {"handle": "@rileybrown", "views": "20K views",
              "lead": "No one has built a good Agent Native video editing/filming platform.",
              "ask": "Someone should build an Open Descript."},
    "hook": {"big": "%ds → %ds" % (round(res["source_seconds"]), round(res["output_seconds"])),
             "sub": "a 3 minute speech, cut by deleting lines of text. $0."},
    "lines": [{"t": " ".join(w["w"] for w in l)[:64], "cut": i in cut,
               "s": l[0]["s"] / dur, "e": l[-1]["e"] / dur} for i, l in enumerate(lines[:15])],
    "env": [round(v / top, 3) for v in env],
    "spans": [[s / dur, e / dur] for s, e in p["spans"]],
    "res": res,
    "end": {"name": "scriptcut", "line": "Edit video by editing text. Your agent already knows how.",
            "meta": "open source \u00b7 MIT \u00b7 one Python file", "built": "built with Claude Opus 5.5",
            "cta": "code in the reply"},
}
import base64
fd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
film["fonts"] = {} if not os.path.isdir(fd) else {k: base64.b64encode(open(os.path.join(fd, f), "rb").read()).decode()
                 for k, f in (("serif", "InstrumentSerif-Regular.ttf"), ("italic", "InstrumentSerif-Italic.ttf"),
                              ("mono", "JetBrainsMono.ttf"))}
json.dump(film, open(out, "w"))
print(len(film["lines"]), len(film["spans"]), film["hook"])
