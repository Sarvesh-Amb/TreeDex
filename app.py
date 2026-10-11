"""Treedex: touch grass edition. Run with `python app.py`."""
import hashlib

import gradio as gr

import scoring
import sprout
import store
from scoring import SEASONS

MIN_CONFIDENCE = 0.35  # below this we ask for a better photo instead of logging
_id_cache: dict = {}  # file hash -> identification, so re-sending a photo after setting the season is instant

GREETING = (
    "<b>Professor Pomona Sprout</b><br>Welcome to Greenhouse Three, dear! Send me a photo of a tree "
    "and I'll tell you what it is. Set the current season in the box above first, so I can score it properly."
)


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def _path(f) -> str:
    return f if isinstance(f, str) else f.get("path", "")


def build_card(t: dict) -> str:
    bar = "▰" * t["rarity"] + "▱" * (10 - t["rarity"])
    foliage = "🌲 Evergreen" if t["evergreen"] else "🍂 Not evergreen (loses or changes its leaves)"
    bloom = ("🌸 Blossoms: " + ", ".join(t["bloom_seasons"])) if t["bloom_seasons"] else "🌸 Rarely / never blossoms"
    names = f"\n**Better known as:** {', '.join(t['also_known_as'])}" if t["also_known_as"] else ""
    return (
        f"### 🌳 {t['common_name']}  ·  {t['confidence']:.0%} confident\n"
        f"**Species:** *{t['scientific_name']}*{names}\n\n"
        f"**Found in:** {'; '.join(t['localities']) or 'unknown'}\n\n"
        f"**Rarity:** {t['rarity']}/10 {bar}\n\n"
        f"{foliage}  ·  {bloom}\n\n"
        f"**{t['fact_type'].capitalize()} fact:** {t['fact']}"
    )


def build_score_block(initial: float, result: dict, new: float) -> str:
    breakdown = "\n".join(f"- `{line}`" for line in result["lines"])
    return (
        "**Botany score calculation**\n\n"
        f"| | |\n|---|---|\n"
        f"| Initial botany score | {initial:.1f} |\n"
        f"| Given tree score | **+{result['total']:.1f}** |\n"
        f"| New score | **{new:.1f}**  ({scoring.rank(new)}) |\n\n"
        f"<details><summary>How that was worked out</summary>\n\n{breakdown}\n\n</details>"
    )


# --------------------------------------------------------------------------- #
# Photo flow
# --------------------------------------------------------------------------- #
def handle_photo(path: str, season: str):
    yield "🔍 *Professor Sprout is polishing her spectacles...*"

    with open(path, "rb") as fh:
        digest = hashlib.sha1(fh.read()).hexdigest()
    tree = _id_cache.get(digest)
    if tree is None:
        tree = sprout.identify(path)
        _id_cache[digest] = tree

    # 1) is it a tree?
    if not tree["is_tree"]:
        remark = sprout.react(
            f"The student showed you a photo of: {tree['subject']}. It is not a tree. "
            "Gently say so and send them off to find a real tree."
        )
        yield f"🚫 **Not a tree.**\n\n🧤 *Professor Sprout:* {remark}"
        return

    # 2) confident enough?
    if tree["confidence"] < MIN_CONFIDENCE:
        remark = sprout.react(
            f"It looks like a tree but you can't tell the species (confidence {tree['confidence']:.0%}). "
            "Ask for a clearer photo: leaves, bark, flowers or fruit up close."
        )
        yield f"🤔 **Not sure what this one is.** Nothing logged.\n\n🧤 *Professor Sprout:* {remark}"
        return

    card = build_card(tree)

    # 3) season needed for the score
    if season not in SEASONS:
        remark = sprout.react(
            "You identified the tree but the student has not told you what season it is where they are, "
            "so you can't score it. Ask them to pick the season in the dropdown above the chat and send the photo again."
        )
        yield f"{card}\n\n---\n⏸️ **Not logged yet (season not set).**\n\n🧤 *Professor Sprout:* {remark}"
        return

    # 4) score + log
    db = store.load()
    result = scoring.evaluate(db, tree, season, tree["confidence"])
    initial = db["score"]
    store.add_find(db, tree, season, tree["confidence"], result["total"], store.save_photo(path))
    block = build_score_block(initial, result, db["score"])
    yield f"{card}\n\n---\n{block}"

    remark = sprout.react(
        f"The student photographed a {tree['common_name']} in {season}. "
        f"This counted as {sprout._KIND_TEXT[result['kind']]}. Congratulate or encourage them accordingly."
    )
    yield f"{card}\n\n---\n{block}\n\n🧤 *Professor Sprout:* {remark}"


# --------------------------------------------------------------------------- #
# Chat entry point
# --------------------------------------------------------------------------- #
def respond(message, history, season):
    text = (message.get("text") or "").strip()
    images = [_path(f) for f in (message.get("files") or [])]
    llm_history = [
        {"role": m["role"], "content": m["content"][:600]}
        for m in history
        if isinstance(m.get("content"), str)
    ]
    try:
        done = []
        for img in images:
            for chunk in handle_photo(img, season):
                yield "\n\n---\n\n".join(done + [chunk])
            done.append(chunk)
        if text:
            prefix = "\n\n---\n\n".join(done)
            for partial in sprout.chat_stream(llm_history, text, store.load(), season):
                yield (prefix + "\n\n---\n\n" if prefix else "") + partial
    except Exception as e:  # most likely: Ollama not running / model not pulled
        yield (
            f"🪴 *Oh dear, the greenhouse door is stuck!* I can't reach Gemma.\n\n"
            f"Check that Ollama is running (`ollama serve`) and that you've run `ollama pull {sprout.MODEL}`.\n\n"
            f"`{type(e).__name__}: {e}`"
        )


# --------------------------------------------------------------------------- #
# Treedex tab
# --------------------------------------------------------------------------- #
def render_dex():
    db = store.load()
    sp = store.species_summary(db)
    header = (
        f"## Botany score: {db['score']:.1f}  ·  {scoring.rank(db['score'])}\n"
        f"{len(sp)} species discovered · {len(db['finds'])} sightings logged"
    )
    gallery = [
        (s["photo"], f"#{s['number']:03d} {s['tree']['common_name']}") for s in sp.values() if s.get("photo")
    ]
    rows = [
        [
            f"#{s['number']:03d}",
            s["tree"]["common_name"],
            s["tree"]["scientific_name"],
            s["tree"]["rarity"],
            ", ".join(f"{k} x{v}" for k, v in s["seasons"].items()),
            s["count"],
        ]
        for s in sp.values()
    ]
    return header, gallery, rows


with gr.Blocks(title="Treedex") as demo:
    gr.Markdown("# 🌳 Treedex: touch grass edition")
    with gr.Tabs():
        with gr.Tab("Greenhouse Three"):
            season = gr.Dropdown(
                ["Not set"] + SEASONS, value="Not set", label="Current season where you are", interactive=True
            )
            gr.ChatInterface(
                fn=respond,
                type="messages",
                multimodal=True,
                additional_inputs=[season],
                chatbot=gr.Chatbot(type="messages", height=560, placeholder=GREETING),
                textbox=gr.MultimodalTextbox(
                    file_types=["image"], placeholder="Send a tree photo, or ask Professor Sprout anything..."
                ),
            )
        with gr.Tab("Treedex") as dex_tab:
            header = gr.Markdown()
            gallery = gr.Gallery(label="Discovered trees", columns=4, height=380)
            table = gr.Dataframe(
                headers=["#", "Tree", "Species", "Rarity", "Seasons found", "Times found"], interactive=False
            )
            refresh = gr.Button("Refresh")
    outputs = [header, gallery, table]
    refresh.click(render_dex, None, outputs)
    dex_tab.select(render_dex, None, outputs)
    demo.load(render_dex, None, outputs)

if __name__ == "__main__":
    demo.launch()
