"""Greenhouse public boards API client.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/<slug>/jobs?content=true
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import re
import httpx
import structlog
from app.schemas import JobPosting

log = structlog.get_logger()

BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_posted(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


class GreenhouseSource:
    name = "greenhouse"
    transport = "http"

    async def _fetch_one(self, client: httpx.AsyncClient, slug: str) -> list[JobPosting]:
        url = BASE.format(slug=slug) + "?content=true"
        try:
            r = await client.get(url, timeout=20.0)
            if r.status_code != 200:
                log.warning("greenhouse.fetch_failed", slug=slug, status=r.status_code)
                return []
            data = r.json()
        except Exception as e:
            log.warning("greenhouse.fetch_error", slug=slug, error=str(e))
            return []

        out: list[JobPosting] = []
        for j in data.get("jobs", []):
            content = _strip_html(j.get("content", ""))
            location = (j.get("location") or {}).get("name") or ""
            out.append(JobPosting(
                source="greenhouse",
                source_job_id=str(j.get("id")) if j.get("id") else None,
                url=j.get("absolute_url", ""),
                canonical_url=j.get("absolute_url", ""),
                title=j.get("title", ""),
                company=slug,
                location=location,
                work_mode=_infer_work_mode(location, j.get("title", "") + " " + content[:500]),
                description_md=content,
                posted_at=_parse_posted(j.get("updated_at") or j.get("first_published")),
                apply_handler="greenhouse",
                raw_payload={"slug": slug, "id": j.get("id")},
            ))
        return out

    async def search(self, prefs: dict) -> list[JobPosting]:
        cfg = (prefs.get("sources") or {}).get("greenhouse") or {}
        if not cfg.get("enabled", False):
            return []
        slugs = cfg.get("company_slugs") or []
        if not slugs:
            return []
        async with httpx.AsyncClient() as client:
            tasks = [self._fetch_one(client, s) for s in slugs]
            results = await asyncio.gather(*tasks)
        flat = [j for batch in results for j in batch]
        log.info("greenhouse.search_done", count=len(flat), companies=len(slugs))
        return flat


def _infer_work_mode(location: str, text: str) -> str:
    s = (location + " " + text).lower()
    if "remote" in s:
        return "remote"
    if "hybrid" in s:
        return "hybrid"
    if location:
        return "onsite"
    return "unknown"
