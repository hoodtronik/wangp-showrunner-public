# Copyright (c) 2026 DeepBeepMeep - part of WanGP, WanGP Community License 2.0 (see LICENSE.txt)
"""Movies (hoodtronik fork): one production holds a film's shared library, its scenes are productions filed under it.

NOTE (hoodtronik fork, 2026-11-02, request: "use subtemplates/subprojects in a major one ... not have one movie exist as several
projects"): a movie is a production with `is_movie`; its cast, its locations (Sets) and its style are the library. A scene is a production
with `movie` = the movie's id and `uses` = the cast ids and location names it switches on ("Showrunner gets confused when I have all the
characters and environments active when it may only need 2 characters and one environment"). The scene's document HOLDS COPIES of the
active members and places (marked `shared`, their media as full paths into the movie's folder), so the director, render and the pages
read a scene exactly like any production and see only what the scene uses. Two flows keep them one library:
  - materialize: the movie (or the scene's `uses`) changed -> rewrite the scene's shared members/places/style from the movie;
  - push: the user or Deepy changed a shared member/place/style inside a scene -> write it to the movie, which materializes every scene.
Removing a shared member inside a scene only switches it off there. Members added in a scene stay the scene's own (not `shared`).
A scene whose `uses` is None (an old production filed under a movie) is only grouped, never synced.
"""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from . import production as model

RECIPES = "recipes.json"
# Starting setups for a scene: brief fields copied into a new scene, plus `notes` the director reads as the scene's concept prefix.
RECIPE_FIELDS = {"kind", "pacing", "plan_first", "review_before_edit", "resolution", "aspect", "duration_s", "templates", "style_tags", "language", "audio_mode"}
BUILT_IN = [
    {"name": "Dialogue scene", "description": "Two or more characters talking: lip-synced lines, coverage, close-ups for the key lines.",
     "fields": {"kind": "short_film", "pacing": -1, "plan_first": True, "review_before_edit": True},
     "notes": "A dialogue scene: every line lip-synced in its speaker's close-up or two-shot, reaction shots between lines, calm cutting."},
    {"name": "Performance / dance", "description": "A character performs to the music: few long takes, the body and the beat lead.",
     "fields": {"kind": "music_video", "pacing": 0, "plan_first": True, "review_before_edit": True},
     "notes": "A performance scene: long takes that let the movement play, cut on the beat, wides for the body and mediums for the face."},
    {"name": "Action", "description": "Movement, chases, fights: short shots, strong screen direction.",
     "fields": {"kind": "short_film", "pacing": 1, "plan_first": True, "review_before_edit": True},
     "notes": "An action scene: short dynamic shots, one clear action per shot, keep screen direction and geography consistent."},
    {"name": "Establishing / montage", "description": "Places and atmosphere, no dialogue: sets the world.",
     "fields": {"kind": "short_film", "pacing": 0, "plan_first": True, "review_before_edit": False},
     "notes": "An establishing passage: the places, their light and scale, little or no dialogue."},
]
CAST_MEDIA = ("images", "master", "voice")


# Recipes --------------------------------------------------------------------------------------------------------------------------------
def recipes(root: Path) -> list[dict[str, Any]]:
    """The built-in recipes, then the user's saved ones (store root recipes.json; a saved one with a built-in's name replaces it)."""
    path = root / RECIPES
    saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    names = {item["name"].casefold() for item in saved}
    return [{**item, "built_in": True} for item in BUILT_IN if item["name"].casefold() not in names] + saved


def save_recipe(root: Path, name: str, fields: dict[str, Any], notes: str = "", description: str = "") -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise model.OperationError("A recipe needs a name.")
    path = root / RECIPES
    saved = [item for item in (json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []) if item["name"].casefold() != name.casefold()]
    item = {"name": name, "description": description, "fields": {key: copy.deepcopy(value) for key, value in fields.items() if key in RECIPE_FIELDS}, "notes": notes}
    saved.append(item)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
    return item


def delete_recipe(root: Path, name: str) -> None:
    path = root / RECIPES
    if path.is_file():
        saved = [item for item in json.loads(path.read_text(encoding="utf-8")) if item["name"].casefold() != name.casefold()]
        path.write_text(json.dumps(saved, indent=1, ensure_ascii=False), encoding="utf-8")


def recipe_of(doc: dict[str, Any]) -> dict[str, Any]:
    """A scene's setup as recipe fields (Save as recipe)."""
    brief = doc["brief"]
    return {**{key: copy.deepcopy(brief[key]) for key in RECIPE_FIELDS if key in brief}, "audio_mode": doc["edit"].get("audio_mode")}


# Paths ----------------------------------------------------------------------------------------------------------------------------------
def _map_member(member: dict[str, Any], convert) -> dict[str, Any]:
    member = copy.deepcopy(member)
    for key in CAST_MEDIA:
        value = member.get(key)
        member[key] = [convert(path) for path in value if path] if isinstance(value, list) else convert(value) if value else value
    for look in member.get("looks") or []:
        look["master"] = convert(look["master"]) if look.get("master") else look.get("master")
    return member


def _map_place(place: dict[str, Any], convert) -> dict[str, Any]:
    place = copy.deepcopy(place)
    place["references"] = [convert(path) for path in place.get("references") or [] if path]
    return place


def _absolute(production):
    """Movie path -> the full path a scene stores."""
    return lambda path: path if Path(path).is_absolute() else str(production.folder / path)


def _into(movie, scene):
    """Scene path -> the path the movie stores: its own files relative, a scene's file copied into the movie (media/imports)."""
    def convert(path):
        full = path if Path(path).is_absolute() else str(scene.folder / path)
        return movie.adopt(full) if Path(full).is_file() else movie.rel(full)
    return convert


def _comparable(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key not in ("shared",)}


# Sync -----------------------------------------------------------------------------------------------------------------------------------
def movie_of(store, doc: dict[str, Any]):
    movie_id = doc.get("movie")
    if not movie_id:
        return None
    try:
        movie = store.get(movie_id)
    except KeyError:
        return None
    return movie if movie.doc.get("is_movie") else None


def scenes_of(store, movie_id: str) -> list[Any]:
    """The movie's scenes in its order (scene_order), then any others filed under it by creation."""
    found = []
    for production_id in store.ids():
        try:
            production = store.get(production_id)
        except (KeyError, OSError, ValueError):
            continue
        if production.doc.get("movie") == movie_id and production_id != movie_id:
            found.append(production)
    order = store.get(movie_id).doc.get("scene_order") or []
    rank = {production_id: index for index, production_id in enumerate(order)}
    return sorted(found, key=lambda production: (rank.get(production.id, len(rank)), production.doc.get("created") or 0))


def _context(store, movie, scene_id: str) -> dict[str, Any]:
    doc = movie.doc
    scenes = [production for production in scenes_of(store, movie.id) if not production.doc.get("archived")]
    ids = [production.id for production in scenes]
    index = ids.index(scene_id) if scene_id in ids else -1
    neighbour = lambda at: {"title": scenes[at].doc["title"], "concept": str(scenes[at].doc["brief"].get("text") or "")[:400]} if 0 <= at < len(scenes) else None
    return {"title": doc["title"], "concept": doc["brief"].get("text") or "", "position": index + 1 if index >= 0 else None, "of": len(scenes),
            "previous": neighbour(index - 1) if index > 0 else None, "next": neighbour(index + 1) if index >= 0 else None}


def materialize(store, scene) -> bool:
    """Rewrite the scene's shared members, places and style from its movie (returns whether the document changed). No undo entry."""
    movie = movie_of(store, scene.doc)
    if movie is None or scene.doc.get("uses") is None:
        return False
    with movie.lock:
        library = copy.deepcopy(movie.doc)
    convert = _absolute(movie)
    with scene.lock:
        doc = scene.doc
        uses = doc["uses"]
        wanted_cast = [member for member in library["cast"] if member["id"] in (uses.get("cast") or [])]
        wanted_places = [place for place in library["brief"]["locations"] if place.get("name") in (uses.get("locations") or [])]
        own_cast = [member for member in doc["cast"] if not member.get("shared")]
        shared_ids = {member["id"] for member in library["cast"]}
        for member in own_cast:  # a scene's own member keeps clear of the movie's ids (one could be switched on later)
            if member["id"] in shared_ids:
                old, member["id"] = member["id"], model._next_id("c", [*library["cast"], *own_cast])
                for shot in doc["shots"]:
                    shot["cast"] = [member["id"] if entry == old else entry for entry in shot["cast"]]
        cast = [{**_map_member(member, convert), "shared": True} for member in wanted_cast] + own_cast
        places = [{**_map_place(place, convert), "shared": True} for place in wanted_places] + [place for place in doc["brief"]["locations"] if not place.get("shared")]
        context = _context(store, movie, scene.id)
        style = copy.deepcopy(library["style"])
        if (cast, places, style, context) == (doc["cast"], doc["brief"]["locations"], doc["style"], doc.get("movie_context")):
            return False
        active = {member["id"] for member in cast}
        for shot in doc["shots"]:  # a member switched off leaves the shots it was in
            shot["cast"] = [entry for entry in shot["cast"] if entry in active]
        doc["cast"], doc["brief"]["locations"], doc["style"], doc["movie_context"] = cast, places, style, context
        model.normalize(doc)
        doc["revision"] += 1
        scene.save()
        revision = doc["revision"]
    store.publish({"type": "doc", "production": scene.id, "revision": revision, "by": "system", "ops": ["movie"]})
    return True


def materialize_all(store, movie_id: str) -> None:
    for scene in scenes_of(store, movie_id):
        try:
            materialize(store, scene)
        except Exception as error:  # one broken scene must not stop the others
            print(f"[Showrunner] Could not sync scene {scene.id} from its movie: {error}")


def push(store, scene, by: str) -> None:
    """Carry the scene's edits of shared members, places and style to the movie (which then syncs every scene)."""
    movie = movie_of(store, scene.doc)
    if movie is None or scene.doc.get("uses") is None:
        return
    with scene.lock:
        doc = copy.deepcopy(scene.doc)
    with movie.lock:
        library = copy.deepcopy(movie.doc)
    convert, ops = _into(movie, scene), []
    uses = {"cast": list(doc["uses"].get("cast") or []), "locations": list(doc["uses"].get("locations") or [])}
    present = {member["id"]: member for member in doc["cast"] if member.get("shared")}
    for member in library["cast"]:
        if member["id"] not in uses["cast"]:
            continue
        if member["id"] not in present:  # removed in the scene: switched off there, kept in the movie
            uses["cast"].remove(member["id"])
            continue
        mine = _comparable(_map_member(present[member["id"]], convert))
        fields = {key: value for key, value in mine.items() if key in model.CAST_FIELDS and value != member.get(key)}
        if fields:
            ops.append({"op": "update_cast", "cast": member["id"], "fields": fields})
    places = {place["name"]: place for place in doc["brief"]["locations"] if place.get("shared")}
    locations, changed = copy.deepcopy(library["brief"]["locations"]), False
    for index, place in enumerate(locations):
        if place.get("name") not in uses["locations"]:
            continue
        if place["name"] not in places:
            uses["locations"].remove(place["name"])
            continue
        mine = _comparable(_map_place(places[place["name"]], convert))
        if mine != place:
            locations[index], changed = mine, True
    if changed:
        ops.append({"op": "brief", "fields": {"locations": locations}})
    if doc["style"] != library["style"]:
        ops.append({"op": "style", "fields": doc["style"]})
    if uses != doc["uses"]:
        with scene.lock:
            scene.doc["uses"] = uses
            scene.save()
    if ops:
        movie.apply(ops, by=by)  # its apply syncs every scene
    elif uses != doc["uses"]:
        materialize(store, scene)


# Scenes ---------------------------------------------------------------------------------------------------------------------------------
def create_scene(store, movie_id: str, title: str, recipe: dict[str, Any] | None, uses: dict[str, Any] | None, concept: str = "", kind: str | None = None) -> Any:
    movie = store.get(movie_id)
    if not movie.doc.get("is_movie"):
        raise model.OperationError("Scenes go into a movie: make this production a movie first.")
    library = movie.snapshot()
    fields = dict((recipe or {}).get("fields") or {})
    brief = {key: copy.deepcopy(library["brief"][key]) for key in ("aspect", "resolution", "templates", "language", "style_tags", "read_other_productions")}
    brief.update({key: value for key, value in fields.items() if key in model.BRIEF_FIELDS and key not in ("templates",)})
    brief["templates"] = {**library["brief"].get("templates", {}), **(fields.get("templates") or {})}
    notes = (recipe or {}).get("notes") or ""
    brief["text"] = "\n".join(part for part in (concept.strip(), notes.strip()) if part)
    # NOTE (hoodtronik fork, 2026-11-02, request: "I still want to keep the old template names"): the format tile picked in Add scene wins,
    # then the recipe's kind, then the movie's own format, so every scene is still a Music video / Short film / Ad... like upstream.
    kind = kind if kind in model.KINDS else (brief.pop("kind", None) or library["brief"].get("kind") or "short_film")
    brief.pop("kind", None)
    scene = store.create(title, kind, **brief)
    with scene.lock:
        scene.doc["movie"] = movie_id
        scene.doc["recipe"] = (recipe or {}).get("name")
        scene.doc["uses"] = {"cast": [member["id"] for member in library["cast"] if member["id"] in ((uses or {}).get("cast") or [])],
                             "locations": [place["name"] for place in library["brief"]["locations"] if place["name"] in ((uses or {}).get("locations") or [])]}
        if fields.get("audio_mode") in model.AUDIO_MODES:
            scene.doc["edit"]["audio_mode"] = fields["audio_mode"]
        scene.save()
    with movie.lock:
        movie.doc["scene_order"] = [*(movie.doc.get("scene_order") or []), scene.id]
        movie.save()
    materialize_all(store, movie_id)  # the new scene's library, and its neighbours' context
    store.publish({"type": "productions"})
    return scene


def file_under(store, scene_id: str, movie_id: str | None, archived: bool | None = None) -> None:
    """File an existing production under a movie (grouped only, not synced: its own cast and sets stay its own), or take it out (None)."""
    scene = store.get(scene_id)
    if movie_id is not None and not store.get(movie_id).doc.get("is_movie"):
        raise model.OperationError("That production is not a movie.")
    with scene.lock:
        previous = scene.doc.get("movie")
        scene.doc["movie"] = movie_id
        if movie_id is None:
            scene.doc["uses"] = None
            for member in scene.doc["cast"]:
                member.pop("shared", None)
            for place in scene.doc["brief"]["locations"]:
                place.pop("shared", None)
        if archived is not None:
            scene.doc["archived"] = archived
        scene.doc["revision"] += 1
        scene.save()
    store.publish({"type": "doc", "production": scene_id, "revision": scene.doc["revision"], "by": "user", "ops": ["movie"]})
    for owner in {previous, movie_id} - {None}:
        try:
            movie = store.get(owner)
        except KeyError:
            continue
        with movie.lock:
            order = [item for item in movie.doc.get("scene_order") or [] if item != scene_id]
            if owner == movie_id:
                order.append(scene_id)
            movie.doc["scene_order"] = order
            movie.save()
    store.publish({"type": "productions"})


def set_uses(store, scene_id: str, uses: dict[str, Any]) -> None:
    scene = store.get(scene_id)
    movie = movie_of(store, scene.doc)
    if movie is None:
        raise model.OperationError("This production is not a scene of a movie.")
    with scene.lock:
        scene.doc["uses"] = {"cast": [str(item) for item in uses.get("cast") or []], "locations": [str(item) for item in uses.get("locations") or []]}
        scene.save()
    materialize(store, scene)


def reorder(store, movie_id: str, order: list[str]) -> None:
    movie = store.get(movie_id)
    known = [production.id for production in scenes_of(store, movie_id)]
    with movie.lock:
        movie.doc["scene_order"] = [item for item in order if item in known] + [item for item in known if item not in order]
        movie.save()
    materialize_all(store, movie_id)  # each scene's previous/next
    store.publish({"type": "productions"})


# The movie cut --------------------------------------------------------------------------------------------------------------------------
def assemble_movie(store, movie_id: str, facts, by: str = "user") -> dict[str, Any]:
    """Join each scene's latest version, in the movie's order, into one film (re-encoded: scenes may differ in size or rate)."""
    from . import media
    movie = store.get(movie_id)
    parts, missing = [], []
    for scene in scenes_of(store, movie_id):
        if scene.doc.get("archived"):
            continue
        latest = next((item for item in reversed(scene.doc["deliverables"]) if item.get("path")), None)
        path = scene.resolve(latest["path"]) if latest else None
        if path is None or not path.is_file():
            missing.append(scene.doc["title"])
            continue
        parts.append(path)
    if not parts:
        raise model.OperationError("No scene has a version yet: assemble a scene first (its Deliver page).")
    width, height = (int(value) for value in model.resolution(movie.doc["brief"]).split("x"))
    inputs, chains = [], []
    # NOTE (hoodtronik fork): 24 fps = the house frame rate; a scene without sound gets silence of its length, or the concat fails.
    for index, path in enumerate(parts):
        info = media.probe(path)
        inputs += ["-i", str(path)]
        audio = f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo[a{index}];" if info.get("has_audio")             else f"anullsrc=r=48000:cl=stereo,atrim=0:{info.get('duration_s') or 1:.3f}[a{index}];"
        chains.append(f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p[v{index}];" + audio)
    graph = "".join(chains) + "".join(f"[v{index}][a{index}]" for index in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=1[v][a]"
    name = re.sub(r"[^A-Za-z0-9]+", "-", movie.doc["title"]).strip("-")[:40] or "movie"
    out = movie.folder / "media" / "exports" / f"{name}-movie-r{movie.doc['revision']}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([media.ffmpeg(), "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
                             "-crf", "18", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Joining the scenes failed: {result.stderr.strip()[-600:]}")
    item = {**facts(movie, out), "kind": "video", "method": "movie", "revision": movie.doc["revision"], "by": by, "scenes": len(parts), "missing": missing}
    movie.apply([{"op": "deliverable", "deliverable": item}], by=by)
    return item
