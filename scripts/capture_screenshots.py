import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def capture_all():
    docs_dir = Path("docs/images")
    docs_dir.mkdir(parents=True, exist_ok=True)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,  # Retina screenshot for crisp display
        )
        page = await context.new_page()
        
        pages_to_capture = [
            ("dashboard", "http://127.0.0.1:8010/#/dashboard"),
            ("auto_schedule", "http://127.0.0.1:8010/#/auto-schedule"),
            ("accounts", "http://127.0.0.1:8010/#/accounts"),
            ("run", "http://127.0.0.1:8010/#/run"),
            ("messages", "http://127.0.0.1:8010/#/messages"),
            ("logs", "http://127.0.0.1:8010/#/logs"),
        ]
        
        for name, url in pages_to_capture:
            print(f"Capturing {name} from {url}...")
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(1.5)  # Wait for animations and data rendering
            target_file = docs_dir / f"{name}.png"
            await page.screenshot(path=str(target_file), full_page=False)
            print(f"Saved {target_file}")
            
        await browser.close()
        print("All screenshots captured successfully!")

if __name__ == "__main__":
    asyncio.run(capture_all())
