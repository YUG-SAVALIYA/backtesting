import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        page.on("console", lambda msg: print(f"CONSOLE: {msg.type} {msg.text}"))
        page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
        
        await page.goto("http://localhost:8000")
        await page.wait_for_timeout(2000)
        
        print("Clicking backtester...")
        await page.evaluate("switchModule('backtester')")
        await page.wait_for_timeout(1000)
        
        print("Active module after click:")
        active = await page.evaluate("document.querySelector('.module-pane.active').id")
        print("Active ID:", active)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
