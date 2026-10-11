"""Tiny JSON-backed log of every tree the user has found."""
import json
import time
import uuid
from pathlib import Path

from PIL import Image

DATA_DIR = Path("data")
DB_FILE = DATA_DIR / "treedex.json"
PHOTO_DIR = DATA_DIR / "photos"


def load() -> dict:
    if DB_FILE.exists():
        return json.loads(DB_FILE.read_text())
    return {"score": 0.0, "finds": []}


def save(db: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    DB_FILE.write_text(json.dumps(db, indent=2))


def species_key(tree: dict) -> str:
    name = tree.get("scientific_name") or tree.get("common_name") or "unknown"
    return " ".join(name.lower().split())


def species_summary(db: dict) -> dict:
    """Group the raw find log by species.

    Returns {species_key: {tree, seasons: {season: times_found}, photo, number, count}}
    `number` is the Treedex entry number (order of first discovery).
    """
    out: dict = {}
    for f in db["finds"]:
        s = out.setdefault(
            f["species_key"],
            {"tree": f["tree"], "seasons": {}, "photo": f.get("photo"), "number": len(out) + 1, "count": 0},
        )
        s["seasons"][f["season"]] = s["seasons"].get(f["season"], 0) + 1
        s["count"] += 1
    return out


def save_photo(src_path: str) -> str:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    dest = PHOTO_DIR / f"{uuid.uuid4().hex[:10]}.jpg"
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        im.thumbnail((480, 480))
        im.save(dest, quality=85)
    return str(dest)


def add_find(db: dict, tree: dict, season: str, confidence: float, added: float, photo: str) -> None:
    db["finds"].append(
        {
            "ts": time.strftime("%Y-%m-%d %H:%M"),
            "season": season,
            "species_key": species_key(tree),
            "confidence": confidence,
            "added": added,
            "tree": tree,
            "photo": photo,
        }
    )
    db["score"] = round(db["score"] + added, 1)
    save(db)
