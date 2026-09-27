import json, os, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scriptcut as sc

def W(text, start, step=0.5):
    return [{"w": w, "s": start + i * step, "e": start + i * step + 0.4} for i, w in enumerate(text.split())]

LINES = [W("hello there everyone", 0.0), W("um this part goes", 3.0), W("keep this one", 8.0)]

class Plan(unittest.TestCase):
    def test_untouched_edit_keeps_everything(self):
        edit = {i: [w["w"] for w in l] for i, l in enumerate(LINES)}
        p = sc.plan(LINES, edit)
        self.assertEqual(p["kept_words"], 10)

    def test_deleted_line_is_cut(self):
        edit = {0: "hello there everyone".split(), 2: "keep this one".split()}
        p = sc.plan(LINES, edit)
        self.assertEqual(p["kept_words"], 6)
        for s, e in p["spans"]:
            self.assertFalse(s < 4.9 and e > 3.1, "cut line leaked into a span")

    def test_deleted_word_splits_span(self):
        edit = {0: "hello everyone".split()}
        p = sc.plan(LINES, edit)
        self.assertEqual(len(p["spans"]), 2)

    def test_fillers_dropped(self):
        edit = {1: "um this part goes".split()}
        p = sc.plan(LINES, edit, drop_fillers=True)
        self.assertEqual(p["kept_words"], 3)
        self.assertGreater(p["spans"][0][0], 3.3)

    def test_max_gap_shortens_pauses(self):
        edit = {i: [w["w"] for w in l] for i, l in enumerate(LINES)}
        self.assertLess(sc.plan(LINES, edit, max_gap=0.3)["kept_seconds"],
                        sc.plan(LINES, edit)["kept_seconds"])

    def test_edit_file_roundtrip(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "x.edit.txt")
        sc.write_edit(LINES, path)
        self.assertEqual(sc.read_edit(path)[2], ["keep", "this", "one"])
        shutil.rmtree(d)

@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
class Render(unittest.TestCase):
    def test_render_length_matches_plan(self):
        d = tempfile.mkdtemp()
        src, out = os.path.join(d, "src.mp4"), os.path.join(d, "out.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=25:d=10",
                        "-f", "lavfi", "-i", "sine=d=10", "-shortest", "-c:v", "libx264", "-c:a", "aac", src], check=True)
        sc.render(src, [[1.0, 3.0], [6.0, 7.0]], out)
        self.assertAlmostEqual(sc.probe_duration(out), 3.0, delta=0.15)
        shutil.rmtree(d)

if __name__ == "__main__":
    unittest.main()
