"""Lever public postings API client.

Endpoint: GET https://api.lever.co/v0/postings/<slug>?mode=json
"""
from __future__ import annotations
import asyncio
from datetime import datetime
import httpx
import structlog
from app.schemas import JobPosting

log = structlog.get_logger()

BASE = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverSource:
    name = "lever"
    transport = "http"

    async def _fetch_one(self, client: httpx.AsyncClient, slug: str) -> list[JobPosting]:
        url = BASE.format(slug=slug)
        try:
            r = await client.get(url, timeout=20.0)
            if r.status_code != 200:
                log.warning("lever.fetch_failed", slug=slug, status=r.status_code)
                return []
            data = r.json()
        except Exception as e:
            log.warning("lever.fetch_error", slug=slug, error=str(e))
            return []

        out: list[JobPosting] = []
        for j in data:
            cats = j.get("categories") or {}
            location = cats.get("location") or ""
            commitment = cats.get("commitment") or ""
            workplace = (cats.get("allLocations") or [""])[0] if cats.get("allLocations") else ""
            description = j.get("descriptionPlain") or _strip(j.get("description") or "")
            posted_ms = j.get("createdAt")
            posted_at = datetime.utcfromtimestamp(posted_ms / 1000) if posted_ms else None
            out.append(JobPosting(
                source="lever",
                source_job_id=j.get("id"),
                url=j.get("hostedUrl") or j.get("applyUrl") or "",
                canonical_url=j.get("hostedUrl") or j.get("applyUrl") or "",
                title=j.get("text", ""),
                company=slug,
                location=location or workplace,
                work_mode=_infer(location, j.get("workplaceType") or commitment),
                description_md=description,
                posted_at=posted_at,
                apply_handler="lever",
                raw_payload={"slug": slug, "id": j.get("id")},
            ))
        return out

    async def search(self, prefs: dict) -> list[JobPosting]:
        cfg = (prefs.get("sources") or {}).get("lever") or {}
        if not cfg.get("enabled", False):
            return []
        slugs = cfg.get("company_slugs") or []
        if not slugs:
            return []
        async with httpx.AsyncClient() as client:
            tasks = [self._fetch_one(client, s) for s in slugs]
            results = await asyncio.gather(*tasks)
        flat = [j for batch in results for j in batch]
        log.info("lever.search_done", count=len(flat), companies=len(slugs))
        return flat


def _strip(html: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def _infer(location: str, workplace: str) -> str:
    s = ((location or "") + " " + (workplace or "")).lower()
    if "remote" in s:
        return "remote"
    if "hybrid" in s:
        return "hybrid"
    if location:
        return "onsite"
    return "unknown"
