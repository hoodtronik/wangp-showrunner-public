"""hoodtronik fork: proven H3 LoRAs as a fix for a shot that failed twice (never a first-take default).

NOTE (2026-11-01, request: template defaults first; LoRA logic only after the director judged 2 takes failed): upstream Showrunner never picks LoRAs (the template brings them). This module reads an H3 LoRA registry
(JSON {"loras": [...]}, tested LoRAs only; path from SHOWRUNNER_H3_REGISTRY or "h3_registry_path" in settings/showrunner/config.json) and offers its PROVEN/ADOPTED LoRAs for a named failure need. A pick
is stored on the shot as `extra_loras` and ADDED on top of the template's LoRAs at submission (merge_extra_loras), so the speed
LoRA stays. Untested candidates are never offered.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CONFIG = Path(__file__).resolve().parents[2] / "settings" / "showrunner" / "config.json"  # WanGP's app/settings/showrunner


def _registry_path() -> Path | None:
    """The registry path: SHOWRUNNER_H3_REGISTRY, else "h3_registry_path" in the plugin config; None = lora_fix not configured."""
    value = os.environ.get("SHOWRUNNER_H3_REGISTRY")
    if not value and CONFIG.is_file():
        try:
            value = json.loads(CONFIG.read_text(encoding="utf-8")).get("h3_registry_path")
        except (OSError, ValueError):
            value = None
    return Path(value) if value else None
LORA_ROOT = Path(__file__).resolve().parents[2] / "loras"  # WanGP's app/loras
# The registry's need vocabulary (scripts/h3_registry.py NEEDS) minus the ones that are not a fix for a failed take.
NEEDS = {
    "face-realism": "plastic or waxy faces, real skin in CU",
    "film-texture": "AI gloss, grain, lens character, grade",
    "body-motion": "stiff or sliding walks, natural body movement",
    "fast-motion": "flips, spins, scrambles without limbs morphing",
    "combat": "fight choreography, impact, weapons",
    "camera": "camera moves that don't land, angle control",
    "lipsync": "lip-sync, facial muscle dynamics while speaking",
    "hands-eyes": "hand and eye defects",
    "action-look": "action-movie energy and lighting",
    "detail": "blurry fine detail, sharpen / restore / refine",
    "physics": "gravity, hang time, weight, ground impact and debris",
}
PROVEN = {"adopted": 0, "proven": 1}
FAILS_BEFORE_LORA = 2


def _on_disk(name: str) -> bool:
    return any(LORA_ROOT.rglob(name)) if LORA_ROOT.is_dir() else False


def _strength(text: Any) -> float:
    match = re.match(r"\s*([0-9]*\.?[0-9]+)", str(text or ""))
    return float(match.group(1)) if match else 1.0


def pick(need: str) -> list[dict[str, Any]]:
    """The proven LoRAs for a need that WanGP can load, best evidence first."""
    if need not in NEEDS:
        raise ValueError(f"Unknown need {need!r}. Known: {', '.join(NEEDS)}.")
    registry = _registry_path()
    if registry is None or not registry.is_file():
        raise ValueError(f"No H3 LoRA registry configured (set SHOWRUNNER_H3_REGISTRY or h3_registry_path in the Showrunner config): {registry}.")
    entries = json.loads(registry.read_text(encoding="utf-8")).get("loras", [])
    rows = []
    for entry in sorted(entries, key=lambda item: (PROVEN.get(item.get("status"), 9), item.get("name", "").lower())):
        if need not in (entry.get("use_for") or []) or entry.get("status") not in PROVEN or str(entry.get("lane") or "").startswith("comfy"):
            continue
        name = next((file for file in entry.get("files") or [] if _on_disk(file)), None)
        if name:
            rows.append({"name": entry["name"], "file": name, "strength": _strength(entry.get("strength")), "strength_note": entry.get("strength"),
                         "triggers": [word.strip() for word in str(entry.get("trigger") or "").split(",") if word.strip()], "recipe": entry.get("recipe", "")})
    return rows


def failed_takes(shot: dict[str, Any]) -> int:
    return sum(1 for take in shot.get("takes") or [] if (take.get("verdict") or {}).get("ok") is False)


def merge_extra_loras(settings: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    """settings with its `extra_loras` appended to the LoRAs it already carries (or the template's, from base), one multiplier each,
    repeated per guidance phase."""
    extra = settings.pop("extra_loras", None) or []
    if not extra:
        return settings
    source = settings if "activated_loras" in settings else (base or {})
    loras = list(source.get("activated_loras") or [])
    multipliers = str(source.get("loras_multipliers") or "").split()
    multipliers += ["1.0"] * (len(loras) - len(multipliers))
    phases = max(1, int(settings.get("guidance_phases") or (base or {}).get("guidance_phases") or 1))
    for item in extra:
        if item["file"] not in loras:
            loras.append(item["file"])
            multipliers.append(";".join([f"{float(item.get('strength', 1.0)):g}"] * phases))
    settings["activated_loras"], settings["loras_multipliers"] = loras, " ".join(multipliers)
    return settings
