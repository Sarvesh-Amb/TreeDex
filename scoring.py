"""Botany score maths. All scoring is done in code, never by the LLM.

Per-find points
---------------
  beauty            beauty (1-10) x 4
  in bloom          +25 if found during one of the tree's blossom seasons
  evergreen         +5
  rarity            rarity (1-10) x 10          <- NEW SPECIES ONLY
  new genus         +10                          <- NEW SPECIES ONLY
  new region        +10                          <- NEW SPECIES ONLY
  confidence        everything x (0.5 + 0.5 * confidence)

Rules
-----
  new species                    -> all of the above
  known species, new season      -> same, but rarity (and discovery bonuses) removed
  known species, same season     -> the "new season" score x 1 / (1 + ln(1 + n))
                                    n = times already found in that season, so each
                                    repeat is worth less, following a log curve.
"""
import math

from store import species_key, species_summary

SEASONS = ["Spring", "Summer", "Autumn", "Winter", "Monsoon"]

RANKS = [
    (0, "Seedling"),
    (150, "Greenhouse Helper"),
    (400, "Herbology Prefect"),
    (900, "Master Gardener"),
    (1800, "Keeper of the Greenhouses"),
]


def rank(score: float) -> str:
    title = RANKS[0][1]
    for threshold, name in RANKS:
        if score >= threshold:
            title = name
    return title


def evaluate(db: dict, tree: dict, season: str, confidence: float = 1.0) -> dict:
    """Work out what finding `tree` in `season` would add to the botany score.

    Returns {"kind": new_species|new_season|repeat, "total": float, "lines": [str]}
    """
    sp = species_summary(db)
    key = species_key(tree)
    seen = sp.get(key)

    parts = [(f"Perceived beauty ({tree['beauty']}/10 x 4)", tree["beauty"] * 4)]
    if season in tree["bloom_seasons"]:
        parts.append((f"In bloom this {season}", 25))
    if tree["evergreen"]:
        parts.append(("Evergreen", 5))

    factors = []  # (label, multiplier)
    if seen is None:
        kind = "new_species"
        parts.append((f"Rarity ({tree['rarity']}/10 x 10)", tree["rarity"] * 10))
        genera = {species_key(s["tree"]).split()[0] for s in sp.values()}
        if key.split()[0] not in genera:
            parts.append(("New genus", 10))
        regions = {s["tree"]["primary_region"].lower() for s in sp.values()}
        if tree["primary_region"].lower() not in regions:
            parts.append(("New region", 10))
    elif season not in seen["seasons"]:
        kind = "new_season"  # rarity is deliberately left out
    else:
        kind = "repeat"
        n = seen["seasons"][season]
        factors.append((f"Repeat sighting #{n + 1} in {season} (log decay)", 1 / (1 + math.log(1 + n))))

    factors.append((f"Identification confidence ({confidence:.0%})", 0.5 + 0.5 * confidence))

    subtotal = sum(p for _, p in parts)
    total = subtotal
    lines = [f"+{p:.0f}  {label}" for label, p in parts]
    for label, mult in factors:
        total *= mult
        lines.append(f"x{mult:.2f}  {label}")
    return {"kind": kind, "total": round(total, 1), "lines": lines}
