const state = {
  config: null,
  selections: [],
  validation: null,
  filter: 'all',
  report: null,
  loading: false,
  draftDistricts: {},
  validationRequest: 0,
};

const STORAGE_KEY = 'akim-simulator-selections-v1';
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
    const error = new Error((data.errors || []).join(' ') || data.detail || 'Запрос не выполнен.');
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
    state.selections = saved
      .filter((item) => item && typeof item.measure_id === 'string')
      .slice(0, state.config.required_selections)
      .map((item) => ({ measure_id: item.measure_id, district_id: item.district_id ?? null }));
  } catch {
    state.selections = [];
  }
}

function allDirections() {
  const byId = new Map();
  state.config.measures.forEach((measure) => byId.set(measure.direction, measure.direction_label));
  return [...byId.entries()];
}

function renderHero() {
  const baseline = state.config.baseline.score;
  $('#hero-baseline').textContent = formatScore(baseline);
  $('#hero-score-orb').style.setProperty('--score-angle', `${Math.max(0, Math.min(100, baseline)) * 3.6}deg`);
}

function renderSelections() {
  const container = $('#selection-slots');
  const labels = ['01', '02', '03', '04', '05'];
  const choices = state.selections;
  $('#selection-count').innerHTML = `${choices.length} <span>/ ${state.config.required_selections}</span>`;
  $('#step-label').textContent = `${choices.length} из ${state.config.required_selections} решений`;
  container.innerHTML = labels.map((number, index) => {
    const selection = choices[index];
    if (!selection) {
      return `<div class="selection-slot" aria-label="Свободное место ${index + 1}">
        <div class="slot-topline"><span class="slot-number">${number}</span><span class="slot-direction-mark">＋</span></div>
        <span class="slot-empty-label">Выберите<br />мероприятие</span>
      </div>`;
    }
    const measure = measureById(selection.measure_id);
    if (!measure) return '';
    const district = selection.district_id ? districtById(selection.district_id) : null;
    return `<div class="selection-slot filled" aria-label="Решение ${index + 1}: ${escapeHtml(measure.name)}">
      <div class="slot-topline"><span class="slot-number">${number}</span><span class="slot-direction-mark">✳</span></div>
      <button class="slot-remove" type="button" data-remove="${escapeHtml(measure.id)}" aria-label="Удалить ${escapeHtml(measure.name)}">×</button>
      <div><p class="slot-measure-name">${escapeHtml(measure.name)}</p><p class="slot-district">${district ? escapeHtml(district.name) : 'Весь город'} · ${measure.cost} ед.</p></div>
    </div>`;
  }).join('');
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
    const effects = Object.entries(measure.effects).map(([id, amount]) => {
      const indicator = state.config.indicators.find((item) => item.id === id);
      return `<span class="impact-chip ${amount < 0 ? 'negative' : ''}" title="${escapeHtml(indicator?.label || id)}">${escapeHtml(id)} ${amount > 0 ? '+' : ''}${amount}</span>`;
    }).join('');
    const location = measure.type === 'district'
      ? `<select class="district-select" data-district-select="${escapeHtml(measure.id)}" aria-label="Район для мероприятия ${escapeHtml(measure.name)}">
          <option value="">Выберите район</option>${districtOptions}
        </select>`
      : '<span class="measure-type">ДЕЙСТВУЕТ ПО ВСЕМУ ГОРОДУ</span>';
    return `<article class="measure-card ${selected ? 'is-selected' : ''} ${full && !selected ? 'is-blocked' : ''}">
      <div class="measure-main">
        <div class="measure-topline"><span class="measure-id">${escapeHtml(measure.id)}</span><span class="area-tag">${escapeHtml(measure.direction_label)}</span><span class="measure-type">${measure.type === 'district' ? 'ОДИН РАЙОН' : 'ВЕСЬ ГОРОД'}</span></div>
        <h4>${escapeHtml(measure.name)}</h4>
        <p class="measure-description">${escapeHtml(measure.description)}</p>
        <div class="measure-meta"><span class="impact-chip">Лаг ${measure.lag} кв.</span>${effects}</div>
      </div>
      <div class="measure-actions">
        <div class="measure-cost"><strong>${measure.cost}</strong><span>единиц</span></div>
        ${selected ? '<button class="add-button" type="button" disabled><span>✓</span> В плане</button>' : `${location}<button class="add-button" type="button" data-add="${escapeHtml(measure.id)}" ${full ? 'disabled' : ''}><span class="add-icon">＋</span> Добавить</button>`}
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
}

function renderResults() {
  const panel = $('#results-panel');
  panel.hidden = !state.report;
  if (!state.report) return;

  const report = state.report;
  const explanation = report.explanation;
  $('#result-score').textContent = formatScore(report.score);
  $('#result-current').textContent = formatScore(report.score);
  $('#result-baseline').textContent = formatScore(report.baseline_score);
  const delta = $('#result-delta');
  delta.textContent = `${signed(report.score_delta)} балла`;
  delta.classList.toggle('negative', report.score_delta < 0);
  $('#result-spent').textContent = report.total_cost;
  $('#result-remaining').textContent = report.budget_remaining;
  $('#result-critical').textContent = report.critical_count;

  $('#explanation-summary').textContent = explanation.summary;
  const sourceBadge = $('#explanation-source');
  sourceBadge.textContent = explanation.source === 'openai' ? 'ИИ-РАЗБОР' : 'ПО ДАННЫМ МОДЕЛИ';
  sourceBadge.classList.toggle('ai-source', explanation.source === 'openai');
  $('#explanation-strengths').innerHTML = explanation.strengths.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  $('#explanation-risks').innerHTML = explanation.risks.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  const recommendations = explanation.recommendations || [];
  $('#explanation-recommendations-wrap').hidden = recommendations.length === 0;
  $('#explanation-recommendations').textContent = recommendations.join(' ');
  $('#explanation-note').hidden = !explanation.note;
  $('#explanation-note').textContent = explanation.note || '';

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
    const changed = district.indicators.filter((indicator) => Math.abs(indicator.delta) > 0.000001);
    const rows = changed.length ? changed.map((indicator) => {
      const contributionTitle = indicator.contributions.map((item) => `${item.source_name}: ${signed(item.amount, 2)}`).join('\n');
      const deltaClass = indicator.delta < 0 ? 'indicator-down' : 'indicator-up';
      return `<tr title="${escapeHtml(contributionTitle)}"><td><strong>${escapeHtml(indicator.label)}</strong> <span class="indicator-id">${escapeHtml(indicator.id)}</span></td><td>${Number(indicator.before).toFixed(1)}</td><td>${Number(indicator.after).toFixed(1)}</td><td class="${deltaClass}">${signed(indicator.delta, 1)}</td></tr>`;
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

function render() {
  renderSelections();
  renderFilters();
  renderCatalog();
  renderBudgetAndValidation();
  renderResults();
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
  if (!measure || state.selections.some((item) => item.measure_id === measureId)) return;
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
  state.selections.push({ measure_id: measureId, district_id: districtId || null });
  state.report = null;
  saveSelections();
  render();
  await refreshValidation();
}

async function removeMeasure(measureId) {
  const removed = state.selections.find((item) => item.measure_id === measureId);
  if (removed?.district_id) state.draftDistricts[measureId] = removed.district_id;
  state.selections = state.selections.filter((item) => item.measure_id !== measureId);
  state.report = null;
  saveSelections();
  render();
  await refreshValidation();
}

async function calculateScenario() {
  if (!state.validation?.ready || state.loading) return;
  state.loading = true;
  renderBudgetAndValidation();
  try {
    state.report = await api('/api/analyze', { selections: state.selections });
    renderResults();
    window.setTimeout(() => $('#results-panel').scrollIntoView({ behavior: 'smooth', block: 'start' }), 40);
  } catch (error) {
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

function resetScenario() {
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

function bindEvents() {
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
  });

  $('#calculate-button').addEventListener('click', calculateScenario);
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
    renderHero();
    $('#workspace').hidden = false;
    render();
    await refreshValidation();
  } catch (error) {
    $('#app-error').hidden = false;
    $('#app-error-message').textContent = error.message || 'Проверьте, что сервер запущен, и обновите страницу.';
  }
}

init();
