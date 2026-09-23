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

from map_checks import check_city_map, expect_invalid_candidate, pick_map_measure
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
            check_city_map(browser, base_url)
            main_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = main_context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(base_url, wait_until="networkidle")
            page.locator("#workspace").wait_for(state="visible")
            expect(page.locator("#baseline-scores .baseline-score-card")).to_have_count(5)
            page.locator(".baseline-details summary").click()
            nura_profile = page.locator(".baseline-profile").filter(has=page.locator("h3", has_text="Нура"))
            expect(nura_profile.locator(".baseline-indicators .is-critical")).to_have_count(2)
            expect(nura_profile.locator(".baseline-indicators")).to_contain_text("38")
            expect(nura_profile.locator(".baseline-indicators")).to_contain_text("35")
            for district_id in ("esil", "almaty", "saryarka", "baikonur", "nura"):
                card = page.locator(f'[data-baseline-district="{district_id}"]')
                card.click()
                expect(card).to_have_attribute("aria-pressed", "true")
                profile = page.locator(f'[data-district-profile="{district_id}"]')
                expect(profile).to_be_visible()
                expect(profile.locator(".baseline-indicators dd")).to_have_count(10)
                expect(page.locator(".baseline-profile:visible")).to_have_count(1)
            page.locator(".baseline-details summary").click()

            page.locator('[data-filter="social"]').click()
            expect(page.locator(".measure-card")).to_have_count(3)
            page.locator('[data-district-select="M7"]').select_option("nura")
            page.locator('[data-filter="all"]').click()
            expect(page.locator(".measure-card")).to_have_count(14)
            expect(page.locator('[data-district-select="M7"]')).to_have_value("nura")

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
            expect(page.locator('[data-nav="results-panel"]')).to_have_attribute("aria-current", "location")
            if not 1 <= page.locator("#explanation-consequences > li").count() <= 3:
                raise AssertionError("The explanation should include grounded consequences.")
            page.locator("#score-breakdown > summary").click()
            expect(page.locator("#score-components tr")).to_have_count(3)
            expect(page.locator('#score-components [data-component="critical"]')).to_contain_text("+2.00000")
            expect(page.locator("#score-components-total")).to_contain_text("56.54307")
            expect(page.locator("#score-components-total")).to_contain_text("+3.98539")
            evidence = page.locator("#explanation-summary-evidence .fact-evidence").first
            evidence.locator("summary").click()
            expect(evidence.locator("ul")).to_be_visible()
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

            # A full-length provider response used to spill the final slide onto a
            # fourth page. Check both pagination and actual slide overflow.
            long_deck = page.evaluate("""() => {
                const report = structuredClone(state.report);
                const prose = 'Развитие районной инфраструктуры улучшает доступность услуг, '
                    + 'однако требует сравнения эффектов для остальных районов города. ';
                report.explanation.summary = prose.repeat(4).slice(0, 400);
                for (const field of ['strengths', 'risks', 'recommendations', 'consequences']) {
                    report.explanation[field] = Array(3).fill(prose.repeat(4).slice(0, 360));
                }
                report.explanation.consequences[0] = 'Уникальное последствие сценария. ' + prose.repeat(2);
                return buildPresentationHtml(report, '<img src=x onerror="window.injected=true">');
            }""")
            print_page.set_content(long_deck)
            expect(print_page.locator(".consequences")).to_contain_text("Уникальное последствие сценария")
            expect(print_page.locator("img, script")).to_have_count(0)
            print_page.emulate_media(media="print")
            long_pdf = PdfReader(BytesIO(print_page.pdf(format="A4", landscape=True, print_background=True)))
            if len(long_pdf.pages) != 3:
                raise AssertionError("A long AI explanation must still print on three pages.")
            if print_page.evaluate("""() => [...document.querySelectorAll('.slide')]
                .some(slide => slide.scrollHeight > slide.clientHeight + 1)"""):
                raise AssertionError("Presentation text must fit its slide without clipping.")
            print_page.close()

            page.locator("#save-team-button").click()
            expect(page.locator("#leaderboard-rows tr")).to_have_count(1)
            if len(page.locator("#team-code").input_value()) < 20:
                raise AssertionError("Team edit code should be issued for updating the result.")

            page.locator("#save-comparison-button").click()
            expect(page.locator("#personal-score-delta")).to_have_text("0.00 Score")

            page.locator('[data-use-alternative="0"]').click()
            page.locator(".selection-slot.filled .slot-measure-name").filter(
                has_text="Линия ЛРТ / расширение"
            ).wait_for(timeout=5_000)
            calculate = page.locator("#calculate-button")
            expect(calculate).to_be_enabled(timeout=5_000)
            calculate.click()
            expect(page.locator("#result-score")).to_have_text("57.21", timeout=15_000)
            expect(page.locator("#personal-score-delta")).to_have_text("+0.67 Score")
            expect(page.locator(".personal-plan-card").first).to_contain_text("56.54")
            expect(page.locator(".personal-plan-card").nth(1)).to_contain_text("57.21")
            expect(page.locator(".personal-gains")).to_contain_text("Нура")
            expect(page.locator(".personal-losses")).to_contain_text("Сарыарка")
            expect(page.locator(".personal-losses")).to_contain_text("−8.75")
            expect(page.locator(".personal-district-table tbody tr")).to_have_count(5)

            # Restoring a snapshot must recalculate its choices, ignoring any
            # fabricated numeric report in browser storage. No paid analysis.
            page.evaluate("""() => {
                const saved = JSON.parse(localStorage.getItem(COMPARISON_KEY));
                saved.report = {score: 99.99};
                localStorage.setItem(COMPARISON_KEY, JSON.stringify(saved));
            }""")
            restored = page.context.new_page()
            restored.on("pageerror", lambda error: page_errors.append(str(error)))
            restored.goto(base_url, wait_until="networkidle")
            expect(restored.locator(".personal-plan-card")).to_have_count(1)
            expect(restored.locator(".personal-plan-card")).to_contain_text("56.54")
            expect(restored.locator("#results-panel")).to_be_hidden()
            restored.locator("[data-load-saved-plan]").click()
            expect(restored.locator("#budget-spent")).to_have_text("95")
            expect(restored.locator('[data-remove="M5"]')).to_have_count(1)
            restored.locator("#clear-comparison-button").click()
            expect(restored.locator("#personal-comparison")).to_be_hidden()
            if restored.evaluate("localStorage.getItem(COMPARISON_KEY) !== null"):
                raise AssertionError("Clearing plan A must remove its stored choices.")
            restored.evaluate("""() => localStorage.setItem(COMPARISON_KEY, JSON.stringify({
                model_version: 'different-model', selections: state.selections
            }))""")
            restored.reload(wait_until="networkidle")
            expect(restored.locator("#personal-comparison-content")).to_contain_text("другой версии модели")
            expect(restored.locator(".personal-plan-card")).to_have_count(0)
            restored.locator("#clear-comparison-button").click()
            restored.close()

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
            expect(budget_page.locator('[data-map-project="M10"]')).to_have_count(0)
            budget_page.locator("#map-district").select_option("baikonur")
            pick_map_measure(budget_page, "M10")
            expect_invalid_candidate(budget_page, "Бюджет превышен")
            expect(budget_page.locator("#map-plan-budget")).to_have_text("99 / 100")
            expect(budget_page.locator("[data-map-project]")).to_have_count(4)
            budget_context.close()

            stale_context = browser.new_context(viewport={"width": 1100, "height": 900})
            stale_page = stale_context.new_page()
            stale_page.on("pageerror", lambda error: page_errors.append(str(error)))
            stale_page.add_init_script("""
                (() => {
                  const fetchOriginal = window.fetch.bind(window);
                  window.fetch = (input, options) => {
                    if (input !== '/api/analyze') return fetchOriginal(input, options);
                    return fetchOriginal(input, options).then((response) => new Promise((resolve) => {
                      document.documentElement.dataset.pendingAnalyze = 'true';
                      window.releaseAnalyze = () => resolve(response);
                    }));
                  };
                })();
            """)
            stale_page.goto(base_url, wait_until="networkidle")
            for measure_id, district_id in [
                ("M7", "nura"), ("M8", "nura"), ("M10", "nura"),
                ("M12", None), ("M5", "saryarka"),
            ]:
                choose_measure(stale_page, measure_id, district_id)
            stale_page.locator("#calculate-button").click()
            stale_page.locator('html[data-pending-analyze="true"]').wait_for()
            stale_page.locator('[data-remove="M7"]').click()
            expect(stale_page.locator(".selection-slot.filled")).to_have_count(4)
            stale_page.evaluate("window.releaseAnalyze()")
            stale_page.wait_for_function("state.loading === false")
            expect(stale_page.locator("#results-panel")).to_be_hidden()
            if stale_page.evaluate("state.report !== null"):
                raise AssertionError("A delayed report must not replace a changed plan.")

            choose_measure(stale_page, "M7", "nura")
            stale_page.evaluate("delete document.documentElement.dataset.pendingAnalyze")
            stale_page.locator("#calculate-button").click()
            stale_page.locator('html[data-pending-analyze="true"]').wait_for()
            stale_page.locator("#reset-button").click()
            stale_page.evaluate("window.releaseAnalyze()")
            stale_page.wait_for_function("state.loading === false")
            expect(stale_page.locator(".selection-slot.filled")).to_have_count(0)
            expect(stale_page.locator("#results-panel")).to_be_hidden()
            stale_page.locator("#load-example-button").click()
            expect(stale_page.locator(".selection-slot.filled")).to_have_count(5)
            stale_page.evaluate("delete document.documentElement.dataset.pendingAnalyze")
            stale_page.locator("#calculate-button").click()
            stale_page.locator('html[data-pending-analyze="true"]').wait_for()
            stale_page.locator("#load-example-button").click()
            stale_page.evaluate("window.releaseAnalyze()")
            stale_page.wait_for_function("state.loading === false")
            expect(stale_page.locator("#results-panel")).to_be_hidden()
            stale_context.close()

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.on("pageerror", lambda error: page_errors.append(str(error)))
            mobile.goto(base_url, wait_until="networkidle")
            mobile.locator("#workspace").wait_for(state="visible")
            mobile.locator('[data-baseline-district="nura"]').click()
            expect(mobile.locator('[data-district-profile="nura"]')).to_be_visible()
            mobile.locator("#map-district").select_option("esil")
            pick_map_measure(mobile, "M1")
            expect(mobile.locator("#map-add-button")).to_be_enabled()
            mobile.locator("#map-add-button").click()
            expect(mobile.locator('[data-map-project="M1"]')).to_have_attribute("data-project-district", "esil")
            expect(mobile.locator(".selection-slot.filled")).to_have_count(1)
            expect(mobile.locator('[data-map-project="M1"]')).to_be_focused()
            mobile.locator("#map-to-builder").click()
            expect(mobile.locator('[data-map-pick="M1"]')).to_be_focused()
            expect(mobile.locator("#map-remove-button")).to_contain_text("Есиль")
            expect(mobile.locator("#map-focus-button")).to_have_attribute("aria-pressed", "true")
            mobile.locator("#map-reset-view").click()
            expect(mobile.locator("#map-focus-button")).to_have_attribute("aria-pressed", "false")
            mobile.locator("#map-focus-button").click()
            expect(mobile.locator("#map-focus-button")).to_have_attribute("aria-pressed", "true")
            mobile.locator("#map-reset-view").click()
            analyses = []
            mobile.on("request", lambda request: analyses.append(request.url) if request.url.endswith("/api/analyze") else None)
            mobile.locator("#load-example-button").click()
            expect(mobile.locator(".selection-slot.filled")).to_have_count(5)
            expect(mobile.locator('[data-remove="M1"]')).to_have_count(0)
            expect(mobile.locator("#example-reasons li")).to_have_count(5)
            expect(mobile.locator("#results-panel")).to_be_hidden()
            if analyses:
                raise AssertionError("Loading the example must not automatically invoke AI.")
            expect(mobile.locator("#mobile-dock-summary")).to_have_text("5 из 5 · 95 / 100 ед.")
            expect(mobile.locator("#mobile-calculate-button")).to_be_enabled()
            mobile.locator("#mobile-calculate-button").click()
            expect(mobile.locator("#result-score")).to_have_text("56.54", timeout=15_000)
            expect(mobile.locator("#mobile-calculate-button")).to_contain_text("К результату")
            mobile.locator("#score-breakdown > summary").click()
            mobile.locator("#save-comparison-button").click()
            mobile.locator('[data-use-alternative="0"]').click()
            expect(mobile.locator("#personal-score-delta")).to_have_count(0)
            mobile.locator("#mobile-calculate-button").click()
            expect(mobile.locator("#result-score")).to_have_text("57.21", timeout=15_000)
            expect(mobile.locator("#personal-score-delta")).to_have_text("+0.67 Score")
            mobile.locator(".mobile-dock-status").click()
            expect(mobile.locator(".selection-slot.filled").first).to_be_visible()
            mobile.locator("#leaderboard-rows tr").first.locator("[data-compare-team]").click()
            for width in (320, 390, 520, 768, 800, 801, 1100, 1440):
                mobile.set_viewport_size({"width": width, "height": 900})
                if mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                    raise AssertionError(f"The simulator should fit a {width}px viewport without horizontal overflow.")
            mobile.set_viewport_size({"width": 390, "height": 844})
            mobile.locator(".mobile-dock-status").click()
            mobile.locator('[data-remove="M7"]').click()
            expect(mobile.locator(".selection-slot.filled")).to_have_count(4)
            expect(mobile.locator("#mobile-calculate-button")).to_be_disabled()
            expect(mobile.locator("#results-panel")).to_be_hidden()
            if page_errors:
                raise AssertionError("Browser JavaScript errors: " + "; ".join(page_errors))

            mobile.close()
            browser.close()

        print("PASS: interactive map, example, Score breakdown, grounded analysis, A/B comparison, teams, export, stale responses, and mobile layout")
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
