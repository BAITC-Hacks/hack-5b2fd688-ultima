"""Browser checks for the map's shared plan and server validation boundary."""

import re

from playwright.sync_api import expect


def pick_map_measure(page, measure_id: str) -> None:
    """Choose through the visible workbench, keeping the all-measures drawer closed."""
    direction = page.evaluate(
        "id => state.config.measures.find(measure => measure.id === id).direction", measure_id
    )
    tab = page.locator(f'[data-map-direction="{direction}"]')
    if tab.get_attribute("aria-pressed") != "true":
        tab.click()
    button = page.locator(f'[data-map-pick="{measure_id}"]')
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#map-measure")).to_have_value(measure_id)


def add_map_measure(page, measure_id: str, district_id: str | None = None) -> None:
    if district_id:
        page.locator("#map-district").select_option(district_id)
    pick_map_measure(page, measure_id)
    expect(page.locator("#map-add-button")).to_be_enabled()
    page.locator("#map-add-button").click()
    expect(page.locator(f'[data-map-project="{measure_id}"]')).to_have_count(1)
    expect(page.locator(f'[data-remove="{measure_id}"]')).to_have_count(1)


def plan_snapshot(page) -> dict:
    return page.evaluate("""() => ({
        selections: state.selections, version: state.selectionsVersion,
        validation: state.validation, report: state.report,
        stored: localStorage.getItem(STORAGE_KEY),
        budget: document.querySelector('#budget-spent').textContent,
        mapBudget: document.querySelector('#map-plan-budget').textContent,
        result: document.querySelector('#results-panel').innerHTML
    })""")


def expect_invalid_candidate(page, reason: str) -> None:
    expect(page.locator("#map-candidate-status")).to_have_attribute("data-status", "invalid")
    expect(page.locator("#map-candidate-status")).to_contain_text(reason)
    expect(page.locator("#map-add-button")).to_be_disabled()
    expect(page.locator("[data-map-preview]")).to_have_count(0)


def check_preview_boundary(page) -> None:
    before = plan_snapshot(page)
    analyses = []
    page.on("request", lambda request: analyses.append(request.url) if request.url.endswith("/api/analyze") else None)
    page.locator("#map-district").select_option("esil")
    pick_map_measure(page, "M7")
    expect(page.locator("#map-add-button")).to_be_enabled()
    expect(page.locator('[data-map-preview="M7"] [data-preview-district="esil"]')).to_have_count(1)
    expect(page.locator("[data-map-project]")).to_have_count(0)
    expect(page.locator(".selection-slot.filled")).to_have_count(0)
    page.locator("#map-preview-toggle").uncheck()
    expect(page.locator("[data-map-preview]")).to_have_count(0)
    page.locator("#map-preview-toggle").check()
    expect(page.locator('[data-map-preview="M7"]')).to_have_count(1)
    pick_map_measure(page, "M6")
    expect(page.locator('[data-map-preview="M6"] [data-preview-district]')).to_have_count(5)
    assert plan_snapshot(page) == before, "Previewing district/city projects must not mutate the plan or report."

    # A failed validator must leave Add locked, with an explicit working retry.
    def fail_candidate(route):
        choices = route.request.post_data_json["selections"]
        if choices and choices[-1]["measure_id"] == "M4":
            route.abort("failed")
        else:
            route.continue_()

    page.route("**/api/validate", fail_candidate)
    pick_map_measure(page, "M4")
    expect(page.locator("#map-candidate-status")).to_have_attribute("data-status", "error")
    expect(page.locator("#map-candidate-status")).to_contain_text("Повторите проверку")
    expect(page.locator("#map-add-button")).to_be_disabled()
    expect(page.locator("[data-map-preview]")).to_have_count(0)
    page.unroute("**/api/validate", fail_candidate)
    page.locator("#map-retry-check").click()
    expect(page.locator("#map-add-button")).to_be_enabled()
    expect(page.locator("#map-retry-check")).to_be_hidden()
    expect(page.locator('[data-map-preview="M4"]')).to_have_count(1)
    assert plan_snapshot(page) == before, "Retrying a preview must not commit it."
    assert not analyses, "Previewing and retrying must never invoke AI analysis."


class ValidationResponses:
    """Deliver real JSON out of order, even after its fetch has been aborted."""

    def __init__(self, page):
        self.page = page
        page.evaluate("""() => {
        window.mapResponseHolds = {};
        window.mapOriginalFetch = window.fetch;
        window.fetch = async (url, options) => {
            const choices = url === '/api/validate' ? JSON.parse(options.body).selections : [];
            const candidate = choices.at(-1);
            const hold = choices.length === state.selections.length + 1
                && Object.values(window.mapResponseHolds).find(item => !item.used
                    && item.adding === state.adding
                    && item.version === state.selectionsVersion
                    && item.measure === candidate?.measure_id && item.district === candidate?.district_id);
            if (hold) hold.used = true;
            const response = await window.mapOriginalFetch(url, options);
            if (!hold) return response;
            const json = response.json.bind(response);
            response.json = async () => {
                const data = await json();
                hold.pending = true;
                await new Promise(resolve => { hold.release = resolve; });
                return data;
            };
            return response;
        };
        }""")

    def hold(self, name, measure, district, *, adding=False):
        self.page.evaluate("""({name, measure, district, adding}) => {
            window.mapResponseHolds[name] = {measure, district, adding, version: state.selectionsVersion};
        }""", {"name": name, "measure": measure, "district": district, "adding": adding})

    def pending(self, name):
        self.page.wait_for_function("name => window.mapResponseHolds[name].pending === true", arg=name)

    def release(self, name):
        # The body is already buffered. Drain its promise chain and a paint before
        # asserting that a late response did not overwrite the current candidate.
        self.page.evaluate("""async name => {
            window.mapResponseHolds[name].release();
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""", name)

    def close(self):
        self.page.evaluate("window.fetch = window.mapOriginalFetch")


def check_preview_races(page) -> None:
    responses = ValidationResponses(page)
    hold, release = responses.hold, responses.release

    def pending(name):
        responses.pending(name)
        expect(page.locator("#map-add-button")).to_be_disabled()
        expect(page.locator("[data-map-preview]")).to_have_count(0)

    before = plan_snapshot(page)
    page.locator("#map-district").select_option("esil")
    hold("oldDistrict", "M7", "esil")
    pick_map_measure(page, "M7")
    pending("oldDistrict")
    hold("newDistrict", "M7", "nura")
    page.locator("#map-district").select_option("nura")
    pending("newDistrict")
    release("oldDistrict")
    expect(page.locator("#map-candidate-status")).to_have_attribute("data-status", "loading")
    expect(page.locator("#map-add-button")).to_be_disabled()
    expect(page.locator("[data-map-preview]")).to_have_count(0)
    release("newDistrict")
    expect(page.locator("#map-add-button")).to_be_enabled()
    expect(page.locator('[data-map-preview="M7"] [data-preview-district="nura"]')).to_have_count(1)
    expect(page.locator('[data-map-preview] [data-preview-district="esil"]')).to_have_count(0)
    assert plan_snapshot(page) == before, "A district preview race must not change the shared plan."

    add_map_measure(page, "M1", "esil")
    before = plan_snapshot(page)
    hold("oldMeasure", "M4", "esil")
    pick_map_measure(page, "M4")
    pending("oldMeasure")
    pick_map_measure(page, "M3")
    expect_invalid_candidate(page, "автобусные полосы")
    release("oldMeasure")
    expect_invalid_candidate(page, "автобусные полосы")
    expect(page.locator("#map-measure")).to_have_value("M3")
    assert plan_snapshot(page) == before, "A late valid preview must not enable an incompatible measure."

    # Same candidate, different plan version: an old rejection must not replace
    # the valid response obtained after resetting the plan.
    pick_map_measure(page, "M4")
    expect(page.locator("#map-add-button")).to_be_enabled()
    hold("oldVersion", "M3", "esil")
    pick_map_measure(page, "M3")
    pending("oldVersion")
    page.locator("#reset-button").click()
    expect(page.locator("#map-add-button")).to_be_enabled()
    release("oldVersion")
    expect(page.locator("#map-add-button")).to_be_enabled()
    expect(page.locator('[data-map-preview="M3"] [data-preview-district="esil"]')).to_have_count(1)
    expect(page.locator("[data-map-project]")).to_have_count(0)
    expect(page.locator(".selection-slot.filled")).to_have_count(0)
    responses.close()


def check_pending_adds(page) -> None:
    page.locator("#reset-button").click()
    responses = ValidationResponses(page)

    def start(name, measure):
        pick_map_measure(page, measure)
        expect(page.locator("#map-add-button")).to_be_enabled()
        district = page.locator("#map-district").input_value()
        responses.hold(name, measure, district, adding=True)
        page.locator("#map-add-button").click()
        responses.pending(name)

    start("oldAdd", "M3")
    page.locator("#reset-button").click()
    assert page.evaluate("state.adding === false"), "Reset must unlock Add before the old response arrives."
    start("newAdd", "M4")
    responses.release("oldAdd")
    assert page.evaluate("state.adding === true"), "The cancelled request's finally must not unlock a newer add."
    expect(page.locator("#map-add-button")).to_be_disabled()
    expect(page.locator("[data-map-project]")).to_have_count(0)
    responses.release("newAdd")
    expect(page.locator('[data-map-project="M4"]')).to_have_count(1)
    expect(page.locator(".selection-slot.filled")).to_have_count(1)

    start("removedPlan", "M8")
    page.locator('[data-remove="M4"]').click()
    assert page.evaluate("state.adding === false"), "Removing a project must cancel the pending add."
    responses.release("removedPlan")
    expect(page.locator("[data-map-project]")).to_have_count(0)
    expect(page.locator(".selection-slot.filled")).to_have_count(0)

    start("replacedPlan", "M3")
    page.locator("#load-example-button").click()
    expect(page.locator(".selection-slot.filled")).to_have_count(5)
    assert page.evaluate("state.adding === false"), "Loading a plan must cancel the pending add."
    responses.release("replacedPlan")
    expect(page.locator('[data-map-project="M3"]')).to_have_count(0)
    expect(page.locator("#map-plan-budget")).to_have_text("95 / 100")
    responses.close()
    page.locator("#reset-button").click()


def check_candidate_guidance(page) -> None:
    add_map_measure(page, "M3", "nura")
    responses = ValidationResponses(page)
    responses.hold("incompatibleCatalog", "M1", "esil", adding=True)
    page.locator('[data-district-select="M1"]').select_option("esil")
    page.locator('[data-add="M1"]').click()
    responses.pending("incompatibleCatalog")
    pick_map_measure(page, "M4")
    responses.release("incompatibleCatalog")
    expect(page.locator("#map-add-button")).to_be_enabled()
    expect(page.locator("#map-action-status")).to_be_empty()
    expect(page.locator('[data-map-preview="M4"]')).to_have_count(1)
    responses.close()

    pick_map_measure(page, "M3")
    page.locator("#map-district").select_option("esil")
    expect(page.locator("#map-measure-preview .map-target-place")).to_contain_text("Нура")
    expect(page.locator("#map-remove-button")).to_contain_text("Нура")
    page.locator("#map-show-project").click()
    expect(page.locator("#map-district")).to_have_value("nura")
    expect(page.locator('[data-map-project="M3"]')).to_be_focused()
    page.locator("#map-reset-view").click()

    add_map_measure(page, "M5", "esil")
    add_map_measure(page, "M7", "nura")
    before = plan_snapshot(page)
    pick_map_measure(page, "M14")
    expect(page.locator("#map-add-button")).to_be_enabled()
    expect(page.locator("#map-completion-hint")).to_be_visible()
    expect(page.locator("#map-completion-hint")).to_contain_text("останется 5 ед.")
    expect(page.locator("#map-completion-hint")).to_contain_text("минимум 10 ед.")
    expect(page.locator("#map-plan-budget")).to_have_text("79 / 100")
    assert plan_snapshot(page) == before, "The budget completion hint is advisory, not a committed project."
    page.locator('[data-remove="M5"]').click()
    expect(page.locator("#map-add-button")).to_be_enabled()
    expect(page.locator("#map-completion-hint")).to_be_hidden()
    page.locator("#reset-button").click()


def check_map_viewport(page) -> None:
    svg = page.locator("#astana-map > svg")
    page.locator("#map-reset-view").click()
    original_view = svg.get_attribute("viewBox")
    expect(page.locator("#map-zoom-label")).to_have_text("100%")
    expect(page.locator("#map-zoom-out")).to_be_disabled()
    page.locator("#map-zoom-in").click()
    expect(page.locator("#map-zoom-label")).to_have_text("125%")
    expect(svg).not_to_have_attribute("viewBox", original_view)
    page.locator("#map-zoom-out").click()
    expect(svg).to_have_attribute("viewBox", original_view)
    for _ in range(8):
        if page.locator("#map-zoom-in").is_enabled():
            page.locator("#map-zoom-in").click()
    expect(page.locator("#map-zoom-label")).to_have_text("300%")
    expect(page.locator("#map-zoom-in")).to_be_disabled()
    assert abs(float(svg.get_attribute("viewBox").split()[2]) * 3 - float(original_view.split()[2])) < 0.01
    for _ in range(8):
        if page.locator("#map-zoom-out").is_enabled():
            page.locator("#map-zoom-out").click()
    expect(page.locator("#map-zoom-label")).to_have_text("100%")
    expect(page.locator("#map-zoom-out")).to_be_disabled()
    page.locator("#map-zoom-in").click()
    svg.scroll_into_view_if_needed()
    district = page.locator("#map-district").input_value()
    measure = page.locator("#map-measure").input_value()
    # Hit-test a different district so an accidental click would be observable.
    point = svg.evaluate("""(svg, active) => {
        const rect = svg.getBoundingClientRect();
        for (let y = Math.max(0, rect.top) + 25; y < Math.min(innerHeight, rect.bottom) - 50; y += 20) {
            for (let x = rect.left + 25; x < rect.right - 80; x += 20) {
                const hit = document.elementFromPoint(x, y)?.closest('[data-map-district]');
                if (hit && hit.dataset.mapDistrict !== active) return {x, y};
            }
        }
        return null;
    }""", district)
    assert point, "A different district must be available for the drag/click regression."
    before_drag = svg.get_attribute("viewBox")
    page.mouse.move(point["x"], point["y"])
    page.mouse.down()
    page.mouse.move(point["x"] + 55, point["y"] + 25, steps=8)
    page.mouse.up()
    expect(svg).not_to_have_attribute("viewBox", before_drag)
    expect(page.locator("#map-district")).to_have_value(district)
    expect(page.locator("#map-measure")).to_have_value(measure)
    page.locator("#map-reset-view").click()
    expect(svg).to_have_attribute("viewBox", original_view)


def check_map_layout(page) -> None:
    section = page.locator("#city-map-section")
    expand = page.locator("#map-expand-button")
    for width in (320, 390, 800, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        for expanded in (False, True):
            if expanded:
                expand.click()
                expect(page.locator("body")).to_have_class(re.compile(r"\bmap-expanded\b"))
                expect(section).to_have_attribute("role", "dialog")
                expect(section).to_have_attribute("aria-modal", "true")
                assert page.evaluate("""() => ['#workspace', '#top', '#comparison-board'].every(
                    selector => document.querySelector(selector).closest('[inert]'))"""), "Expanded map must make the background inert."
                page.locator("#reset-button").evaluate("element => element.focus()")
                assert section.evaluate("element => element.contains(document.activeElement)"), "Background controls must not steal modal focus."
                page.evaluate("""() => {
                    const section = document.querySelector('#city-map-section');
                    const controls = [...section.querySelectorAll('button, a[href], input, select, summary, [tabindex]')]
                        .filter(element => element.tabIndex >= 0 && !element.disabled && element.checkVisibility());
                    window.mapFocusEdges = [controls[0], controls.at(-1)];
                    window.mapFocusEdges[1].focus();
                }""")
                page.keyboard.press("Tab")
                assert page.evaluate("document.activeElement === window.mapFocusEdges[0]"), "Tab must wrap inside the expanded map."
                page.keyboard.press("Shift+Tab")
                assert page.evaluate("document.activeElement === window.mapFocusEdges[1]"), "Shift+Tab must wrap inside the expanded map."
            overflow = page.evaluate("""() => {
                const elements = [document.documentElement, ...document.querySelectorAll(
                    '#city-map-section, .map-workspace, #map-builder, .map-toolbar, .map-navigation')];
                return elements.filter(element => element.scrollWidth > element.clientWidth + 1)
                    .map(element => element.id || element.className || element.tagName);
            }""")
            assert not overflow, f"Map overflow at {width}px, expanded={expanded}: {overflow}"
            if width <= 800:
                assert page.evaluate("""() => document.querySelector('#map-builder').getBoundingClientRect().bottom
                    <= document.querySelector('#map-projects-drawer').getBoundingClientRect().top + 1"""), "The mobile builder must precede the project list."
            if expanded:
                page.keyboard.press("Escape")
                expect(page.locator("body")).not_to_have_class(re.compile(r"\bmap-expanded\b"))
                expect(expand).to_have_attribute("aria-expanded", "false")
                expect(expand).to_be_focused()
                assert section.get_attribute("role") is None
                assert page.locator("#workspace").evaluate("element => !element.closest('[inert]')")
    page.set_viewport_size({"width": 1440, "height": 1000})


def check_map_motion(page) -> None:
    project = page.locator('[data-map-project="M3"]')
    project.scroll_into_view_if_needed()
    # Discover the moving SVG element via its animation, without tying the test
    # to a vehicle class or a particular CSS keyframe name.
    page.wait_for_function("""() => document.querySelector('[data-map-project="M3"]')
        .getAnimations({subtree: true}).some(animation => animation.effect.getTiming().iterations === Infinity)""")
    assert project.evaluate("""element => {
        for (const animation of element.getAnimations({subtree: true})) {
            const timing = animation.effect.getTiming();
            if (timing.iterations !== Infinity || !Number.isFinite(timing.duration)) continue;
            const target = animation.effect.target;
            const originalTime = animation.currentTime;
            animation.currentTime = timing.duration * .15;
            const start = target.getBoundingClientRect();
            animation.currentTime = timing.duration * .65;
            const end = target.getBoundingClientRect();
            animation.currentTime = originalTime;
            if (Math.hypot(start.x - end.x, start.y - end.y) > 5) {
                window.mapVehicle = target;
                return true;
            }
        }
        return false;
    }"""), "The LRT vehicle must actually travel across the map."
    page.locator("#map-motion-button").click()
    expect(page.locator("#map-motion-button")).to_have_attribute("aria-pressed", "true")
    page.wait_for_function("window.mapVehicle.getAnimations().every(animation => animation.playState !== 'running')")
    page.locator("#map-motion-button").click()
    page.wait_for_function("window.mapVehicle.getAnimations().some(animation => animation.playState === 'running')")
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_function("window.mapVehicle.getAnimations().every(animation => animation.playState !== 'running')")
    expect(project).to_be_visible()
    assert page.evaluate("window.mapVehicle.getBoundingClientRect().width > 0"), "Reduced motion must keep the vehicle visible."
    page.emulate_media(reduced_motion="no-preference")
    page.wait_for_function("window.mapVehicle.getAnimations().some(animation => animation.playState === 'running')")


def check_map_views(page) -> None:
    before = plan_snapshot(page)
    analyses = []
    page.on("request", lambda request: analyses.append(request.url) if request.url.endswith("/api/analyze") else None)
    page.evaluate("""() => {
        window.mapPlanNodes = [...document.querySelectorAll('[data-map-project]')];
        window.mapReport = state.report;
    }""")
    svg = page.locator("#astana-map > svg")
    expect(svg).to_have_attribute("data-score-source", "report")
    page.locator('[data-map-view="baseline"]').click()
    expect(svg).to_have_attribute("data-score-source", "baseline")
    expect(page.locator("#map-district-score")).to_have_text("49.18")
    expect(page.locator("[data-map-project]")).to_have_count(5)
    expect(page.locator("[data-map-project]:visible")).to_have_count(0)
    expect(page.locator("#result-score")).to_have_text("56.54")
    for view in ("baseline", "plan"):
        page.locator(f'[data-map-view="{view}"]').click()
        for layer in ("scores", "projects"):
            page.locator(f'[data-map-layer="{layer}"]').click()
            expect(page.locator(f'[data-map-layer="{layer}"]')).to_have_attribute("aria-pressed", "true")
            if layer == "scores":
                expect(page.locator("#map-score-legend")).to_be_visible()
                expect(page.locator("#map-score-legend")).to_contain_text("Балл района")
                expect(page.locator("#map-project-legend")).to_be_hidden()
            else:
                expect(page.locator("#map-score-legend")).to_be_hidden()
                expect(page.locator("#map-project-legend")).to_be_visible()
            expect(svg).to_have_attribute("data-score-source", "baseline" if view == "baseline" else "report")
    expect(page.locator("[data-map-project]:visible")).to_have_count(5)
    expect(page.locator("#map-district-score")).to_have_text("52.96")
    pick_map_measure(page, "M3")
    page.locator("#map-preview-toggle").uncheck()
    page.locator("#map-preview-toggle").check()
    expect(page.locator("#map-add-button")).to_be_disabled()
    expect(page.locator("[data-map-preview]")).to_have_count(0)
    assert page.evaluate("""() => window.mapReport === state.report && window.mapPlanNodes.every(
        node => node === document.querySelector(`[data-map-project="${node.dataset.mapProject}"]`))"""), "View/layer switches must preserve the report and every project node."
    assert plan_snapshot(page) == before, "Map display controls must not alter the plan or calculated report."
    assert not analyses, "Changing map display must not recalculate or invoke AI."


def check_map_clearance(browser, base_url: str) -> None:
    """Exercise dense, valid plans against the actual painted SVG geometry."""
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.goto(base_url, wait_until="networkidle")
    page.evaluate("""async () => {
        await document.fonts.ready;
        const host = document.createElement('div');
        host.id = 'map-layout-fixture';
        host.style.cssText = 'position:fixed;inset:0 auto auto 0;width:min(1000px,100vw);z-index:200';
        document.body.append(host);
        window.layoutMap = createAstanaMap(host, state.config);
    }""")
    plans = (
        ["M3", "M7", "M8", "M10", "M11"],
        ["M1", "M4", "M8", "M10", "M13"],
        ["M2", "M6", "M12", "M14", "M9"],
    )
    config = page.request.get(f"{base_url}/api/config").json()
    city_measures = {item["id"] for item in config["measures"] if item["type"] == "city"}
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 1000})
        for district in config["districts"]:
            for measures in plans:
                selections = [{"measure_id": item, "district_id": None if item in city_measures else district["id"]} for item in measures]
                response = page.request.post(f"{base_url}/api/simulate", data={"selections": selections})
                assert response.ok, response.text()
                page.evaluate("""({selections, report, district}) => {
                    layoutMap.update({selections: [], preview: null});
                    layoutMap.update({selections, report, activeDistrict: district, motionPaused: true});
                }""", {"selections": selections, "report": response.json(), "district": district["id"]})
                failures = page.evaluate("""() => {
                    const root = document.querySelector('#map-layout-fixture');
                    const svg = root.querySelector('svg'), scale = svg.getScreenCTM().a;
                    const name = el => `${el.closest('[data-map-project]')?.dataset.mapProject || el.dataset.mapLandmark || 'label'}:${el.closest('[data-object-district]')?.dataset.objectDistrict || el.closest('[data-map-district]')?.dataset.mapDistrict || ''}`;
                    const items = [...root.querySelectorAll('.am-project-site, .am-district-label, [data-map-landmark]')].map(el => ({el, name: name(el), box: el.getBoundingClientRect()}));
                    const overlaps = (a,b,gap=0) => a.left-gap<b.right && a.right+gap>b.left && a.top-gap<b.bottom && a.bottom+gap>b.top;
                    const failures = [];
                    items.forEach((a,i) => items.slice(i+1).forEach(b => {
                        if (overlaps(a.box,b.box,scale*2)) failures.push(`${a.name} overlaps ${b.name}`);
                    }));
                    for (const route of root.querySelectorAll('.am-route')) {
                        const path = route.querySelector('.am-route-road');
                        const district = root.querySelector(`[data-map-district="${route.dataset.routeDistrict}"] .am-district-area`);
                        const matrix = path.getScreenCTM(), length = path.getTotalLength();
                        for (let i=0;i<=200;i++) {
                            const point = path.getPointAtLength(length*i/200), p = point.matrixTransform(matrix);
                            if (!district.isPointInFill(point)) failures.push('Route leaves district');
                            for (const item of items) {
                                const b = item.box, pad = scale*8;
                                if (p.x>b.left-pad && p.x<b.right+pad && p.y>b.top-pad && p.y<b.bottom+pad) failures.push(`Route crosses ${item.name}`);
                            }
                        }
                        const vehicle = route.querySelector('[data-route-vehicle]'), animation = vehicle.getAnimations()[0];
                        for (let i=0;i<=160;i++) {
                            animation.currentTime = animation.effect.getTiming().duration*i/161;
                            for (const item of items) if (overlaps(vehicle.getBoundingClientRect(),item.box,scale)) failures.push(`Vehicle crosses ${item.name}`);
                        }
                    }
                    // A shoreline drawn later used to hide project names even when sites were disjoint.
                    const terrain = root.querySelector('.am-terrain'), projects = root.querySelector('.am-projects');
                    if (!(terrain.compareDocumentPosition(projects) & Node.DOCUMENT_POSITION_FOLLOWING)) failures.push('Terrain obscures projects');
                    const river = root.querySelector('.am-river'), matrix = river.getScreenCTM(), length = river.getTotalLength();
                    for (let i=0;i<=300;i++) {
                        const p = river.getPointAtLength(length*i/300).matrixTransform(matrix);
                        for (const item of items.filter(item => item.el.matches('.am-project-site'))) {
                            const b = item.box, pad = scale*13;
                            if (p.x>b.left-pad && p.x<b.right+pad && p.y>b.top-pad && p.y<b.bottom+pad) failures.push(`River crosses ${item.name}`);
                        }
                    }
                    return [...new Set(failures)];
                }""")
                assert not failures, f"{width}px / {district['id']} / {measures}: {failures}"
    context.close()


def check_city_map(browser, base_url: str) -> None:
    check_map_clearance(browser, base_url)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base_url, wait_until="networkidle")
    expect(page.locator("#city-map-section")).to_be_visible()
    expect(page.locator("[data-map-district]")).to_have_count(5)
    expect(page.locator("#map-measure option")).to_have_count(14)
    expect(page.locator("[data-map-direction]")).to_have_count(5)
    expect(page.locator("#map-measure")).to_be_hidden()
    expect(page.locator("[data-map-project]")).to_have_count(0)
    check_preview_boundary(page)
    check_preview_races(page)

    for district in ("esil", "almaty", "saryarka", "baikonur", "nura"):
        area = page.locator(f'[data-map-district="{district}"]')
        area.focus()
        area.press("Enter")
        expect(area).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#map-district")).to_have_value(district)
        expect(page.locator(f'[data-baseline-district="{district}"]')).to_have_attribute("aria-pressed", "true")

    svg = page.locator("#astana-map > svg")
    original_view = svg.get_attribute("viewBox")
    page.locator("#map-focus-button").click()
    expect(svg).not_to_have_attribute("viewBox", original_view)
    page.locator("#map-reset-view").click()
    expect(svg).to_have_attribute("viewBox", original_view)
    check_map_viewport(page)

    def add(measure_id: str, district_id: str | None = None) -> None:
        add_map_measure(page, measure_id, district_id)

    add("M3", "nura")
    check_map_motion(page)
    expect(page.locator("#map-plan-budget")).to_have_text("30 / 100")
    expect(page.locator('[data-map-project="M3"]')).to_have_attribute("data-project-district", "nura")
    page.evaluate('window.existingTrain = document.querySelector(\'[data-map-project="M3"]\')')
    add("M4", "saryarka")
    assert page.evaluate('window.existingTrain === document.querySelector(\'[data-map-project="M3"]\')'), "Adding a park must preserve the existing train node/animation."
    assert page.evaluate("window.mapVehicle.isConnected"), "Adding a park must also preserve the moving vehicle node."
    pick_map_measure(page, "M1")
    expect_invalid_candidate(page, "автобусные полосы")
    expect(page.locator('[data-map-project="M1"]')).to_have_count(0)
    expect(page.locator("#map-plan-budget")).to_have_text("45 / 100")
    # Project activation should inspect the actual stored district, then remove
    # only that project from both the map and catalogue plan.
    page.locator('[data-map-project="M3"]').focus()
    page.locator('[data-map-project="M3"]').press("Space")
    expect(page.locator("#map-district")).to_have_value("nura")
    expect(page.locator("#map-measure")).to_have_value("M3")
    page.locator("#map-remove-button").click()
    expect(page.locator('[data-map-project="M3"]')).to_have_count(0)
    expect(page.locator('[data-map-project="M4"]')).to_have_count(1)
    add("M6")
    expect(page.locator('[data-map-project="M6"]')).to_have_attribute("data-project-district", "city")
    expect(page.locator('[data-map-project="M6"] [data-object-district]')).to_have_count(5)
    expect(page.locator(".selection-slot.filled")).to_have_count(2)
    pick_map_measure(page, "M5")
    expect_invalid_candidate(page, "2")
    expect(page.locator('[data-map-project="M5"]')).to_have_count(0)
    page.reload(wait_until="networkidle")
    expect(page.locator("[data-map-project]")).to_have_count(2)
    expect(page.locator('[data-map-project="M4"]')).to_have_attribute("data-project-district", "saryarka")
    expect(page.locator("#map-mode")).to_have_attribute("data-mode", "draft")
    page.locator("#reset-button").click()
    expect(page.locator("[data-map-project]")).to_have_count(0)

    # Each of the fourteen measures must draw its own project and be removable.
    config = page.request.get(f"{base_url}/api/config").json()
    for measure in config["measures"]:
        add(measure["id"], "almaty")
        expect(page.locator(f'[data-map-project="{measure["id"]}"]')).to_have_attribute(
            "data-project-district", "city" if measure["type"] == "city" else "almaty"
        )
        expect(page.locator(f'[data-map-project="{measure["id"]}"] [data-object-district]')).to_have_count(
            5 if measure["type"] == "city" else 1
        )
        page.locator("#map-remove-button").click()
        expect(page.locator("[data-map-project]")).to_have_count(0)

    check_candidate_guidance(page)
    check_map_layout(page)
    page.locator("#load-example-button").click()
    expect(page.locator("[data-map-project]")).to_have_count(5)
    expect(page.locator("#map-calculate-button")).to_be_enabled()
    page.locator("#map-calculate-button").click()
    expect(page.locator("#result-score")).to_have_text("56.54", timeout=15_000)
    expect(page.locator("#map-mode")).to_have_attribute("data-mode", "calculated")
    page.locator("#map-district").select_option("nura")
    expect(page.locator("#map-district-score")).to_have_text("52.96")
    check_map_views(page)
    page.locator('[data-remove="M7"]').click()
    expect(page.locator("#map-mode")).to_have_attribute("data-mode", "draft")
    expect(page.locator("#map-district-score")).to_have_text("49.18")
    expect(page.locator('[data-map-project="M7"]')).to_have_count(0)
    expect(page.locator("#map-calculate-button")).to_be_disabled()

    check_pending_adds(page)
    if errors:
        raise AssertionError("Map JavaScript errors: " + "; ".join(errors))
    context.close()
