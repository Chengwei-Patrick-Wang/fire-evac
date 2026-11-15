"""Tracer routes (spec 7.5), mounted under /api by main.py.

    POST /api/trace/propose   multipart: image (a file), hints (a JSON string)
                              ->  {floor, model, seconds, notes}

The AI first pass (A8). `image` is a PNG, JPEG or WebP floor plan of at most 8 MB (the tracer sends
it at most 1600 px on its long side); `hints` is {metersPerPixel, width, height, name?, level?} for
the image as sent. `floor` is a plan/v0 floor with rooms AI1, AI2, ... in floor meters (y up, from
the image's bottom-left corner, snapped to 0.25 m) and no doors: vision models miss doors, so the
person tracing adds them. `model` names the model that answered; `notes` are B's tidy_floor notes
(empty until buildings/tidy.py is on main, see _tidy). Errors: 413 above 8 MB, 415 for
another file type, 422 for bad hints (or a width and height that are not the image's), and 503
{"detail": "AI first pass unavailable"} when the model gives nothing: LLM_PROVIDER=off, no key,
every model out of quota or busy, a refusal, a timeout. The model call can take a while (Gemini: 60 s per
model in the chain, at most 130 s in all; Claude Opus at high effort: about 35 s for 12 rooms, and at least
150 s allowed), so the tracer waits up to 180 s. Only public plans may go to the model (spec 12): the tracer
asks before it sends a private trace and refuses one that mentions UMass.
"""
import io
import json
import sys
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..llm import client, features

router = APIRouter()

MAX_BYTES = 8 * 1024 * 1024
UNAVAILABLE = "AI first pass unavailable"


def _image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) in pixels, or None when Pillow (it comes with matplotlib) cannot tell."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:
        return None


def _tidy(floor: dict) -> tuple[dict, list[str]]:
    """(floor, notes): B's buildings.tidy.tidy_floor (task B10: squares near-rectangles, snaps to
    the 0.25 m grid, merges duplicates, trims overlaps, drops slivers) when it can be imported,
    else the floor as sanitize_floor left it (each vertex snapped to 0.25 m, junk dropped).

    TODO(A, after B10 merges): tidy_floor is on ws-b (3767e77) but was not on main when A8
    finished, so today this always falls back. It switches on by itself once main has
    buildings/tidy.py; then check its notes on a live proposal.
    """
    try:
        from buildings.tidy import tidy_floor
    except ImportError:
        return floor, []
    try:
        tidied, notes = tidy_floor(floor)
        if not isinstance(tidied, dict) or not isinstance(tidied.get("rooms"), list):
            raise ValueError(f"tidy_floor returned {type(tidied).__name__}, not a floor")
        return tidied, [str(n) for n in notes or []]
    except Exception as e:  # B's code failing must not cost the user the proposal
        print(f"trace/propose: tidy_floor failed ({type(e).__name__}: {e}); rooms left as sanitized", file=sys.stderr)
        return floor, []


@router.post("/trace/propose")
def post_trace_propose(image: UploadFile = File(...), hints: str = Form(...)):
    data = image.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"the image is over {MAX_BYTES // 2**20} MB; send it at most 1600 px on its long side")
    if features.image_mime(data) is None:
        raise HTTPException(415, "the image must be a PNG, JPEG or WebP file")
    try:
        parsed = json.loads(hints)
        _, width, height, _, _ = features.check_hints(parsed)
    except ValueError as e:  # json.JSONDecodeError is a ValueError
        raise HTTPException(422, f"hints: {e}")
    size = _image_size(data)
    if size is not None and (abs(size[0] - width) > 1 or abs(size[1] - height) > 1):
        raise HTTPException(422, f"hints say {width} x {height} px but the image is {size[0]} x {size[1]} px")
    t0 = time.time()
    floor = features.propose_plan(data, parsed)
    seconds = round(time.time() - t0, 1)
    if floor is None:
        print(f"trace/propose: {UNAVAILABLE} after {seconds} s", file=sys.stderr)
        raise HTTPException(503, UNAVAILABLE)
    model = client.last_model
    floor, notes = _tidy(floor)
    if notes:
        print(f"trace/propose: tidy_floor: {'; '.join(notes)}", file=sys.stderr)
    return {"floor": floor, "model": model, "seconds": seconds, "notes": notes}
