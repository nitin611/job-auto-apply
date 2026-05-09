"""Greenhouse-hosted application form filler.

Greenhouse application URL pattern: https://boards.greenhouse.io/<slug>/jobs/<id>
The "Apply" button reveals an inline form on the same page.
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


class GreenhouseApply:
    source = "greenhouse"

    async def can_handle(self, job: Job) -> bool:
        return job.source == "greenhouse" and "greenhouse.io" in (job.url or "")

    async def apply(self, job: Job, profile: dict, cover_letter: str, dry_run: bool) -> ApplyResult:
        ident = profile.get("identity") or {}
        first, _, last = (ident.get("full_name") or "").partition(" ")
        email = ident.get("email") or ""
        phone = ident.get("phone") or ""
        resume = resume_pdf_path()

        if dry_run:
            log.info("greenhouse.dry_run", job_id=job.id, url=job.url)
            return ApplyResult(outcome="dry_run", confirmation_text="DRY_RUN: would have submitted")

        if not resume:
            return ApplyResult(outcome="needs_human", failure_reason="profile/resume.pdf missing")
        if not email or not first:
            return ApplyResult(outcome="needs_human", failure_reason="profile identity incomplete")

        async with persistent_context("greenhouse", headless=True) as ctx:
            page = await ctx.new_page()
            try:
                await page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
                await page_jitter()

                blocker = await detect_blocker(page)
                if blocker:
                    sp = screenshot_path(job.id, "captcha")
                    await page.screenshot(path=str(sp), full_page=True)
                    return ApplyResult(outcome="needs_human", failure_reason=f"blocker: {blocker}", screenshot_path=str(sp))

                # Greenhouse forms have stable field IDs.
                async def fill(sel: str, val: str):
                    if not val:
                        return
                    loc = page.locator(sel).first
                    if await loc.count():
                        await loc.fill(val)
                        await jitter()

                await fill("input#first_name", first)
                await fill("input#last_name", last or first)
                await fill("input#email", email)
                await fill("input#phone", phone)

                # Resume upload
                resume_input = page.locator("input[type='file'][name*='resume' i], input#resume").first
                if await resume_input.count():
                    await resume_input.set_input_files(str(resume))
                    await jitter(1.0, 2.0)

                # Cover letter — either textarea or upload
                cl_text = page.locator("textarea[name*='cover' i], textarea#cover_letter_text").first
                if cover_letter and await cl_text.count():
                    await cl_text.fill(cover_letter)
                    await jitter()

                # LinkedIn URL if a field exists
                li_url = (ident.get("linkedin_url") or "")
                if li_url:
                    li_loc = page.locator("input[name*='linkedin' i], input[id*='linkedin' i]").first
                    if await li_loc.count():
                        await li_loc.fill(li_url)
                        await jitter()

                # Submit
                submit = page.locator("button#submit_app, button[type='submit']:has-text('Submit')").first
                if not await submit.count():
                    sp = screenshot_path(job.id, "no_submit")
                    await page.screenshot(path=str(sp), full_page=True)
                    return ApplyResult(outcome="needs_human", failure_reason="submit button not found", screenshot_path=str(sp))

                await submit.click()
                await page.wait_for_load_state("networkidle", timeout=30000)
                await jitter(1.0, 2.0)

                # Confirmation detection
                body = (await page.locator("body").inner_text()).lower()
                if "thank you" in body or "received your application" in body or "application submitted" in body:
                    return ApplyResult(outcome="submitted", confirmation_text=body[:500])

                sp = screenshot_path(job.id, "post_submit")
                await page.screenshot(path=str(sp), full_page=True)
                return ApplyResult(
                    outcome="needs_human",
                    failure_reason="no confirmation text detected after submit",
                    screenshot_path=str(sp),
                )
            except Exception as e:
                sp = screenshot_path(job.id, "error")
                try:
                    await page.screenshot(path=str(sp), full_page=True)
                except Exception:
                    pass
                log.exception("greenhouse.apply_error", job_id=job.id)
                return ApplyResult(outcome="failed", failure_reason=str(e)[:500], screenshot_path=str(sp))
