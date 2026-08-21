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
            device_scale_factor=2,  # Crisp retina scale
        )
        page = await context.new_page()
        
        pages_to_capture = [
            ("dashboard", "http://127.0.0.1:8010/dashboard", "text=运行看板"),
            ("auto_schedule", "http://127.0.0.1:8010/auto-schedule", "text=自动续火花"),
            ("accounts", "http://127.0.0.1:8010/accounts", "text=账号资产与凭证管理"),
            ("run", "http://127.0.0.1:8010/run", "text=手动执行与调度触发"),
            ("messages", "http://127.0.0.1:8010/messages", "text=消息与话术配置"),
            ("logs", "http://127.0.0.1:8010/logs", "text=运行日志"),
        ]
        
        for name, url, wait_selector in pages_to_capture:
            print(f"--> Navigating to {name}: {url}")
            await page.goto(url, wait_until="networkidle")
            try:
                await page.wait_for_selector(wait_selector, timeout=5000)
            except Exception as e:
                print(f"Warning waiting for {wait_selector}: {e}")
            await asyncio.sleep(1.0)  # Wait for element animations/data to settle
            
            target_file = docs_dir / f"{name}.png"
            await page.screenshot(path=str(target_file), full_page=False)
            print(f"Saved {target_file}")
            
        await browser.close()
        print("All unique screenshots captured successfully!")

if __name__ == "__main__":
    asyncio.run(capture_all())
