"""Claude Code CLI subprocess wrapper.

Shells out to `claude -p ... --output-format json` and returns parsed output.
No ANTHROPIC_API_KEY required — uses the user's local Claude Code login.
"""
from __future__ import annotations
import asyncio
import json
import re
from pathlib import Path
import structlog
from app.config import settings, ROOT

log = structlog.get_logger()

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FIRST_OBJ = re.compile(r"(\{.*\})", re.DOTALL)


class ClaudeError(Exception):
    pass


async def call_claude(
    prompt: str,
    system_prompt_path: Path | None = None,
    timeout: float = 90.0,
    model: str = "haiku",
) -> dict:
    """Run a single Claude Code call. Returns {result, total_cost_usd, ...}."""
    args = [
        settings.claude_bin,
        "-p", prompt,
        "--output-format", "json",
        "--model", model,
        "--permission-mode", "bypassPermissions",
        "--tools", "",
    ]
    if system_prompt_path and system_prompt_path.exists():
        try:
            sys_text = system_prompt_path.read_text()
            if sys_text.strip():
                args += ["--append-system-prompt", sys_text]
        except Exception:
            pass

    log.debug("claude.call", prompt_len=len(prompt), model=model)
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
        raise ClaudeError(f"timeout after {timeout}s")

    if proc.returncode != 0:
        raise ClaudeError(f"exit {proc.returncode}: stdout={stdout.decode()[:300]} stderr={stderr.decode()[:300]}")

    try:
        envelope = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        raise ClaudeError(f"non-JSON envelope: {e}; raw={stdout[:300]}")
    return envelope


def extract_json(text: str) -> dict:
    """Extract first JSON object from Claude's text response."""
    if not text:
        raise ClaudeError("empty response")
    m = _JSON_BLOCK.search(text)
    candidate = m.group(1) if m else None
    if candidate is None:
        m = _FIRST_OBJ.search(text)
        candidate = m.group(1) if m else None
    if candidate is None:
        raise ClaudeError(f"no JSON in response: {text[:300]}")
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ClaudeError(f"JSON parse failed: {e}; candidate={candidate[:300]}")


def _active_provider() -> str:
    """Return the currently configured LLM provider (reads prefs at call time)."""
    try:
        from app.services.profile import load_preferences
        prefs = load_preferences()
        return prefs.get("llm", {}).get("provider") or settings.llm_provider
    except Exception:
        return settings.llm_provider


async def call_llm(
    prompt: str,
    system_prompt_path: Path | None = None,
    timeout: float = 90.0,
    model: str = "haiku",
) -> dict:
    """Unified LLM call — routes to Claude CLI or Gemini CLI based on preferences."""
    provider = _active_provider()
    if provider == "gemini_cli":
        from app.llm.gemini_client import call_gemini
        return await call_gemini(prompt, system_prompt_path=system_prompt_path, timeout=timeout, model=model)
    return await call_claude(prompt, system_prompt_path=system_prompt_path, timeout=timeout, model=model)


async def call_and_parse(prompt: str, system_prompt_path: Path | None = None, retries: int = 1) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            envelope = await call_llm(prompt, system_prompt_path=system_prompt_path)
            result_text = envelope.get("result", "") or envelope.get("text", "")
            return extract_json(result_text)
        except (ClaudeError, Exception) as e:
            last_err = e
            log.warning("llm.parse_failed", attempt=attempt, error=str(e))
            await asyncio.sleep(1.0)
    raise last_err or ClaudeError("unknown failure")


async def health_check() -> tuple[bool, str]:
    """Verify `claude` is installed and authenticated."""
    try:
        proc = await asyncio.create_subprocess_exec(
            settings.claude_bin, "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            return False, f"claude --version failed: {stderr.decode()[:200]}"
        return True, stdout.decode().strip()
    except FileNotFoundError:
        return False, f"`{settings.claude_bin}` binary not found in PATH"
    except Exception as e:
        return False, str(e)
