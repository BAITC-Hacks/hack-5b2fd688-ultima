"""Run a real-browser smoke test against the local simulator."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

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
    previous_count = page.locator(".selection-slot.filled").count()
    if district_id:
        page.locator(f'[data-district-select="{measure_id}"]').select_option(district_id)
    page.locator(f'[data-add="{measure_id}"]').click()
    expect(page.locator(".selection-slot.filled")).to_have_count(previous_count + 1, timeout=5_000)


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    temporary_data = tempfile.TemporaryDirectory(prefix="akim-e2e-")
    environment["SIMULATOR_DB_PATH"] = str(Path(temporary_data.name) / "teams.sqlite3")
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
            expect(page.locator("#result-delta")).to_contain_text("3.98")
            expect(page.locator("#results-title")).to_be_focused(timeout=5_000)
            expect(page.locator("#explanation-consequences li")).to_have_count(2)
            alternatives = page.locator(".alternative-card")
            if alternatives.count() != 3:
                raise AssertionError("The reference scenario should show three validated alternatives.")
            if "+0.67 к сценарию" not in alternatives.first.inner_text():
                raise AssertionError("The best alternative should show a +0.67 displayed score change.")

            page.locator("#team-name").fill("Ultima")
            with page.expect_download() as presentation_download:
                page.locator("#export-presentation-button").click()
            deck = Path(presentation_download.value.path()).read_text(encoding="utf-8")
            if deck.count('<section class="slide"') != 3 or "56,54" not in deck or "Ultima" not in deck:
                raise AssertionError("The offline presentation should contain three scenario slides.")
            # Playwright's temporary download path has no .html extension; save it as
            # HTML before opening, otherwise Chromium prints its raw source as text.
            exported_path = Path(temporary_data.name) / "presentation.html"
            exported_path.write_text(deck, encoding="utf-8")
            print_page = browser.new_page()
            print_page.goto(exported_path.as_uri())
            pdf = print_page.pdf(format="A4", landscape=True, print_background=True)
            pdf_pages = PdfReader(BytesIO(pdf)).pages
            if len(pdf_pages) != 3:
                page_snippets = [
                    (pdf_page.extract_text() or "")[:60].replace("\n", " ")
                    for pdf_page in pdf_pages
                ]
                raise AssertionError(
                    f"Printing the scenario produced {len(pdf_pages)} pages, expected three: {page_snippets}"
                )
            print_page.close()

            page.locator("#save-team-button").click()
            expect(page.locator("#leaderboard-rows tr")).to_have_count(1)
            if len(page.locator("#team-code").input_value()) < 20:
                raise AssertionError("Team edit code should be issued for updating the result.")

            page.locator('[data-use-alternative="0"]').click()
            page.locator(".selection-slot.filled .slot-measure-name").filter(
                has_text="Линия ЛРТ / расширение"
            ).wait_for(timeout=5_000)
            calculate = page.locator("#calculate-button")
            expect(calculate).to_be_enabled(timeout=5_000)
            calculate.click()
            expect(page.locator("#result-score")).to_have_text("57.21", timeout=15_000)

            page.locator("#team-name").fill("Новый город")
            page.locator("#save-team-button").click()
            expect(page.locator("#leaderboard-rows tr")).to_have_count(2)
            first_rank = page.locator("#leaderboard-rows tr").first.inner_text()
            if "Новый город" not in first_rank:
                raise AssertionError("The stronger team plan should rank first.")

            visitor_context = browser.new_context(viewport={"width": 1100, "height": 900})
            visitor = visitor_context.new_page()
            visitor.on("pageerror", lambda error: page_errors.append(str(error)))
            visitor.goto(base_url, wait_until="networkidle")
            expect(visitor.locator("#leaderboard-rows tr")).to_have_count(2)
            visitor.locator("#leaderboard-rows tr").first.locator("[data-compare-team]").click()
            expect(visitor.locator("#team-comparison")).to_contain_text("Новый город")
            expect(visitor.locator(".comparison-district-table tbody tr")).to_have_count(5)
            visitor.locator("[data-load-team]").click()
            expect(visitor.locator(".selection-slot.filled")).to_have_count(5)
            visitor_context.close()

            critical_context = browser.new_context(viewport={"width": 1100, "height": 900})
            critical_page = critical_context.new_page()
            critical_page.on("pageerror", lambda error: page_errors.append(str(error)))
            critical_page.goto(base_url, wait_until="networkidle")
            critical_page.locator("#workspace").wait_for(state="visible")
            choose_measure(critical_page, "M1", "esil")
            choose_measure(critical_page, "M2")
            choose_measure(critical_page, "M4", "saryarka")
            choose_measure(critical_page, "M10", "almaty")
            choose_measure(critical_page, "M12")
            critical_page.locator("#calculate-button").click()
            expect(critical_page.locator("#result-critical")).to_have_text("2", timeout=15_000)
            expect(critical_page.locator("#critical-list li")).to_have_count(2)
            expect(critical_page.locator(".critical-indicator-row")).to_have_count(2)
            critical_context.close()

            budget_context = browser.new_context(viewport={"width": 1100, "height": 900})
            budget_page = budget_context.new_page()
            budget_page.on("pageerror", lambda error: page_errors.append(str(error)))
            budget_page.goto(base_url, wait_until="networkidle")
            budget_page.locator("#workspace").wait_for(state="visible")
            choose_measure(budget_page, "M3", "esil")
            choose_measure(budget_page, "M5", "saryarka")
            choose_measure(budget_page, "M7", "nura")
            choose_measure(budget_page, "M8", "nura")
            budget_page.locator('[data-district-select="M10"]').select_option("baikonur")
            budget_page.locator('[data-add="M10"]').click()
            expect(budget_page.locator("#toast")).to_contain_text("Бюджет превышен", timeout=5_000)
            expect(budget_page.locator(".selection-slot.filled")).to_have_count(4)
            expect(budget_page.locator("#budget-spent")).to_have_text("99")
            budget_context.close()

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.on("pageerror", lambda error: page_errors.append(str(error)))
            mobile.goto(base_url, wait_until="networkidle")
            mobile.locator("#workspace").wait_for(state="visible")
            choose_measure(mobile, "M7", "nura")
            choose_measure(mobile, "M8", "nura")
            choose_measure(mobile, "M10", "nura")
            choose_measure(mobile, "M12")
            choose_measure(mobile, "M5", "saryarka")
            mobile.locator("#calculate-button").click()
            expect(mobile.locator("#result-score")).to_have_text("56.54", timeout=15_000)
            has_horizontal_overflow = mobile.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth"
            )
            if has_horizontal_overflow:
                raise AssertionError("The result and leaderboard should fit a 390px mobile viewport without horizontal overflow.")
            if page_errors:
                raise AssertionError("Browser JavaScript errors: " + "; ".join(page_errors))

            mobile.close()
            browser.close()

        print("PASS: browser budget, Score, risks, team ranking, comparison, export, and mobile layout")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        temporary_data.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
