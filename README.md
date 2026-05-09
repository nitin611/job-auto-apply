# Auto Job Apply

Local-first job search + auto-apply system. See `TECHSPEC.md` for full design.

## Quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate.fish
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
# edit .env if needed
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 and configure your profile through the UI.

Drop your resume at `profile/resume.pdf` before the first apply run.

## Safety

`DRY_RUN=true` in `.env` is the default — pipeline will log what it would
submit but won't actually submit. Set to `false` only when you've reviewed
scored results and trust them.
