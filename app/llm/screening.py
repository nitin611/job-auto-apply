"""Answer screening questions using profile/answers.yaml + LLM fallback."""
from app.llm.client import call_and_parse
from app.services.profile import load_answers, build_system_prompt
from app.config import settings


PROMPT = """The candidate is applying for a job. Answer these screening questions
using the candidate profile. For each question, return an answer plus a
confidence value (0-1) and a source ("answers.yaml" if drawn from canonical
answers, "resume" if inferred from resume content, "synthesized" if generated).

Questions:
{questions}

Output ONLY JSON in a fenced ```json block:
```json
{{
  "answers": [
    {{"question": "...", "answer": "...", "confidence": 0.95, "source": "answers.yaml"}}
  ]
}}
```
"""


async def answer_screening(questions: list[dict]) -> list[dict]:
    if not questions:
        return []
    answers_yaml = load_answers()
    _, _ = build_system_prompt()
    sys_path = settings.profile_dir / "system_prompt.md"
    qtext = "\n".join(
        f"- {q.get('question', '')} (type={q.get('type','text')}"
        + (f", options={q.get('options')}" if q.get('options') else "")
        + ")"
        for q in questions
    )
    data = await call_and_parse(PROMPT.format(questions=qtext), system_prompt_path=sys_path)
    return list(data.get("answers") or [])
