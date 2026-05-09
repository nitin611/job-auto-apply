"""Lever-hosted application form filler.

Application URL pattern: https://jobs.lever.co/<slug>/<id>/apply (or main page → Apply)
"""
from __future__ import annotations
import structlog
from app.apply.base import ApplyHandler
from app.browser.context import persistent_context
from app.browser.helpers import jitter, page_jitter, screenshot_path, detect_blocker
from app.models import Job
from app.schemas import ApplyResult
from app.services.profile import resume_pdf_path

log = structlog.get_logger()


class LeverApply:
    source = "lever"

    async def can_handle(self, job: Job) -> bool:
        return job.source == "lever" and "lever.co" in (job.url or "")

    async def apply(self, job: Job, profile: dict, cover_letter: str, dry_run: bool) -> ApplyResult:
        ident = profile.get("identity") or {}
        full_name = ident.get("full_name") or ""
        email = ident.get("email") or ""
        phone = ident.get("phone") or ""
        resume = resume_pdf_path()

        if dry_run:
            log.info("lever.dry_run", job_id=job.id, url=job.url)
            return ApplyResult(outcome="dry_run", confirmation_text="DRY_RUN: would have submitted")

        if not resume:
            return ApplyResult(outcome="needs_human", failure_reason="profile/resume.pdf missing")
        if not email or not full_name:
            return ApplyResult(outcome="needs_human", failure_reason="profile identity incomplete")

        apply_url = job.url
        if "/apply" not in apply_url:
            apply_url = apply_url.rstrip("/") + "/apply"

        async with persistent_context("lever", headless=True) as ctx:
            page = await ctx.new_page()
            try:
                await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
                await page_jitter()

                blocker = await detect_blocker(page)
                if blocker:
                    sp = screenshot_path(job.id, "captcha")
                    await page.screenshot(path=str(sp), full_page=True)
                    return ApplyResult(outcome="needs_human", failure_reason=f"blocker: {blocker}", screenshot_path=str(sp))

                async def fill(sel: str, val: str):
                    if not val:
                        return
                    loc = page.locator(sel).first
                    if await loc.count():
                        await loc.fill(val)
                        await jitter()

                await fill("input[name='name']", full_name)
                await fill("input[name='email']", email)
                await fill("input[name='phone']", phone)
                await fill("input[name='urls[LinkedIn]']", ident.get("linkedin_url") or "")
                await fill("input[name='urls[GitHub]']", ident.get("github_url") or "")
                await fill("input[name='urls[Portfolio]']", ident.get("portfolio_url") or "")

                resume_input = page.locator("input[type='file'][name='resume']").first
                if await resume_input.count():
                    await resume_input.set_input_files(str(resume))
                    await jitter(1.0, 2.0)

                cl = page.locator("textarea[name='comments']").first
                if cover_letter and await cl.count():
                    await cl.fill(cover_letter)
                    await jitter()

                submit = page.locator("button[type='submit'], input[type='submit']").first
                if not await submit.count():
                    sp = screenshot_path(job.id, "no_submit")
                    await page.screenshot(path=str(sp), full_page=True)
                    return ApplyResult(outcome="needs_human", failure_reason="submit button not found", screenshot_path=str(sp))

                await submit.click()
                await page.wait_for_load_state("networkidle", timeout=30000)
                await jitter(1.0, 2.0)

                body = (await page.locator("body").inner_text()).lower()
                if "thank you" in body or "application has been submitted" in body or "we received your application" in body:
                    return ApplyResult(outcome="submitted", confirmation_text=body[:500])

                sp = screenshot_path(job.id, "post_submit")
                await page.screenshot(path=str(sp), full_page=True)
                return ApplyResult(
                    outcome="needs_human",
                    failure_reason="no confirmation text detected",
                    screenshot_path=str(sp),
                )
            except Exception as e:
                sp = screenshot_path(job.id, "error")
                try:
                    await page.screenshot(path=str(sp), full_page=True)
                except Exception:
                    pass
                log.exception("lever.apply_error", job_id=job.id)
                return ApplyResult(outcome="failed", failure_reason=str(e)[:500], screenshot_path=str(sp))
