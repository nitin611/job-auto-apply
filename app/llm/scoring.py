from app.llm.client import call_and_parse, call_claude, call_llm, extract_json, ClaudeError
from app.schemas import ScoreResult
from app.services.profile import build_system_prompt
from app.config import settings
import json
import structlog

log = structlog.get_logger()

BATCH_SIZE = 10


SCORING_PROMPT_SINGLE = """You are evaluating a job posting against a candidate's profile.

Job posting:
- Title: {title}
- Company: {company}
- Location: {location} ({work_mode})
- Description:
{description}

Score the fit from 0 to 10 considering title/seniority alignment, required skills,
location/work_mode match, compensation if mentioned, and any red flags.

Output ONLY a JSON object in a fenced ```json block:
```json
{{
  "score": <number 0-10>,
  "rationale": "<1-2 sentence explanation>",
  "match_highlights": ["<bullet1>", "<bullet2>", "<bullet3>"],
  "red_flags": ["<flag1>"]
}}
```
"""


SCORING_PROMPT_BATCH = """You are evaluating multiple job postings against a candidate's profile.

For EACH job below, score the fit from 0 to 10 considering title/seniority alignment,
required skills, location/work_mode match, compensation if mentioned, and red flags.

Jobs:
{jobs_block}

Output ONLY a JSON object in a fenced ```json block, with results in the SAME ORDER as the
input jobs (one entry per job). If any job is unparseable, give it score 0 with rationale
"unparseable" — never fail the whole batch.

```json
{{
  "results": [
    {{"id": <job_id>, "score": <0-10>, "rationale": "<1-2 sentences>",
      "match_highlights": ["..."], "red_flags": ["..."]}}
  ]
}}
```
"""


async def score_job(title: str, company: str, location: str, work_mode: str, description: str) -> ScoreResult:
    _, _ = build_system_prompt()
    sys_path = settings.profile_dir / "system_prompt.md"
    prompt = SCORING_PROMPT_SINGLE.format(
        title=title or "",
        company=company or "",
        location=location or "Unknown",
        work_mode=work_mode or "unknown",
        description=(description or "")[:4000],
    )
    data = await call_and_parse(prompt, system_prompt_path=sys_path, retries=1)
    return ScoreResult(
        score=float(data.get("score", 0)),
        rationale=str(data.get("rationale", "")),
        red_flags=list(data.get("red_flags") or []),
        match_highlights=list(data.get("match_highlights") or []),
    )


async def score_jobs_batch(items: list[dict]) -> dict[int, ScoreResult]:
    """Score up to BATCH_SIZE jobs in one Claude call.

    items: [{"id": int, "title": str, "company": str, "location": str,
             "work_mode": str, "description": str}, ...]
    Returns: {id: ScoreResult}
    """
    if not items:
        return {}
    _, _ = build_system_prompt()
    sys_path = settings.profile_dir / "system_prompt.md"

    blocks = []
    for it in items:
        blocks.append(
            f"--- job_id={it['id']} ---\n"
            f"Title: {it.get('title','')}\n"
            f"Company: {it.get('company','')}\n"
            f"Location: {it.get('location') or 'Unknown'} ({it.get('work_mode') or 'unknown'})\n"
            f"Description:\n{(it.get('description') or '')[:1200]}\n"
        )
    prompt = SCORING_PROMPT_BATCH.format(jobs_block="\n\n".join(blocks))

    envelope = await call_llm(prompt, system_prompt_path=sys_path, timeout=180.0, model="haiku")
    text = envelope.get("result", "") or ""
    try:
        data = extract_json(text)
        results = data.get("results") or []
    except ClaudeError as e:
        log.warning("batch_score.parse_failed", error=str(e), preview=text[:300])
        return {}

    out: dict[int, ScoreResult] = {}
    for r in results:
        try:
            jid = int(r.get("id"))
            out[jid] = ScoreResult(
                score=float(r.get("score", 0)),
                rationale=str(r.get("rationale", "")),
                red_flags=list(r.get("red_flags") or []),
                match_highlights=list(r.get("match_highlights") or []),
            )
        except Exception:
            continue
    return out
