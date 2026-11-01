"""hoodtronik fork: a shot's GUIDES (start frame, end frame, previz) wired into an H3 reference template the same way every time.

NOTE (2026-11-01, request: work a previz into Showrunner so it knows what each shot is): upstream has no notion of a previz or of keyframes for cast shots (its skill: cast pictures are references,
never start images). So the meaning is not left to the director: render applies the slots deterministically, with the forms we
proved in WanGP H3 tests:
- start frame -> image_start, end frame -> image_end (image_prompt_type S / SE). H3 numbers pictures start, end, then references, so
  the director's <Picture n> (written for the references, counting from 1) are shifted and the anchors' lines are added.
- previz -> video_guide with video_prompt_type V + I, CAMERA-ONLY wording: grey/clay stand-ins leaked into renders when a previz was
  treated as a full guide (learnings/h3 10-30), and H3 refuses a video reference under 2 s, so a short clip is padded (last frame held)
  to the shot's length.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from . import media

SLOTS = ("start_frame", "end_frame", "previz")
PREVIZ_LINE = ("<Video 1> is a CAMERA-MOVEMENT REFERENCE ONLY (a previz): copy its camera path, framing changes and timing; do NOT copy its "
               "grey stand-in bodies, set or colours: every person and place looks exactly as in the pictures.")


def insert_after(prompt: str, label: str, text: str) -> str:
    """The prompt with text placed right after a section label (H3's structured prompt), or in front when the label is missing."""
    at = prompt.find(label)
    if at < 0:
        return f"{text} {prompt}"
    end = at + len(label)
    rest = prompt[end:]
    return f"{prompt[:end]} {text}" + (rest if rest[:1] in (" ", "\n") else " " + rest)


def padded_video(path: Path, seconds: float, folder: Path) -> Path:
    """The previz held on its last frame up to `seconds` (at least 2.5 s: H3 refuses shorter video references), cut once and reused."""
    length = float(media.probe(path).get("duration_s") or 0.0)
    target = max(2.5, float(seconds or 0.0))
    if length >= target - 0.05:
        return path
    out = folder / f"{path.stem}-to-{target:.2f}s.mp4"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        media._run([media.ffmpeg(), "-y", "-v", "error", "-i", str(path), "-vf", f"tpad=stop_mode=clone:stop_duration={target - length + 0.1:.3f}",
                    "-an", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out)])
    return out


def apply(settings: dict[str, Any], shot: dict[str, Any], resolve: Callable[[str], Path], name: Callable[[Path], str], folder: Path) -> dict[str, Any]:
    """settings (of a reference template) with the shot's guides wired in; resolve = production path -> file, name = file -> how the
    generator is given it, folder = where padded previz copies go."""
    start, end, previz = (shot.get(slot) for slot in SLOTS)
    if not (start or end or previz):
        return settings
    prompt = str(settings.get("prompt") or "")
    definitions, retention = [], []
    anchors = [(path, kind) for path, kind in ((start, "first"), (end, "last")) if path]
    if anchors:
        prompt = re.sub(r"<Picture (\d+)>", lambda match: f"<Picture {int(match.group(1)) + len(anchors)}>", prompt)
        for number, (path, kind) in enumerate(anchors, 1):
            settings["image_start" if kind == "first" else "image_end"] = name(resolve(path))
            definitions.append(f"<Picture {number}> is the {kind} frame.")
            retention.append(f"<Picture {number}>: fully_preserved - exact {kind} frame.")
        settings["image_prompt_type"] = ("S" if start else "") + ("E" if end else "")
    if previz:
        settings["video_guide"] = name(padded_video(resolve(previz), float(shot.get("duration_s") or 0.0), folder))
        settings["video_prompt_type"] = "VI" if "I" in str(settings.get("video_prompt_type") or "I") else "V"
        definitions.append(PREVIZ_LINE)  # prose only, NO retention label: a partially_preserved tag made the clay drive stiff + jumpy (minimax-h3 skill, 09-11)
    prompt = insert_after(prompt, "subject_definitions:", " ".join(definitions))
    settings["prompt"] = insert_after(prompt, "retention_analysis:", " ".join(retention)) if retention else prompt
    return settings
