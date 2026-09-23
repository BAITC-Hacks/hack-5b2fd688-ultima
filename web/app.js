const state = {
  config: null,
  selections: [],
  validation: null,
  filter: 'all',
  report: null,
  loading: false,
  adding: false,
  selectionsVersion: 0,
  draftDistricts: {},
  validationRequest: 0,
  leaderboard: [],
  comparisonTeam: null,
  teamTokens: Object.create(null),
  leaderboardLoading: false,
  activeDistrict: 'nura',
  savedPlan: null,
  savedPlanLoading: false,
  savedPlanError: '',
  savedPlanRequest: 0,
};

const STORAGE_KEY = 'akim-simulator-selections-v1';
const TEAM_TOKENS_KEY = 'akim-simulator-team-tokens-v1';
const TEAM_NAME_KEY = 'akim-simulator-team-name-v1';
const COMPARISON_KEY = 'akim-simulator-plan-a-v1';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function formatScore(value) {
  return Number(value).toFixed(2);
}

function signed(value, digits = 2) {
  const number = Number(value);
  if (Math.abs(number) < 0.000001) return Number(0).toFixed(digits);
  return `${number > 0 ? '+' : '−'}${Math.abs(number).toFixed(digits)}`;
}

function russianCount(value, forms) {
  const number = Math.abs(value) % 100;
  const lastDigit = number % 10;
  if (number > 10 && number < 20) return forms[2];
  if (lastDigit > 1 && lastDigit < 5) return forms[1];
  if (lastDigit === 1) return forms[0];
  return forms[2];
}

function measureById(id) {
  return state.config.measures.find((measure) => measure.id === id);
}

function districtById(id) {
  return state.config.districts.find((district) => district.id === id);
}

function saveSelections() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.selections));
  } catch {
    // The simulator works even when browser storage is disabled.
  }
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('visible');
  window.clearTimeout(showToast.timeout);
  showToast.timeout = window.setTimeout(() => toast.classList.remove('visible'), 3400);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => String(item.msg || '').replace(/^Value error, /, '')).join(' ')
      : typeof data.detail === 'string' ? data.detail : '';
    const message = (data.errors || []).join(' ') || detail || 'Запрос не выполнен.';
    const error = new Error(message);
    error.data = data;
    error.status = response.status;
    throw error;
  }
  return data;
}

function loadSavedSelections() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    if (!Array.isArray(saved)) return;
    const knownMeasures = new Map(state.config.measures.map((measure) => [measure.id, measure]));
    const knownDistricts = new Set(state.config.districts.map((district) => district.id));
    const seen = new Set();
    state.selections = saved
      .filter((item) => {
        const measure = knownMeasures.get(item?.measure_id);
        if (!measure || seen.has(item.measure_id)) return false;
        if (measure.type === 'district' && !knownDistricts.has(item.district_id)) return false;
        if (measure.type === 'city' && item.district_id != null) return false;
        seen.add(item.measure_id);
        return true;
      })
      .slice(0, state.config.required_selections)
      .map((item) => ({ measure_id: item.measure_id, district_id: item.district_id ?? null }));
  } catch {
    state.selections = [];
  }
}

function loadTeamTokens() {
  try {
    const saved = JSON.parse(localStorage.getItem(TEAM_TOKENS_KEY) || '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
      state.teamTokens = Object.assign(Object.create(null), saved);
    }
    $('#team-name').value = localStorage.getItem(TEAM_NAME_KEY) || '';
    const token = state.teamTokens[teamKey($('#team-name').value)];
    $('#team-code').value = typeof token === 'string' ? token : '';
  } catch {
    state.teamTokens = Object.create(null);
  }
}

function teamKey(name) {
  return name.normalize('NFC').trim().replace(/\s+/g, ' ').toLowerCase();
}

function storeTeamToken(name, token) {
  if (!token) return;
  state.teamTokens[teamKey(name)] = token;
  try {
    localStorage.setItem(TEAM_TOKENS_KEY, JSON.stringify(state.teamTokens));
  } catch {
    // Access codes can still be copied manually if browser storage is disabled.
  }
}

function allDirections() {
  const byId = new Map();
  state.config.measures.forEach((measure) => byId.set(measure.direction, measure.direction_label));
  return [...byId.entries()];
}

function renderHero() {
  const baseline = state.config.baseline;
  $('#hero-baseline').textContent = formatScore(baseline.score);
  $('#baseline-critical-count').textContent = baseline.critical_count;
  $('#baseline-critical-caption').textContent = baseline.critical_indicators.map((item) => `${item.district_name} · ${item.indicator_id}: ${item.value}`).join(' / ');
  $('#incompatibility-list').textContent = state.config.incompatibilities.map((rule) => `${rule.measures.join(' + ')}: ${rule.description}`).join(' ');
  const example = state.config.example_scenario;
  $('#example-scenario').hidden = !example;
  if (example) {
    $('#example-title').textContent = example.title;
    $('#example-description').textContent = example.description;
    $('#example-reasons').innerHTML = example.rationale.map((item) => `<li><strong>${escapeHtml(item.measure_id)}</strong> ${escapeHtml(item.text)}</li>`).join('');
    $('#example-expected').textContent = `Пять мер · расход ${example.total_cost} / ${state.config.budget} · контрольный Score ${formatScore(example.score)}. После загрузки нажмите «Рассчитать сценарий».`;
  }
}

function renderBaseline() {
  const { baseline, districts, indicators } = state.config;
  const scores = new Map(baseline.districts.map((district) => [district.id, district.score_after]));
  $('#baseline-intro').textContent = `Исходные показатели одинаковы для всех участников. ${baseline.critical_count} ${russianCount(baseline.critical_count, ['показатель', 'показателя', 'показателей'])} ниже порога 40 — раскройте профили, чтобы выбрать приоритеты.`;
  $('#baseline-scores').innerHTML = districts.map((district) => `
    <button type="button" class="baseline-score-card ${district.id === baseline.weakest_district_id ? 'is-weakest' : ''}" data-baseline-district="${escapeHtml(district.id)}" aria-pressed="${district.id === state.activeDistrict}" aria-controls="baseline-profiles">
      <span>${escapeHtml(district.name)} <i aria-hidden="true">↗</i></span>
      <strong>${formatScore(scores.get(district.id))}</strong>
      <span class="district-meter" aria-hidden="true"><span style="width:${scores.get(district.id)}%"></span></span>
      <small>${Math.round(district.population_share * 100)}% населения${district.id === baseline.weakest_district_id ? ' · слабейший' : ''}</small>
    </button>`).join('');
  $('#baseline-profiles').innerHTML = districts.map((district) => `
    <article class="baseline-profile" data-district-profile="${escapeHtml(district.id)}" ${district.id === state.activeDistrict ? '' : 'hidden'}>
      <div class="baseline-profile-heading"><h3>${escapeHtml(district.name)}</h3><span>${formatScore(scores.get(district.id))} балла</span></div>
      <p>${escapeHtml(district.profile)}</p>
      <dl class="baseline-indicators">${indicators.map((indicator) => {
        const value = district.indicators[indicator.id];
        return `<div class="${value < 40 ? 'is-critical' : ''}" title="${escapeHtml(indicator.description)}"><dt><span>${escapeHtml(indicator.id)}</span> ${escapeHtml(indicator.label)}</dt><dd>${value}${value < 40 ? ' <small>ниже 40</small>' : ''}</dd></div>`;
      }).join('')}</dl>
    </article>`).join('');
  $('#baseline-overview').hidden = false;
}

function renderSelections() {
  const container = $('#selection-slots');
  const labels = ['01', '02', '03', '04', '05'];
  const choices = state.selections;
  $('#selection-count').innerHTML = `${choices.length} <span>/ ${state.config.required_selections}</span>`;
  $('#step-label').textContent = `${choices.length} из ${state.config.required_selections} решений`;
  $('#nav-plan-count').textContent = `${choices.length}/${state.config.required_selections}`;
  container.innerHTML = labels.map((number, index) => {
    const selection = choices[index];
    if (!selection) {
      return `<div class="selection-slot" aria-label="Свободное место ${index + 1}">
        <span class="slot-number">${number}</span>
        <a class="slot-empty-label" href="#catalog-title">Выберите инициативу</a><span class="slot-empty-plus" aria-hidden="true">＋</span>
      </div>`;
    }
    const measure = measureById(selection.measure_id);
    if (!measure) return '';
    const district = selection.district_id ? districtById(selection.district_id) : null;
    return `<div class="selection-slot filled" aria-label="Решение ${index + 1}: ${escapeHtml(measure.name)}">
      <span class="slot-number">${number}</span>
      <button class="slot-remove" type="button" data-remove="${escapeHtml(measure.id)}" aria-label="Удалить ${escapeHtml(measure.name)}">×</button>
      <div><p class="slot-measure-name">${escapeHtml(measure.name)}</p><p class="slot-district">${district ? escapeHtml(district.name) : 'Весь город'} · ${measure.cost} ед.</p></div>
    </div>`;
  }).join('');
}

function directionIcon(direction) {
  const paths = {
    transport: '<rect x="4" y="3" width="16" height="16" rx="4"/><path d="M4 11h16M8 3v8M16 3v8M7 19v2M17 19v2M7 15h1M16 15h1"/>',
    ecology: '<path d="M5 18C-1 5 11 3 21 3c0 12-6 19-14 16M3 21 16 8"/>',
    social: '<path d="M12 21S2 15 2 8a5 5 0 0 1 10-1 5 5 0 0 1 10 1c0 7-10 13-10 13zM8 11h8M12 7v8"/>',
    safety: '<path d="m12 2 8 3v6c0 6-8 11-8 11S4 17 4 11V5zM8 11l3 3 5-6"/>',
    services: '<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 22h8M12 18v4M7 9h10M7 13h6"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[direction] || paths.services}</svg>`;
}

function renderFilters() {
  const directions = allDirections();
  const options = [['all', 'Все меры'], ...directions];
  $('#filter-list').innerHTML = options.map(([id, label]) =>
    `<button type="button" class="filter-chip ${state.filter === id ? 'active' : ''}" data-filter="${escapeHtml(id)}" aria-pressed="${state.filter === id}">${escapeHtml(label)}</button>`
  ).join('');
}

function renderCatalog() {
  const selectedIds = new Set(state.selections.map((selection) => selection.measure_id));
  const measures = state.config.measures.filter((measure) => state.filter === 'all' || measure.direction === state.filter);
  $('#catalog-count').textContent = `${measures.length} ${russianCount(measures.length, ['инициатива', 'инициативы', 'инициатив'])}`;
  const districtOptions = state.config.districts.map((district) =>
    `<option value="${escapeHtml(district.id)}">${escapeHtml(district.name)}</option>`
  ).join('');
  $('#measure-list').innerHTML = measures.map((measure) => {
    const selected = selectedIds.has(measure.id);
    const full = state.selections.length >= state.config.required_selections;
    const effects = Object.entries(measure.realised_effects || measure.effects).map(([id, amount]) => {
      const indicator = state.config.indicators.find((item) => item.id === id);
      const displayedAmount = Number(amount.toFixed(2));
      return `<span class="impact-chip ${amount < 0 ? 'negative' : ''}" title="${escapeHtml(id)}: ${escapeHtml(indicator?.description || '')}. Эффект за 8 кварталов с учётом лага.">${escapeHtml(indicator?.label || id)} <strong>${displayedAmount > 0 ? '+' : ''}${displayedAmount}</strong></span>`;
    }).join('');
    const location = measure.type === 'district'
      ? `<select class="district-select" data-district-select="${escapeHtml(measure.id)}" aria-label="Район для мероприятия ${escapeHtml(measure.name)}">
          <option value="">Выберите район</option>${districtOptions}
        </select>`
      : '<span class="measure-type">◎ Во всех районах</span>';
    const selection = state.selections.find((choice) => choice.measure_id === measure.id);
    const selectedPlace = selection?.district_id ? districtById(selection.district_id)?.name : 'Весь город';
    return `<article class="measure-card ${selected ? 'is-selected' : ''} ${full && !selected ? 'is-blocked' : ''}" data-direction="${escapeHtml(measure.direction)}">
        <div class="measure-topline"><div class="category-identity"><span class="category-icon">${directionIcon(measure.direction)}</span><div><span class="area-tag">${escapeHtml(measure.direction_label)}</span><span class="measure-id">${escapeHtml(measure.id)}</span></div></div><div class="measure-cost"><strong>${measure.cost}</strong><span>ед.</span></div></div>
        <h4>${escapeHtml(measure.name)}</h4>
        <p class="measure-description">${escapeHtml(measure.description)}</p>
        <div class="measure-meta">${effects}</div>
        <div class="measure-timing">◷ Лаг ${measure.lag} кв. <span>·</span> ${measure.type === 'district' ? 'Районный проект' : 'Городской проект'}</div>
      <div class="measure-actions">
        ${selected ? `<span class="selected-location">${escapeHtml(selectedPlace)}</span><button class="add-button" type="button" disabled><span>✓</span> В плане</button>` : `${location}<button class="add-button" type="button" data-add="${escapeHtml(measure.id)}" ${full || state.adding ? 'disabled' : ''}><span class="add-icon">＋</span> Добавить</button>`}
      </div>
    </article>`;
  }).join('');

  // Restore district dropdown values after rendering the catalogue.
  $$('[data-district-select]').forEach((select) => {
    const selectedDistrict = state.draftDistricts[select.dataset.districtSelect];
    if (selectedDistrict) select.value = selectedDistrict;
  });
}

function renderBudgetAndValidation() {
  const validation = state.validation || {
    valid: true,
    ready: false,
    errors: [],
    selection_count: state.selections.length,
    remaining_selections: Math.max(0, state.config.required_selections - state.selections.length),
    total_cost: state.selections.reduce((sum, choice) => sum + (measureById(choice.measure_id)?.cost || 0), 0),
    budget_remaining: state.config.budget - state.selections.reduce((sum, choice) => sum + (measureById(choice.measure_id)?.cost || 0), 0),
  };
  const totalCost = validation.total_cost ?? 0;
  const budgetRemaining = validation.budget_remaining ?? (state.config.budget - totalCost);
  $('#budget-total').textContent = state.config.budget;
  $('#budget-spent').textContent = totalCost;
  $('#budget-remaining').textContent = budgetRemaining;
  const progress = $('#budget-progress');
  progress.style.width = `${Math.min(100, Math.max(0, totalCost / state.config.budget * 100))}%`;
  progress.classList.toggle('over-budget', totalCost > state.config.budget);
  progress.parentElement.setAttribute('aria-valuenow', totalCost);
  progress.parentElement.setAttribute('aria-valuemax', state.config.budget);

  const counts = new Map();
  state.selections.forEach((choice) => {
    const measure = measureById(choice.measure_id);
    if (measure) counts.set(measure.direction, (counts.get(measure.direction) || 0) + 1);
  });
  $('#direction-summary').innerHTML = allDirections().map(([id, label]) => {
    const count = counts.get(id) || 0;
    return `<div class="direction-row"><span>${escapeHtml(label)}</span><strong class="${count >= state.config.max_per_direction ? 'at-limit' : ''}">${count} / ${state.config.max_per_direction}</strong><div class="direction-track"><span style="width:${count / state.config.max_per_direction * 100}%"></span></div></div>`;
  }).join('');

  const messages = validation.errors?.length
    ? validation.errors.map((message) => `<span>! ${escapeHtml(message)}</span>`)
    : validation.ready
      ? ['<span class="validation-ok">✓ Все правила соблюдены. Сценарий готов к расчёту.</span>']
      : [`<span class="validation-muted">Осталось выбрать ${validation.remaining_selections} ${russianCount(validation.remaining_selections, ['мероприятие', 'мероприятия', 'мероприятий'])}.</span>`];
  $('#validation-message').innerHTML = messages.join('');
  const calculate = $('#calculate-button');
  calculate.disabled = !validation.ready || state.loading;
  calculate.classList.toggle('is-loading', state.loading);
  $('.button-label', calculate).textContent = state.loading ? 'Считаем последствия…' : 'Рассчитать сценарий';
  $('#calculate-hint').textContent = state.loading
    ? 'Сначала считаем модель, затем формируем объяснение'
    : validation.ready
      ? 'Все решения проходят проверку правил'
      : 'Добавьте пять мероприятий, чтобы увидеть результат';
  $('#mobile-dock-summary').textContent = `${state.selections.length} из ${state.config.required_selections} · ${totalCost} / ${state.config.budget} ед.`;
  const mobileCalculate = $('#mobile-calculate-button');
  mobileCalculate.disabled = state.loading || (!validation.ready && !state.report);
  mobileCalculate.innerHTML = `${state.loading ? 'Считаем…' : state.report ? 'К результату' : 'Рассчитать'} <span aria-hidden="true">↗</span>`;
  $('#save-comparison-button').disabled = !state.report || state.loading;
}

function renderScoreBreakdown(report) {
  const breakdown = report.score_breakdown;
  $('#score-breakdown').hidden = !breakdown;
  if (!breakdown) return;
  $('#score-formula').textContent = breakdown.formula;
  $('#score-components').innerHTML = breakdown.components.map((component) => {
    const context = component.id === 'weakest'
      ? `${component.before.district_name} → ${component.after.district_name}`
      : component.id === 'critical' ? 'Количество пар «район × показатель» ниже 40' : 'С учётом долей населения';
    return `<tr data-component="${escapeHtml(component.id)}"><th scope="row">${escapeHtml(component.label)} <span class="component-weight">${component.coefficient < 0 ? '−1 за показатель' : `${component.coefficient * 100}%`}</span><small>${escapeHtml(context)}</small><small>Исходная величина: ${Number(component.before.value).toFixed(5)} → ${Number(component.after.value).toFixed(5)}</small></th><td>${Number(component.before.contribution).toFixed(5)}</td><td>${Number(component.after.contribution).toFixed(5)}</td><td class="${component.delta < 0 ? 'value-negative' : 'value-positive'}">${signed(component.delta, 5)}</td></tr>`;
  }).join('');
  $('#score-components-total').innerHTML = `<tr><th scope="row">Итого Score</th><td>${Number(report.baseline_score).toFixed(5)}</td><td>${Number(report.score).toFixed(5)}</td><td>${signed(report.score_delta, 5)}</td></tr>`;
}

function factEvidenceHtml(fact) {
  if (!fact?.details?.length) return '';
  return `<details class="fact-evidence" data-evidence-id="${escapeHtml(fact.id)}"><summary>Основание расчёта <span aria-hidden="true">↘</span></summary><ul>${fact.details.map((detail) => `<li>${escapeHtml(detail)}</li>`).join('')}</ul></details>`;
}

function renderExplanation(explanation) {
  $('#explanation-summary').textContent = explanation.summary;
  const evidence = explanation.evidence || {};
  $('#explanation-summary-evidence').innerHTML = (evidence.summary || []).map(factEvidenceHtml).join('');
  const sourceBadge = $('#explanation-source');
  sourceBadge.textContent = explanation.source === 'openai' ? 'ИИ-РАЗБОР' : 'ПО ДАННЫМ МОДЕЛИ';
  sourceBadge.classList.toggle('ai-source', explanation.source === 'openai');
  for (const section of ['strengths', 'risks', 'consequences']) {
    $(`#explanation-${section}`).innerHTML = (explanation[section] || []).map((text, index) =>
      `<li>${escapeHtml(text)}${factEvidenceHtml(evidence[section]?.[index])}</li>`
    ).join('');
  }
  $('#explanation-consequences-wrap').hidden = !explanation.consequences?.length;
  $('#explanation-recommendations-wrap').hidden = !explanation.recommendations?.length;
  $('#explanation-recommendations').innerHTML = (explanation.recommendations || []).map((text, index) =>
    `<div class="verified-recommendation"><p>${escapeHtml(text)}</p>${factEvidenceHtml(evidence.recommendations?.[index])}</div>`
  ).join('');
  $('#explanation-note').hidden = !explanation.note;
  $('#explanation-note').textContent = explanation.note || '';
}

function renderResults() {
  const panel = $('#results-panel');
  panel.hidden = !state.report;
  $('#results-nav').setAttribute('aria-disabled', String(!state.report));
  if (!state.report) return;

  const report = state.report;
  const explanation = report.explanation;
  $('#result-score').textContent = formatScore(report.score);
  $('#result-current').textContent = formatScore(report.score);
  $('#result-baseline').textContent = formatScore(report.baseline_score);
  const delta = $('#result-delta');
  const displayedDelta = report.display_score_delta ?? (Number(report.score.toFixed(2)) - Number(report.baseline_score.toFixed(2)));
  delta.textContent = `${signed(displayedDelta)} балла`;
  delta.classList.toggle('negative', displayedDelta < 0);
  $('#result-spent').textContent = report.total_cost;
  $('#result-remaining').textContent = report.budget_remaining;
  $('#result-critical').textContent = report.critical_count;
  $('#result-announcement').textContent = `Результат сценария: Score ${formatScore(report.score)}, изменение ${signed(displayedDelta)}. Критических показателей: ${report.critical_count}.`;
  const criticalList = $('#critical-list');
  criticalList.hidden = report.critical_count === 0;
  criticalList.innerHTML = report.critical_count
    ? `<div class="critical-heading"><span aria-hidden="true">!</span><div><strong>Показатели ниже 40 — штраф в итоговом Score</strong><p>Эти проблемы остались после выбранных решений.</p></div></div><ul>${report.critical_indicators.map((item) => `<li><strong>${escapeHtml(item.district_name)}</strong> · ${escapeHtml(item.indicator_label)} <span>${Number(item.value).toFixed(1)}</span></li>`).join('')}</ul>`
    : '';

  renderScoreBreakdown(report);
  renderExplanation(explanation);

  const alternatives = report.alternative_scenarios || [];
  $('#alternative-list').innerHTML = alternatives.length
    ? alternatives.map((alternative, index) => `<article class="alternative-card">
        <div class="alternative-rank">0${index + 1}</div>
        <div class="alternative-main">
          <p class="alternative-description">${escapeHtml(alternative.description)}</p>
          <div class="alternative-meta"><span>Score <strong>${formatScore(alternative.score)}</strong></span><span class="alternative-gain">${signed(alternative.display_score_delta ?? alternative.score_delta)} к сценарию</span><span>${alternative.total_cost} / 100 ед.</span><span>Критических: ${alternative.critical_count}</span></div>
        </div>
        <button class="alternative-button" type="button" data-use-alternative="${index}">Выбрать план <span aria-hidden="true">↗</span></button>
      </article>`).join('')
    : `<div class="alternative-empty"><span aria-hidden="true">✓</span><p>${escapeHtml(report.recommendation_message || 'Среди одиночных замен сценария улучшения не найдено.')}</p><small>Это означает, что ни одна допустимая замена одной меры или района не повысила отображаемый Score.</small></div>`;

  $('#district-chart').innerHTML = report.districts.map((district) => {
    const isWeakest = district.id === report.weakest_district_id;
    return `<div class="district-chart-card ${isWeakest ? 'is-weakest' : ''}">
      <div class="district-chart-name"><span>${escapeHtml(district.name)}</span>${isWeakest ? '<span class="weakest-tag">ФОКУС</span>' : ''}</div>
      <div class="district-chart-value">${formatScore(district.score_before)} → <strong>${formatScore(district.score_after)}</strong></div>
      <div class="district-bar" role="img" aria-label="${escapeHtml(district.name)}: ${formatScore(district.score_before)} до, ${formatScore(district.score_after)} после">
        <span class="district-bar-before" style="width:${Math.max(0, district.score_before)}%"></span>
        <span class="district-bar-after" style="width:${Math.max(0, district.score_after)}%"></span>
      </div>
      <div class="district-population">${Math.round(district.population_share * 100)}% населения · ${signed(district.score_delta)} балла</div>
    </div>`;
  }).join('');

  $('#district-details').innerHTML = report.districts.map((district, index) => {
    const changed = district.indicators.filter((indicator) => Math.abs(indicator.delta) > 0.000001 || indicator.after < 40);
    const rows = changed.length ? changed.map((indicator) => {
      const contributionTitle = indicator.contributions.map((item) => `${item.source_name}: ${signed(item.amount, 2)}`).join('\n');
      const deltaClass = indicator.delta < 0 ? 'indicator-down' : 'indicator-up';
      return `<tr class="${indicator.after < 40 ? 'critical-indicator-row' : ''}"><td><strong>${escapeHtml(indicator.label)}</strong> <span class="indicator-id">${escapeHtml(indicator.id)}</span>${indicator.after < 40 ? ' <span class="critical-chip">НИЖЕ 40</span>' : ''}${contributionTitle ? `<small class="indicator-contributions">${escapeHtml(contributionTitle)}</small>` : ''}</td><td>${Number(indicator.before).toFixed(1)}</td><td>${Number(indicator.after).toFixed(1)}</td><td class="${deltaClass}">${signed(indicator.delta, 1)}</td></tr>`;
    }).join('') : '<tr><td colspan="4">Выбранные меры не изменили показатели этого района.</td></tr>';
    return `<details class="district-detail" ${district.id === report.weakest_district_id || index === 0 ? 'open' : ''}>
      <summary><span class="district-detail-title">${escapeHtml(district.name)}</span><span class="district-detail-score">${formatScore(district.score_before)} → ${formatScore(district.score_after)}</span><span class="district-detail-delta">${signed(district.score_delta)}</span></summary>
      <div class="indicator-table-wrap"><table class="indicator-table"><thead><tr><th>ПОКАЗАТЕЛЬ</th><th>БЫЛО</th><th>СТАЛО</th><th>Δ</th></tr></thead><tbody>${rows}</tbody></table></div>
    </details>`;
  }).join('');

  const synergy = $('#synergy-note');
  synergy.hidden = report.applied_synergies.length === 0;
  $('#synergy-copy').textContent = report.applied_synergies.map((item) =>
    `${item.measures.join(' + ')} — +${item.amount} к ${item.indicator_id}${item.district_id ? ` в районе ${districtById(item.district_id)?.name}` : ' во всех районах'}. ${item.description}`
  ).join(' ');
}

function selectionsFromReport(report) {
  return report.selected_measures.map((measure) => ({ measure_id: measure.id, district_id: measure.district_id ?? null }));
}

function selectionKey(selection) {
  return `${selection.measure_id || selection.id}:${selection.district_id || 'city'}`;
}

function renderPersonalComparison() {
  const panel = $('#personal-comparison');
  const saved = state.savedPlan;
  panel.hidden = !saved && !state.savedPlanLoading && !state.savedPlanError;
  $('#save-comparison-button').textContent = saved ? 'Обновить план А' : 'Сохранить для сравнения';
  const content = $('#personal-comparison-content');
  if (state.savedPlanLoading) {
    content.innerHTML = '<p class="comparison-notice" role="status">Пересчитываем сохранённый план А по текущей модели…</p>';
    return;
  }
  if (state.savedPlanError) {
    content.innerHTML = `<div class="comparison-notice"><p>${escapeHtml(state.savedPlanError)}</p><button class="outline-button" data-restore-comparison type="button">Повторить восстановление</button></div>`;
    return;
  }
  if (!saved) {
    content.innerHTML = '';
    return;
  }
  const a = saved.report;
  const differentModel = state.report && state.report.model_version !== a.model_version;
  const b = differentModel ? null : state.report;
  const decisions = (report, other) => {
    const otherKeys = new Set((other?.selected_measures || []).map(selectionKey));
    return report.selected_measures.map((measure) => `<li class="${other && !otherKeys.has(selectionKey(measure)) ? 'decision-different' : ''}"><strong>${escapeHtml(measure.id)} · ${escapeHtml(measure.name)}</strong><span>${escapeHtml(measure.district_name || 'Весь город')} · ${measure.cost} ед.${other && !otherKeys.has(selectionKey(measure)) ? ' · отличается' : ''}</span></li>`).join('');
  };
  const card = (report, label, description, other) => `<article class="personal-plan-card"><span class="eyebrow">${label}</span><p>${description}</p><div class="personal-plan-score"><strong>${formatScore(report.score)}</strong><span>Score</span></div><div class="personal-plan-meta"><span>Бюджет <b>${report.total_cost} / ${report.budget}</b></span><span>Критических <b>${report.critical_count}</b></span></div><ol class="personal-plan-decisions">${decisions(report, other)}</ol></article>`;
  const same = b && saved.selections.map(selectionKey).sort().join('|') === selectionsFromReport(b).map(selectionKey).sort().join('|');
  let comparison = '';
  if (b) {
    const delta = Number((Number(formatScore(b.score)) - Number(formatScore(a.score))).toFixed(2));
    const beforeDistricts = new Map(a.districts.map((district) => [district.id, district]));
    const changes = [];
    const districtRows = b.districts.map((district) => {
      const before = beforeDistricts.get(district.id);
      const beforeIndicators = new Map(before.indicators.map((indicator) => [indicator.id, indicator]));
      district.indicators.forEach((indicator) => {
        const old = beforeIndicators.get(indicator.id).after;
        if (Math.abs(indicator.after - old) > 1e-9) {
          changes.push({ district: district.name, indicator: indicator.label, before: old, after: indicator.after, delta: indicator.after - old });
        }
      });
      const districtDelta = Number((Number(formatScore(district.score_after)) - Number(formatScore(before.score_after))).toFixed(2));
      return `<tr><th scope="row">${escapeHtml(district.name)}</th><td>${formatScore(before.score_after)}</td><td>${formatScore(district.score_after)}</td><td class="${districtDelta < 0 ? 'value-negative' : 'value-positive'}">${signed(districtDelta)}</td></tr>`;
    }).join('');
    changes.sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta));
    const effects = (items, empty) => items.length ? `<ul>${items.map((item) => `<li><strong>${escapeHtml(item.district)} · ${escapeHtml(item.indicator)}</strong><span>${item.before.toFixed(2)} → ${item.after.toFixed(2)} <b>${signed(item.delta)}</b></span></li>`).join('')}</ul>` : `<p>${empty}</p>`;
    comparison = `<div class="personal-comparison-delta"><div><span>Переход А → Б</span><strong id="personal-score-delta" class="${delta < 0 ? 'value-negative' : 'value-positive'}">${signed(delta)} Score</strong></div><p>${same ? 'Планы совпадают. Измените решения и рассчитайте план Б, чтобы увидеть компромисс.' : `Изменение расходов: ${signed(b.total_cost - a.total_cost, 0)} ед. · Критических показателей: ${a.critical_count} → ${b.critical_count}.`}</p></div>
      <div class="breakdown-table-wrap"><table class="breakdown-table personal-district-table"><thead><tr><th scope="col">Район</th><th scope="col">План А</th><th scope="col">План Б</th><th scope="col">Б − А</th></tr></thead><tbody>${districtRows}</tbody></table></div>
      <details class="personal-effects" open><summary>Что получили и потеряли при переходе А → Б</summary><p class="result-help">Изменения относительно плана А. Более низкое значение в плане Б может означать отказ от улучшения, а не ухудшение исходного города.</p><div class="personal-effects-columns"><section class="personal-gains"><h3>Выигрыш в показателях</h3>${effects(changes.filter((item) => item.delta > 0), 'Показатели не стали выше, чем в плане А.')}</section><section class="personal-losses"><h3>Потерянные эффекты</h3>${effects(changes.filter((item) => item.delta < 0), 'Показатели не стали ниже, чем в плане А.')}</section></div></details>`;
  }
  content.innerHTML = `<p class="result-help">План А — сохранённый снимок. План Б — текущий рассчитанный результат. Оба используют одинаковые исходные данные и версию модели.</p><div class="personal-plan-grid">${card(a, 'ПЛАН А', 'Сохранён для сравнения', b)}${b ? card(b, 'ПЛАН Б', 'Текущий рассчитанный план', a) : '<div class="personal-plan-empty"><strong>Соберите план Б</strong><p>Измените решения и нажмите «Рассчитать сценарий». План А сохранится, пока вы экспериментируете.</p><a class="hero-link" href="#workspace">Перейти к решениям ↗</a></div>'}</div><div class="personal-plan-actions"><button class="outline-button" type="button" data-load-saved-plan>Вернуть решения плана А ↗</button><span>${saved.persisted ? 'Хранится в этом браузере. После обновления страницы пересчитывается сервером.' : 'Сохранён на этой странице. Постоянное хранилище браузера недоступно.'}</span></div>${comparison}`;
  if (differentModel) {
    $('.personal-plan-empty', content).innerHTML = '<strong>Версия модели изменилась</strong><p>Обновите страницу и сохраните новый план А. Для сравнения оба расчёта должны использовать одну версию модели.</p>';
  }
}

function saveComparisonPlan() {
  if (!state.report || state.loading) return;
  state.savedPlanRequest++;
  state.savedPlanLoading = false;
  state.savedPlanError = '';
  state.savedPlan = { selections: selectionsFromReport(state.report), report: structuredClone(state.report) };
  let persisted = true;
  try {
    localStorage.setItem(COMPARISON_KEY, JSON.stringify({ model_version: state.report.model_version, selections: state.savedPlan.selections }));
  } catch {
    persisted = false;
  }
  state.savedPlan.persisted = persisted;
  renderPersonalComparison();
  showToast(persisted ? 'План А сохранён. Измените решения и рассчитайте план Б.' : 'План А сохранён на этой странице. Браузер не разрешил постоянное хранение.');
  $('#personal-comparison-title').focus({ preventScroll: true });
  $('#personal-comparison').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function restoreComparisonPlan() {
  const request = ++state.savedPlanRequest;
  let stored;
  try {
    stored = localStorage.getItem(COMPARISON_KEY);
  } catch {
    return;
  }
  if (!stored) return;
  state.savedPlanLoading = true;
  state.savedPlanError = '';
  renderPersonalComparison();
  try {
    const saved = JSON.parse(stored);
    if (saved?.model_version !== state.config.model_version) {
      throw new Error('План А сохранён для другой версии модели. Сохраните новый рассчитанный план для сравнения.');
    }
    if (!Array.isArray(saved.selections) || saved.selections.length !== state.config.required_selections) {
      throw new Error('Сохранённый план А повреждён. Сохраните новый рассчитанный план.');
    }
    // Persist only choices; numeric reports are always reconstructed by the engine.
    const report = await api('/api/simulate', { selections: saved.selections });
    if (request !== state.savedPlanRequest) return;
    if (report.model_version !== state.config.model_version) {
      throw new Error('Версия модели на сервере изменилась. Обновите страницу и сохраните новый план А.');
    }
    state.savedPlan = { selections: selectionsFromReport(report), report, persisted: true };
  } catch (error) {
    if (request !== state.savedPlanRequest) return;
    state.savedPlan = null;
    state.savedPlanError = error instanceof SyntaxError ? 'Не удалось прочитать сохранённый план А. Сохраните новый план.' : error.message;
  } finally {
    if (request === state.savedPlanRequest) {
      state.savedPlanLoading = false;
      renderPersonalComparison();
    }
  }
}

function clearComparisonPlan() {
  state.savedPlanRequest++;
  state.savedPlan = null;
  state.savedPlanLoading = false;
  state.savedPlanError = '';
  try {
    localStorage.removeItem(COMPARISON_KEY);
  } catch {
    showToast('Сравнение убрано с этой страницы. Браузер не разрешил изменить хранилище.');
  }
  renderPersonalComparison();
}

function renderLeaderboard() {
  const tbody = $('#leaderboard-rows');
  const entries = state.leaderboard;
  const status = $('#comparison-status');
  if (!status.dataset.error) {
    status.textContent = state.leaderboardLoading
      ? 'Загружаем результаты команд…'
      : entries.length
        ? `Сохранено ${entries.length} ${russianCount(entries.length, ['сценарий', 'сценария', 'сценариев'])} по текущей версии модели.`
        : 'Пока нет сохранённых команд. Рассчитайте сценарий и добавьте первый результат.';
  }
  $('#refresh-leaderboard').disabled = state.leaderboardLoading;
  tbody.innerHTML = entries.map((entry, index) => `<tr class="${state.comparisonTeam === teamKey(entry.team_name) ? 'comparison-selected' : ''}">
    <td class="comparison-rank">${entry.rank}</td>
    <td class="comparison-name">${escapeHtml(entry.team_name)}</td>
    <td class="comparison-score">${formatScore(entry.score)}</td>
    <td class="comparison-change">${signed(entry.display_score_delta)}</td>
    <td>${entry.total_cost} / ${state.config.budget}</td>
    <td>${entry.critical_count}</td>
    <td><button type="button" data-compare-team="${index}" class="comparison-action">Сравнить ↗</button></td>
  </tr>`).join('');

  const detail = $('#team-comparison');
  const chosen = entries.find((entry) => teamKey(entry.team_name) === state.comparisonTeam);
  if (!chosen) {
    detail.hidden = true;
    detail.innerHTML = '';
    return;
  }

  const own = state.report || state.config.baseline;
  const ownScores = Object.fromEntries(own.districts.map((district) => [district.id, district.score_after]));
  const difference = Number((Number(formatScore(chosen.score)) - Number(formatScore(own.score))).toFixed(2));
  const districtRows = state.config.districts.map((district) => {
    const teamDistrict = chosen.district_scores[district.id];
    return `<tr><td>${escapeHtml(district.name)}</td><td>${formatScore(ownScores[district.id])}</td><td>${formatScore(teamDistrict)}</td><td>${signed(Number((Number(formatScore(teamDistrict)) - Number(formatScore(ownScores[district.id]))).toFixed(2)))}</td></tr>`;
  }).join('');
  const measures = chosen.selections.map((selection) => {
    const measure = measureById(selection.measure_id);
    const district = selection.district_id ? districtById(selection.district_id)?.name : 'весь город';
    return measure ? `<li>${escapeHtml(measure.id)} · ${escapeHtml(measure.name)} — ${escapeHtml(district)}</li>` : '';
  }).join('');
  detail.hidden = false;
  detail.innerHTML = `<div class="team-comparison-top">
    <div><span class="panel-kicker">ПОДРОБНОСТИ ПЛАНА</span><h3>${escapeHtml(chosen.team_name)}</h3></div>
    <button type="button" class="comparison-close" id="close-comparison" aria-label="Закрыть сравнение">×</button>
  </div>
  <div class="comparison-score-pair"><div><span>${state.report ? 'ВАШ ТЕКУЩИЙ ПЛАН' : 'СТАРТОВЫЙ ГОРОД'}</span><strong>${formatScore(own.score)}</strong></div><div><span>ПЛАН КОМАНДЫ</span><strong>${formatScore(chosen.score)}</strong></div><div class="comparison-difference"><span>РАЗНИЦА</span><strong>${signed(difference)}</strong></div></div>
  <div class="comparison-columns"><div><h4>Районы: ваш план → команда</h4><table class="comparison-district-table"><thead><tr><th>РАЙОН</th><th>ВАШ</th><th>КОМАНДА</th><th>Δ</th></tr></thead><tbody>${districtRows}</tbody></table></div>
  <div><h4>Пять решений команды</h4><ol class="comparison-decisions">${measures}</ol><button type="button" class="comparison-load-button" data-load-team="${entries.indexOf(chosen)}">Взять этот план в симулятор <span aria-hidden="true">↗</span></button></div></div>`;
}

async function refreshLeaderboard() {
  if (state.leaderboardLoading) return;
  state.leaderboardLoading = true;
  delete $('#comparison-status').dataset.error;
  renderLeaderboard();
  try {
    const board = await api('/api/leaderboard');
    state.leaderboard = board.entries;
  } catch (error) {
    const status = $('#comparison-status');
    status.dataset.error = 'true';
    status.textContent = error.message || 'Не удалось загрузить результаты команд.';
  } finally {
    state.leaderboardLoading = false;
    renderLeaderboard();
  }
}

async function submitTeamScenario(event) {
  event.preventDefault();
  if (!state.report || $('#save-team-button').disabled) return;
  const input = $('#team-name');
  const name = input.value.normalize('NFC').trim().replace(/\s+/g, ' ');
  if (!name || name.length > 40) {
    showToast('Название команды должно содержать от 1 до 40 символов.');
    input.focus();
    return;
  }
  const codeInput = $('#team-code');
  const savedToken = state.teamTokens[teamKey(name)];
  const ownerToken = codeInput.value.trim() || (typeof savedToken === 'string' ? savedToken : null);
  const button = $('#save-team-button');
  button.disabled = true;
  const selectionSnapshot = JSON.stringify(state.selections);
  $('#team-save-status').textContent = 'Проверяем план и сохраняем результат команды…';
  try {
    const result = await api('/api/leaderboard', {
      team_name: name,
      owner_token: ownerToken,
      selections: JSON.parse(selectionSnapshot),
    });
    const token = result.entry.owner_token || ownerToken;
    if (token) {
      storeTeamToken(name, token);
      if (teamKey(input.value) === teamKey(name)) codeInput.value = token;
    }
    try {
      localStorage.setItem(TEAM_NAME_KEY, name);
    } catch {
      // The team name remains visible in the form for this session.
    }
    $('#team-save-status').textContent = `План «${name}» сохранён. ${result.entry.owner_token ? 'Код команды доступен в поле выше при выборе её названия. Сохраните его для обновления с другого устройства.' : 'Ваш результат обновлён.'}`;
    await refreshLeaderboard();
    state.comparisonTeam = teamKey(name);
    renderLeaderboard();
  } catch (error) {
    $('#team-save-status').textContent = error.message || 'Не удалось сохранить результат.';
    showToast(error.message || 'Не удалось сохранить результат команды.');
  } finally {
    button.disabled = false;
  }
}

async function loadPlan(selections, message, target = '#catalog-title') {
  state.selections = selections.map((choice) => ({
    measure_id: choice.measure_id,
    district_id: choice.district_id ?? null,
  }));
  state.selectionsVersion++;
  state.validationRequest++;
  const version = state.selectionsVersion;
  state.report = null;
  state.validation = null;
  state.filter = 'all';
  state.draftDistricts = Object.fromEntries(state.selections.filter((choice) => choice.district_id).map((choice) => [choice.measure_id, choice.district_id]));
  $('#plan-choices').open = true;
  saveSelections();
  render();
  await refreshValidation();
  if (version !== state.selectionsVersion) return;
  showToast(message);
  $(target).scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function useTeamPlan(index) {
  const entry = state.leaderboard[index];
  if (entry) await loadPlan(entry.selections, `План «${entry.team_name}» загружен. Рассчитайте его или измените решения.`);
}

function render() {
  renderSelections();
  renderFilters();
  renderCatalog();
  renderBudgetAndValidation();
  renderResults();
  renderPersonalComparison();
  renderLeaderboard();
}

async function refreshValidation() {
  const currentRequest = ++state.validationRequest;
  try {
    const result = await api('/api/validate', { selections: state.selections });
    if (currentRequest !== state.validationRequest) return;
    state.validation = result;
  } catch (error) {
    if (currentRequest !== state.validationRequest) return;
    state.validation = {
      valid: false,
      ready: false,
      errors: [error.message || 'Не удалось проверить выбор.'],
      selection_count: state.selections.length,
      remaining_selections: Math.max(0, state.config.required_selections - state.selections.length),
      total_cost: state.selections.reduce((sum, choice) => sum + (measureById(choice.measure_id)?.cost || 0), 0),
      budget_remaining: state.config.budget - state.selections.reduce((sum, choice) => sum + (measureById(choice.measure_id)?.cost || 0), 0),
    };
  }
  renderBudgetAndValidation();
}

async function addMeasure(measureId) {
  const measure = measureById(measureId);
  if (!measure || state.adding || state.selections.some((item) => item.measure_id === measureId)) return;
  if (state.selections.length >= state.config.required_selections) {
    showToast('В плане уже пять решений. Удалите одно, чтобы выбрать другое.');
    return;
  }
  const districtId = measure.type === 'district' ? state.draftDistricts[measureId] : null;
  if (measure.type === 'district' && !districtId) {
    showToast('Сначала выберите район для этой меры.');
    const select = $(`[data-district-select="${measureId}"]`);
    select?.focus();
    return;
  }
  const proposed = [...state.selections, { measure_id: measureId, district_id: districtId || null }];
  const version = state.selectionsVersion;
  state.adding = true;
  $('#measure-list').setAttribute('aria-busy', 'true');
  $$('[data-add]').forEach((button) => { button.disabled = true; });
  const addingButton = $(`[data-add="${measureId}"]`);
  if (addingButton) addingButton.textContent = 'Проверяем…';
  try {
    const validation = await api('/api/validate', { selections: proposed });
    if (version !== state.selectionsVersion) return;
    if (!validation.valid) {
      showToast(validation.errors[0] || 'Этот набор решений недопустим.');
      return;
    }
    state.validationRequest++;
    state.selectionsVersion++;
    state.selections = proposed;
    state.validation = validation;
    state.report = null;
    saveSelections();
    render();
  } catch (error) {
    if (version === state.selectionsVersion) showToast(error.message || 'Не удалось проверить новую меру.');
  } finally {
    state.adding = false;
    $('#measure-list').setAttribute('aria-busy', 'false');
    $$('[data-add]').forEach((button) => {
      button.disabled = state.selections.length >= state.config.required_selections;
      button.innerHTML = '<span class="add-icon">＋</span> Добавить';
    });
  }
}

async function removeMeasure(measureId) {
  const removed = state.selections.find((item) => item.measure_id === measureId);
  if (removed?.district_id) state.draftDistricts[measureId] = removed.district_id;
  state.validationRequest++;
  state.selectionsVersion++;
  state.selections = state.selections.filter((item) => item.measure_id !== measureId);
  state.validation = null;
  state.report = null;
  saveSelections();
  render();
  await refreshValidation();
}

async function calculateScenario() {
  if (!state.validation?.ready || state.loading) return;
  $('#toast').classList.remove('visible');
  const version = state.selectionsVersion;
  const selections = state.selections.map((choice) => ({ ...choice }));
  state.loading = true;
  renderBudgetAndValidation();
  try {
    const report = await api('/api/analyze', { selections });
    if (version !== state.selectionsVersion) return;
    state.report = report;
    renderResults();
    renderPersonalComparison();
    renderLeaderboard();
    window.setTimeout(() => {
      if (version !== state.selectionsVersion || !state.report) return;
      $('#results-title').focus({ preventScroll: true });
      $('#results-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 40);
  } catch (error) {
    if (version !== state.selectionsVersion) return;
    showToast(error.message || 'Не удалось рассчитать сценарий.');
    if (error.data?.errors) {
      state.validation = error.data;
      renderBudgetAndValidation();
    }
  } finally {
    state.loading = false;
    renderBudgetAndValidation();
  }
}

async function useAlternative(index) {
  const alternative = state.report?.alternative_scenarios?.[index];
  if (!alternative) return;
  await loadPlan(alternative.selections, 'План обновлён. Рассчитайте его, чтобы увидеть итог и новые варианты.');
}

function resetScenario() {
  if (!state.config) return;
  state.validationRequest++;
  state.selectionsVersion++;
  state.selections = [];
  state.validation = null;
  state.report = null;
  state.filter = 'all';
  state.draftDistricts = {};
  saveSelections();
  render();
  refreshValidation();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function downloadPresentation() {
  if (!state.report || typeof window.buildPresentationHtml !== 'function') {
    showToast('Сначала рассчитайте сценарий, чтобы подготовить презентацию.');
    return;
  }
  const teamName = $('#team-name').value.trim();
  const content = window.buildPresentationHtml(state.report, teamName);
  const blob = new Blob([content], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `akim-${state.report.model_version}-presentation.html`;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  showToast('Презентация сохранена. Откройте HTML-файл и нажмите «Печать / PDF».');
}

function bindEvents() {
  $$('.nav-link').forEach((link) => {
    link.setAttribute('aria-label', $('span', link).textContent);
    link.addEventListener('click', (event) => {
      if (link.getAttribute('aria-disabled') === 'true') {
        event.preventDefault();
        showToast('Выберите пять инициатив и рассчитайте план, чтобы открыть результат.');
      }
    });
  });
  const navigationSections = ['top', 'workspace', 'results-panel', 'comparison-board'].map((id) => $(`#${id}`));
  let navigationQueued = false;
  const updateNavigation = () => {
    navigationQueued = false;
    let section = 'top';
    for (const element of navigationSections) {
      if (!element.hidden && element.getBoundingClientRect().top <= Math.min(200, window.innerHeight * 0.3)) {
        section = element.id;
      }
    }
    $$('.nav-link').forEach((link) => {
      const active = link.dataset.nav === section;
      link.classList.toggle('active', active);
      if (active) link.setAttribute('aria-current', 'location');
      else link.removeAttribute('aria-current');
    });
  };
  const queueNavigation = () => {
    if (navigationQueued) return;
    navigationQueued = true;
    window.requestAnimationFrame(updateNavigation);
  };
  window.addEventListener('scroll', queueNavigation, { passive: true });
  window.addEventListener('resize', queueNavigation);
  $('#baseline-scores').addEventListener('click', (event) => {
    const button = event.target.closest('[data-baseline-district]');
    if (!button) return;
    state.activeDistrict = button.dataset.baselineDistrict;
    $$('#baseline-scores button').forEach((card) => card.setAttribute('aria-pressed', String(card === button)));
    $$('.baseline-profile').forEach((profile) => {
      profile.hidden = profile.dataset.districtProfile !== state.activeDistrict;
    });
    $('.baseline-details').open = true;
  });
  $('#team-name').addEventListener('input', () => {
    const token = state.teamTokens[teamKey($('#team-name').value)];
    $('#team-code').value = typeof token === 'string' ? token : '';
    $('#team-save-status').textContent = '';
  });
  $('#measure-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-add]');
    if (button && !button.disabled) addMeasure(button.dataset.add);
  });

  $('#selection-slots').addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove]');
    if (button) removeMeasure(button.dataset.remove);
  });

  $('#measure-list').addEventListener('change', (event) => {
    const select = event.target.closest('[data-district-select]');
    if (select) state.draftDistricts[select.dataset.districtSelect] = select.value;
  });

  $('#filter-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-filter]');
    if (!button) return;
    state.filter = button.dataset.filter;
    renderFilters();
    renderCatalog();
    $(`[data-filter="${state.filter}"]`).focus({ preventScroll: true });
  });

  $('#calculate-button').addEventListener('click', calculateScenario);
  $('#load-example-button').addEventListener('click', async () => {
    const example = state.config?.example_scenario;
    if (!example) return;
    $('#example-rationale').open = true;
    await loadPlan(example.selections, 'Контрольный пример загружен. Нажмите «Рассчитать сценарий» или измените решения.', '#example-scenario');
  });
  $('#save-comparison-button').addEventListener('click', saveComparisonPlan);
  $('#clear-comparison-button').addEventListener('click', clearComparisonPlan);
  $('#personal-comparison-content').addEventListener('click', (event) => {
    if (event.target.closest('[data-load-saved-plan]') && state.savedPlan) {
      loadPlan(state.savedPlan.selections, 'Решения плана А восстановлены. Рассчитайте их или продолжите эксперимент.');
    }
    if (event.target.closest('[data-restore-comparison]')) restoreComparisonPlan();
  });
  $('#mobile-calculate-button').addEventListener('click', () => {
    if (state.report) {
      $('#results-title').focus({ preventScroll: true });
      $('#results-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      calculateScenario();
    }
  });
  $('.mobile-dock-status').addEventListener('click', () => { $('#plan-choices').open = true; });
  $('#export-presentation-button').addEventListener('click', downloadPresentation);
  $('#team-submit-form').addEventListener('submit', submitTeamScenario);
  $('#refresh-leaderboard').addEventListener('click', refreshLeaderboard);
  $('#leaderboard-rows').addEventListener('click', (event) => {
    const button = event.target.closest('[data-compare-team]');
    if (!button) return;
    const entry = state.leaderboard[Number(button.dataset.compareTeam)];
    if (!entry) return;
    state.comparisonTeam = teamKey(entry.team_name);
    renderLeaderboard();
    $('#team-comparison').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  $('#team-comparison').addEventListener('click', (event) => {
    if (event.target.closest('#close-comparison')) {
      state.comparisonTeam = null;
      renderLeaderboard();
      return;
    }
    const button = event.target.closest('[data-load-team]');
    if (button) useTeamPlan(Number(button.dataset.loadTeam));
  });
  $('#alternative-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-use-alternative]');
    if (button) useAlternative(Number(button.dataset.useAlternative));
  });
  $('#reset-button').addEventListener('click', resetScenario);
  $('#edit-plan-button').addEventListener('click', () => {
    $('#catalog-title').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}

async function init() {
  bindEvents();
  try {
    state.config = await api('/api/config');
    loadSavedSelections();
    loadTeamTokens();
    $('#plan-choices').open = !window.matchMedia('(max-width: 520px)').matches || state.selections.length > 0;
    renderHero();
    renderBaseline();
    $('#workspace').hidden = false;
    $('#comparison-board').hidden = false;
    $('#mobile-dock').hidden = false;
    render();
    await Promise.all([refreshValidation(), refreshLeaderboard(), restoreComparisonPlan()]);
  } catch (error) {
    $('#app-error').hidden = false;
    $('#app-error-message').textContent = error.message || 'Проверьте, что сервер запущен, и обновите страницу.';
  }
}

init();
