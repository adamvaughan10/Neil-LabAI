"""
Play recorded sessions in the browser, cycle through them, and see what the classifier said.

    python scripts/session_player.py                         # every attempt under logs/ and episodes/
    python scripts/session_player.py logs/run_* --port 8771
    python scripts/session_player.py "../Neil LabAI-recorder/logs" --results output/classifier

Opens http://127.0.0.1:8770. Both cameras play side by side from the saved frames (so they stay in
step with steps.jsonl), with the arm/gripper readings under them. Each attempt shows the latest
classifier verdict found under --results (default output/classifier/, newest run wins); the
Classify button judges the current attempt on the spot (needs ANTHROPIC_API_KEY) and saves the
verdict to output/classifier/player/.

Keys: space play/pause, left/right one step, shift+left/right one second, up/down or p/n previous/next attempt.
"""
import argparse
import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neil_robot.attempt_classifier import DEFAULT_MODEL, classify, find_attempts, load_attempt, sample_indices  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "session_player.html"


def load_verdicts(results: list[Path]) -> dict[str, dict]:
    """Attempt path -> its newest verdict, from every attempts/*.json under the results folders."""
    found = []
    for r in results:
        for f in Path(r).rglob("attempts/*.json"):
            try:
                v = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if "success" in v and v.get("path"):
                found.append((f.stat().st_mtime, v, f))
    verdicts = {}
    for _, v, f in sorted(found, key=lambda x: x[0]):
        p = Path(v["path"])
        p = p if p.is_absolute() else (ROOT / p)
        v["result_file"] = str(f)
        verdicts[str(p.resolve())] = v
    return verdicts


class Library:
    """The attempts on offer, loaded lazily, with decoded video frames cached for episodes."""

    def __init__(self, dirs: list[Path], results: list[Path], task: str | None):
        self.dirs = dirs
        self.results = results
        self.task = task
        self.attempts = {}
        self.frame_cache = {}
        self.lock = threading.Lock()
        self.verdicts = load_verdicts(results)

    def attempt(self, i: int):
        with self.lock:
            if i not in self.attempts:
                self.attempts[i] = load_attempt(self.dirs[i], self.task)
            return self.attempts[i]

    def listing(self) -> list[dict]:
        self.verdicts = load_verdicts(self.results)
        out = []
        for i, d in enumerate(self.dirs):
            parent = d.parent
            out.append({"id": i, "name": d.name, "group": f"{parent.parent.name}/{parent.name}",
                        "path": str(d), "verdict": self.verdicts.get(str(d.resolve()))})
        return out

    def detail(self, i: int) -> dict:
        a = self.attempt(i)
        parent = self.dirs[i].parent
        return {"id": i, "name": self.dirs[i].name, "group": f"{parent.parent.name}/{parent.name}",
                "path": str(self.dirs[i]), "kind": a.kind, "task": a.task,
                "fps": a.fps, "n_steps": a.n_steps, "cameras": list(a.frames), "label": a.label,
                "arm": a.arm, "grip": a.grip, "sampled": sample_indices(a.n_steps, 8),
                "verdict": self.verdicts.get(str(self.dirs[i].resolve()))}

    def frame_jpeg(self, i: int, cam: str, step: int, width: int = 640) -> bytes | None:
        key = (i, cam, step)
        if key in self.frame_cache:
            return self.frame_cache[key]
        a = self.attempt(i)
        if cam not in a.frames or not 0 <= step < a.n_steps:
            return None
        if a.kind == "episode":
            self._decode_video(i, cam, a, width)  # seeking per frame is slow; decode the whole clip once
            return self.frame_cache.get(key)
        img = a.frames[cam](step)
        if img is None:
            return None
        return _encode(img, width)

    def _decode_video(self, i, cam, a, width):
        with self.lock:
            if (i, cam, 0) in self.frame_cache:
                return
            video = a.path / ("top.mp4" if cam == "top" else "front.mp4")
            cap = cv2.VideoCapture(str(video))
            step = 0
            while True:
                ok, img = cap.read()
                if not ok:
                    break
                self.frame_cache[(i, cam, step)] = _encode(img, width)
                step += 1
            cap.release()

    def classify(self, i: int, model: str, effort: str) -> dict:
        import anthropic
        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")):
            raise RuntimeError("no ANTHROPIC_API_KEY: export it in the terminal, then restart the player")
        a = self.attempt(i)
        d = self.dirs[i]
        name = "__".join(d.resolve().parts[-3:]).replace(" ", "_")
        v = {"name": name, "path": str(d.resolve()), "kind": a.kind, "task": a.task,
             "duration_s": round(a.duration_s, 1), "label": a.label}
        v.update(classify(anthropic.Anthropic(), a, model, effort))
        out = ROOT / "output" / "classifier" / "player" / "attempts" / f"{name}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(v, indent=2))
        v["result_file"] = str(out)
        self.verdicts[str(d.resolve())] = v
        return v


def _encode(img, width):
    h, w = img.shape[:2]
    if w > width:
        img = cv2.resize(img, (width, round(h * width / w)), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


def make_handler(lib: Library, model: str, effort: str):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body: bytes, ctype: str, cache: bool = False):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def json(self, obj, code=200):
            self.send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            parts = [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p]
            try:
                if not parts:
                    return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if parts == ["api", "attempts"]:
                    return self.json(lib.listing())
                if len(parts) == 3 and parts[:2] == ["api", "attempt"]:
                    return self.json(lib.detail(int(parts[2])))
                if len(parts) == 4 and parts[0] == "frame":  # /frame/<id>/<cam>/<step>.jpg
                    jpg = lib.frame_jpeg(int(parts[1]), parts[2], int(parts[3].split(".")[0]))
                    if jpg is None:
                        return self.send(404, b"no frame", "text/plain")
                    return self.send(200, jpg, mimetypes.types_map[".jpg"], cache=True)
                self.send(404, b"not found", "text/plain")
            except (ValueError, IndexError) as e:
                self.json({"error": str(e)}, 400)

        def do_POST(self):
            parts = [p for p in urlparse(self.path).path.strip("/").split("/") if p]
            if len(parts) == 3 and parts[:2] == ["api", "classify"]:
                try:
                    return self.json(lib.classify(int(parts[2]), model, effort))
                except Exception as e:  # shown in the page, e.g. a missing API key
                    return self.json({"error": f"{type(e).__name__}: {e}"}, 500)
            self.send(404, b"not found", "text/plain")

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", type=Path, help="attempt folders, or folders to search (default logs/ and episodes/)")
    ap.add_argument("--results", nargs="*", type=Path, default=[ROOT / "output" / "classifier"],
                    help="classifier output folders to read verdicts from (default output/classifier)")
    ap.add_argument("--task", help="task for the Classify button (default: from the attempt)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    paths = args.paths or [p for p in (ROOT / "logs", ROOT / "episodes") if p.exists()]
    dirs = []
    for p in paths:
        dirs += [d for d in find_attempts(p) if d not in dirs]
    if not dirs:
        sys.exit("No attempts found. Pass the folder holding the sessions, e.g. logs/")
    lib = Library(dirs, args.results, args.task)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(lib, args.model, args.effort))
    url = f"http://127.0.0.1:{args.port}"
    n_judged = sum(1 for d in dirs if str(d.resolve()) in lib.verdicts)
    print(f"{len(dirs)} attempts ({n_judged} with a verdict). Playing at {url}   Ctrl+C stops")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
