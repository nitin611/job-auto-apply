"""Gemini CLI subprocess wrapper.

Shells out to `gemini -p ... --output-format json --yolo` and returns a
normalised envelope dict {"result": text} — same shape as the Claude CLI wrapper.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
import structlog
from app.config import settings, ROOT

log = structlog.get_logger()

# Map Claude model aliases → Gemini model names
_MODEL_MAP = {
    "haiku": "gemini-2.0-flash",
    "sonnet": "gemini-2.0-flash",
    "opus": "gemini-1.5-pro",
}


class GeminiError(Exception):
    pass


async def call_gemini(
    prompt: str,
    system_prompt_path: Path | None = None,
    timeout: float = 90.0,
    model: str = "gemini-2.0-flash",
) -> dict:
    """Run a single Gemini CLI call. Returns {"result": text, ...}."""
    # Resolve model name (handle Claude aliases)
    resolved_model = _MODEL_MAP.get(model, model)

    # Gemini CLI has no --append-system-prompt, so prepend system text to prompt
    full_prompt = prompt
    if system_prompt_path and system_prompt_path.exists():
        try:
            sys_text = system_prompt_path.read_text().strip()
            if sys_text:
                full_prompt = f"{sys_text}\n\n---\n\n{prompt}"
        except Exception:
            pass

    # Read prefs to get user-configured model override
    try:
        from app.services.profile import load_preferences
        prefs = load_preferences()
        pref_model = prefs.get("llm", {}).get("gemini_model", "")
        if pref_model:
            resolved_model = pref_model
    except Exception:
        pass

    args = [
        settings.gemini_bin,
        "-p", full_prompt,
        "--output-format", "json",
        "--model", resolved_model,
        "--yolo",
    ]

    log.debug("gemini.call", prompt_len=len(full_prompt), model=resolved_model)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise GeminiError(f"timeout after {timeout}s")

    if proc.returncode != 0:
        raise GeminiError(
            f"exit {proc.returncode}: stdout={stdout.decode()[:300]} stderr={stderr.decode()[:300]}"
        )

    try:
        envelope = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        raise GeminiError(f"non-JSON envelope: {e}; raw={stdout[:300]}")

    # Normalise to {"result": text} — Gemini uses "response" key
    text = envelope.get("response") or envelope.get("result") or ""
    return {"result": text, "_raw": envelope}


async def health_check() -> tuple[bool, str]:
    """Verify `gemini` is installed and authenticated."""
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.gemini_bin, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return False, f"gemini --version failed: {stderr.decode()[:200]}"
        return True, stdout.decode().strip()
    except FileNotFoundError:
        return False, f"`{settings.gemini_bin}` binary not found in PATH"
    except Exception as e:
        return False, str(e)
