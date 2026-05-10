from app.llm.client import call_llm
from app.services.profile import build_system_prompt
from app.config import settings


COVER_LETTER_PROMPT = """Write a tailored cover letter (150-200 words) for this role.

Role:
- {title} at {company}
- Description:
{description}

Requirements:
- 2-3 specific references to the job description
- Match resume bullets where relevant
- Professional but not stiff
- No "Dear Hiring Manager" template; open with a strong hook
- No JSON, no markdown formatting, just the letter body as plain text.
"""


async def generate_cover_letter(title: str, company: str, description: str) -> str:
    _, _ = build_system_prompt()
    sys_path = settings.profile_dir / "system_prompt.md"
    prompt = COVER_LETTER_PROMPT.format(
        title=title or "",
        company=company or "",
        description=(description or "")[:4000],
    )
    envelope = await call_llm(prompt, system_prompt_path=sys_path, timeout=90.0, model="sonnet")
    return (envelope.get("result") or "").strip()
