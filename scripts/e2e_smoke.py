"""Run a real-browser smoke test against the local simulator."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for_server(process: subprocess.Popen[bytes], url: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Test server exited early with code {process.returncode}.")
        try:
            with urlopen(f"{url}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.2)
    raise TimeoutError("The simulator did not start within 20 seconds.")


def choose_measure(page, measure_id: str, district_id: str | None = None) -> None:
    if district_id:
        page.locator(f'[data-district-select="{measure_id}"]').select_option(district_id)
    page.locator(f'[data-add="{measure_id}"]').click()


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    # Exercise the deterministic fallback; this smoke test must never call a paid AI API.
    environment["OPENAI_API_KEY"] = ""
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    try:
        wait_for_server(process, base_url)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(base_url, wait_until="networkidle")
            page.locator("#workspace").wait_for(state="visible")

            choose_measure(page, "M7", "nura")
            choose_measure(page, "M8", "nura")
            choose_measure(page, "M10", "nura")
            choose_measure(page, "M12")
            choose_measure(page, "M5", "saryarka")

            calculate = page.locator("#calculate-button")
            expect(calculate).to_be_enabled(timeout=5_000)
            if page.locator("#budget-spent").inner_text() != "95":
                raise AssertionError("The reference scenario should spend 95 budget units.")

            calculate.click()
            expect(page.locator("#result-score")).to_have_text("56.54", timeout=15_000)
            alternatives = page.locator(".alternative-card")
            if alternatives.count() != 3:
                raise AssertionError("The reference scenario should show three validated alternatives.")
            if "+0.67 к сценарию" not in alternatives.first.inner_text():
                raise AssertionError("The best alternative should show a +0.67 displayed score change.")

            page.locator('[data-use-alternative="0"]').click()
            page.locator(".selection-slot.filled .slot-measure-name").filter(
                has_text="Линия ЛРТ / расширение"
            ).wait_for(timeout=5_000)
            calculate = page.locator("#calculate-button")
            expect(calculate).to_be_enabled(timeout=5_000)
            calculate.click()
            expect(page.locator("#result-score")).to_have_text("57.21", timeout=15_000)

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.on("pageerror", lambda error: page_errors.append(str(error)))
            mobile.goto(base_url, wait_until="networkidle")
            mobile.locator("#workspace").wait_for(state="visible")
            has_horizontal_overflow = mobile.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth"
            )
            if has_horizontal_overflow:
                raise AssertionError("The main page should fit a 390px mobile viewport without horizontal overflow.")
            if page_errors:
                raise AssertionError("Browser JavaScript errors: " + "; ".join(page_errors))

            mobile.close()
            browser.close()

        print("PASS: browser selection, budget validation, Score, recommendations, and mobile layout")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
