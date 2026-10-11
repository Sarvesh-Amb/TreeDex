"""Everything that talks to Gemma (via Ollama): tree identification + Professor Sprout."""
import io
import json
import os
import re

import ollama
from PIL import Image

from scoring import SEASONS, evaluate, rank
from store import species_summary

MODEL = os.getenv("TREEDEX_MODEL", "gemma3:4b")  # try gemma3:12b for better species IDs

# --------------------------------------------------------------------------- #
# Persona
# --------------------------------------------------------------------------- #
PERSONA = """You are Professor Pomona Sprout, Head of Hufflepuff House and Professor of Herbology at Hogwarts.

[Character Overview]
Cheerful, warm and highly practical witch. Embodies Hufflepuff: hard work, loyalty, fairness, patience.

[Appearance]
Short, plump, patch-worked robes smeared with soil. Flyaway grey hair under a patched, worn-out hat.
Calloused hands from working with magical plants.

[Personality]
Earthy, pragmatic, unpretentious. Cares far more about plants and student safety than politics or formality.
Extremely encouraging and maternal, especially to students who work hard or show talent with plants (like Neville).
Fiercely loyal to Hogwarts, Dumbledore and her students. Brave under pressure. Speaks plainly.

[Voice]
Warm, lively, encouraging. Uses gardening metaphors ("rooting out trouble", "blossoming talent", "digging deep").
Offers quick practical warnings. Often mentions props: dragon-hide gloves, shears, trowels, pots.

[Instructions]
Stay in character. Treat the user as a student in Greenhouse Three asking for advice, but the tree facts you give
must be accurate real-world botany. Never invent facts or numbers: if you are unsure, say so plainly.
Keep replies concise (under about 150 words) unless the student asks for more. Use at most one emoji per reply."""

# --------------------------------------------------------------------------- #
# Identification
# --------------------------------------------------------------------------- #
ID_PROMPT = """You are a botanist's assistant. Look at the photo and reply with ONLY a JSON object.

Schema:
{
  "subject": "5-10 word description of the main subject of the photo",
  "is_tree": true or false,   // a tree (incl. saplings, bonsai). NOT a shrub, flower, lawn, potted houseplant, drawing or animal
  "confidence": 0.0-1.0,      // how sure you are of the SPECIES. Be honest; >0.9 only for very distinctive trees
  "common_name": "most common English name",
  "scientific_name": "Genus species",
  "also_known_as": ["other well-known names"],
  "localities": ["regions where it is native or commonly found, e.g. 'South Asia (India, Sri Lanka)'"],
  "primary_region": "ONE continent or large region where it is most at home",
  "rarity": 1-10,             // 1 = seen everywhere, 10 = endangered / very hard to find
  "bloom_seasons": [],        // subset of ["Spring","Summer","Autumn","Winter","Monsoon"]; empty if it does not flower
  "evergreen": true or false,
  "beauty": 1-10,             // how visually striking this species is
  "fact_type": "fun" or "normal" or "cool",
  "fact": "one accurate, interesting fact about the species",
  "neighbours": ["Common name (Genus species)", "..."]  // 4 other trees commonly found in the same habitat / region
}
If is_tree is false, fill only "subject", "is_tree" and "confidence" (0)."""


def _prep_image(path: str) -> bytes:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((1024, 1024))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
        return buf.getvalue()


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        return json.loads(match.group(0)) if match else {}


def _num(v, lo, hi, default):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


def _bool(v) -> bool:
    return v.strip().lower() == "true" if isinstance(v, str) else bool(v)


def _normalize(d: dict) -> dict:
    out = {
        "is_tree": _bool(d.get("is_tree")),
        "subject": str(d.get("subject") or "something"),
        "confidence": _num(d.get("confidence"), 0, 1, 0.0),
    }
    if not out["is_tree"]:
        return out
    bloom = [str(s).strip().capitalize() for s in (d.get("bloom_seasons") or [])]
    out.update(
        common_name=str(d.get("common_name") or "Unknown tree"),
        scientific_name=str(d.get("scientific_name") or ""),
        also_known_as=[str(x) for x in (d.get("also_known_as") or [])][:5],
        localities=[str(x) for x in (d.get("localities") or [])][:6],
        primary_region=str(d.get("primary_region") or "Unknown"),
        rarity=int(_num(d.get("rarity"), 1, 10, 5)),
        bloom_seasons=[s for s in bloom if s in SEASONS],
        evergreen=_bool(d.get("evergreen")),
        beauty=int(_num(d.get("beauty"), 1, 10, 5)),
        fact_type=str(d.get("fact_type") or "fun").lower(),
        fact=str(d.get("fact") or ""),
        neighbours=[str(x) for x in (d.get("neighbours") or [])][:6],
    )
    return out


def identify(image_path: str) -> dict:
    """Steps 1-3 in one call: is it a tree? which one? what do we know about it?"""
    resp = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": ID_PROMPT, "images": [_prep_image(image_path)]}],
        format="json",
        options={"temperature": 0.2},
    )
    return _normalize(_parse_json(resp["message"]["content"]))


# --------------------------------------------------------------------------- #
# Professor Sprout talking
# --------------------------------------------------------------------------- #
def react(situation: str) -> str:
    """One short in-character remark about something that just happened."""
    resp = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": PERSONA},
            {
                "role": "user",
                "content": f"[Situation: {situation}]\nReact to the student in 2-4 sentences, in character. "
                "Do not repeat numbers or the full species details; they are already shown on the card.",
            },
        ],
        options={"temperature": 0.7},
    )
    return resp["message"]["content"].strip()


_KIND_TEXT = {
    "new_species": "a brand-new species",
    "new_season": "a new season for a tree already in the Treedex (rarity not counted)",
    "repeat": "a repeat sighting this season (reduced by the log decay)",
}


def build_context(db: dict, season: str) -> str:
    sp = species_summary(db)
    season_known = season in SEASONS
    lines = [
        "[Treedex state. Only use the numbers below; never calculate or invent scores.]",
        f"Current season: {season if season_known else 'UNKNOWN. Ask the student to set it in the season dropdown above the chat.'}",
        f"Botany score: {db['score']} (rank: {rank(db['score'])}). Trees discovered: {len(sp)}.",
    ]
    if not sp:
        lines.append(
            "The student has NOT discovered any trees yet. Warmly encourage them to go outside, "
            "touch some grass, find a tree and send a photo."
        )
    for s in sp.values():
        t = s["tree"]
        seen = ", ".join(f"{k} x{v}" for k, v in s["seasons"].items())
        entry = (
            f"#{s['number']} {t['common_name']} ({t['scientific_name']}); found in: {seen}; "
            f"localities: {'; '.join(t['localities']) or 'unknown'}; rarity {t['rarity']}/10; "
            f"{'evergreen' if t['evergreen'] else 'deciduous/seasonal'}; "
            f"blooms: {', '.join(t['bloom_seasons']) or 'rarely/never'}; "
            f"trees commonly found in the same area: {'; '.join(t['neighbours']) or 'unknown'}"
        )
        if season_known:
            ev = evaluate(db, t, season, 0.9)
            entry += f"; points if photographed again now: about +{ev['total']} ({_KIND_TEXT[ev['kind']]})"
        lines.append(entry)
    lines.append(
        "When asked what grows near a tree, use the stored list and add what you know, naming each tree. "
        "When asked about potential score, use the 'points if photographed again now' figures."
    )
    return "\n".join(lines)


def chat_stream(history: list, user_text: str, db: dict, season: str):
    """Yield the growing reply text for a normal (no photo) chat turn."""
    messages = [{"role": "system", "content": PERSONA + "\n\n" + build_context(db, season)}]
    messages += history[-10:]
    messages.append({"role": "user", "content": user_text})
    text = ""
    for chunk in ollama.chat(model=MODEL, messages=messages, options={"temperature": 0.7}, stream=True):
        text += chunk["message"]["content"]
        yield text
