"""Find the cup (white) and Neil (yellow) in the live frames. Simple colour rules."""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image

A = Path(__file__).resolve().parents[1] / "assets"

def largest(mask):
    """Pixels of the largest 4-connected blob."""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    best = []
    for y0, x0 in zip(*np.where(mask)):
        if seen[y0, x0]: continue
        stack, blob = [(y0, x0)], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop(); blob.append((y, x))
            for yy, xx in ((y+1, x), (y-1, x), (y, x+1), (y, x-1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                    seen[yy, xx] = True; stack.append((yy, xx))
        if len(blob) > len(best): best = blob
    return best

def dilate(m, n=1):
    for _ in range(n):
        m = m | np.roll(m, 1, 0) | np.roll(m, -1, 0) | np.roll(m, 1, 1) | np.roll(m, -1, 1)
    return m


def box(mask, minpx):
    blob = largest(mask)
    if len(blob) < minpx: return None
    ys = np.array([b[0] for b in blob]); xs = np.array([b[1] for b in blob])
    h, w = mask.shape
    return [round(xs.min() / w, 3), round(ys.min() / h, 3), round((xs.max() + 1) / w, 3), round((ys.max() + 1) / h, 3)]

def run():
    txt = (A / "data.js").read_text()
    data = json.loads(txt[len("window.LOOP_DATA = "):-2])
    for k, lv in enumerate(data["live"]):
        out = []
        for j in range(lv["n"]):
            im = np.asarray(Image.open(A / "live" / str(k) / f"{j:03d}.jpg").convert("RGB").resize((160, 90))).astype(int)
            r, g, b = im[..., 0], im[..., 1], im[..., 2]
            yellow = dilate((r > 170) & (g > 140) & (b < 90), 2)
            # the cup is cream white: bright, with a little less blue than the grey table glare
            cream = (r > 195) & (g > 185) & (r - b > 14) & (r - b < 60) & (b > 130)
            out.append({"bot": box(yellow, 25), "cup": box(cream, 30)})
        lv["boxes"] = out
    (A / "data.js").write_text("window.LOOP_DATA = " + json.dumps(data) + ";\n")

if __name__ == "__main__":
    run()
