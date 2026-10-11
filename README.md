# 🌳 Treedex: touch grass edition

A local, Pokédex-style tree logger. Gemma (via Ollama) identifies trees from photos,
Professor Pomona Sprout chats about them, and your botany score grows as you collect.

## Setup
1. Install [Ollama](https://ollama.com) and pull a Gemma vision model:
   ```
   ollama pull gemma3:4b      # ~8 GB RAM; use gemma3:12b for better species IDs
   ```
2. Install and run:
   ```
   pip install -r requirements.txt
   python app.py
   ```
3. Open http://127.0.0.1:7860, set the season, and upload a tree photo.

Use a different model with `TREEDEX_MODEL=gemma3:12b python app.py`.
Your dex lives in `data/treedex.json` (photos in `data/photos/`). Delete `data/` to reset.

## Files
- `app.py`: Gradio UI (chat + Treedex tab) and the photo flow
- `sprout.py`: Gemma calls, identification prompt, Professor Sprout persona
- `scoring.py`: botany score maths (all in code, not the LLM)
- `store.py`: JSON log + photo thumbnails
