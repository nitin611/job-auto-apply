from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
from app.config import settings


@asynccontextmanager
async def persistent_context(source: str, headless: bool = True):
    """Persistent BrowserContext per source — cookies survive between runs."""
    state_dir = settings.browser_state_dir / source
    state_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(state_dir),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        try:
            yield ctx
        finally:
            await ctx.close()
