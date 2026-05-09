import hashlib
from pathlib import Path
from typing import Any
import yaml
from app.config import settings


def _read(p: Path) -> str:
    return p.read_text() if p.exists() else ""


def load_preferences() -> dict[str, Any]:
    p = settings.profile_dir / "preferences.yaml"
    return yaml.safe_load(_read(p)) or {}


def save_preferences(data: dict[str, Any]) -> None:
    p = settings.profile_dir / "preferences.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def load_answers() -> dict[str, Any]:
    p = settings.profile_dir / "answers.yaml"
    return yaml.safe_load(_read(p)) or {}


def save_answers(data: dict[str, Any]) -> None:
    p = settings.profile_dir / "answers.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def load_resume_md() -> str:
    return _read(settings.profile_dir / "resume.md")


def save_resume_md(text: str) -> None:
    p = settings.profile_dir / "resume.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def load_skills_md() -> str:
    return _read(settings.profile_dir / "skills.md")


def save_skills_md(text: str) -> None:
    p = settings.profile_dir / "skills.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def build_system_prompt() -> tuple[str, str]:
    """Concatenate profile sources into a system prompt; return (text, sha1)."""
    prefs = load_preferences()
    answers = load_answers()
    parts = [
        "# Candidate Profile",
        "",
        "## Resume",
        load_resume_md(),
        "",
        "## Skills",
        load_skills_md(),
        "",
        "## Preferences",
        yaml.safe_dump(prefs, sort_keys=False),
        "",
        "## Screening Answers (canonical)",
        yaml.safe_dump(answers, sort_keys=False),
    ]
    text = "\n".join(parts)
    h = hashlib.sha1(text.encode()).hexdigest()
    out = settings.profile_dir / "system_prompt.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    return text, h


def resume_pdf_path() -> Path | None:
    p = settings.profile_dir / "resume.pdf"
    return p if p.exists() else None
