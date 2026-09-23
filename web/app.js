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
  teamTokens: {},
  leaderboardLoading: false,
};

const STORAGE_KEY = 'akim-simulator-selections-v1';
const TEAM_TOKENS_KEY = 'akim-simulator-team-tokens-v1';
const TEAM_NAME_KEY = 'akim-simulator-team-name-v1';
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
    const message = (data.errors || []).join(' ') || (typeof data.detail === 'string' ? data.detail : '') || 'Запрос не выполнен.';
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
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) state.teamTokens = saved;
    $('#team-name').value = localStorage.getItem(TEAM_NAME_KEY) || '';
  } catch {
    state.teamTokens = {};
  }
}

function teamKey(name) {
  return name.trim().replace(/\s+/g, ' ').toLowerCase();
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
    const effects = Object.entries(measure.realised_effects || measure.effects).map(([id, amount]) => {
      const indicator = state.config.indicators.find((item) => item.id === id);
      const displayedAmount = Number(amount.toFixed(2));
      return `<span class="impact-chip ${amount < 0 ? 'negative' : ''}" title="${escapeHtml(indicator?.label || id)}: эффект за 8 кварталов с учётом лага">${escapeHtml(id)} ${displayedAmount > 0 ? '+' : ''}${displayedAmount}</span>`;
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
  $('#mobile-dock-summary').textContent = `${state.selections.length} из ${state.config.required_selections} · ${totalCost} / ${state.config.budget} ед.`;
  const mobileCalculate = $('#mobile-calculate-button');
  mobileCalculate.disabled = state.loading || (!validation.ready && !state.report);
  mobileCalculate.innerHTML = `${state.loading ? 'Считаем…' : state.report ? 'К результату' : 'Рассчитать'} <span aria-hidden="true">↗</span>`;
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

  $('#explanation-summary').textContent = explanation.summary;
  const sourceBadge = $('#explanation-source');
  sourceBadge.textContent = explanation.source === 'openai' ? 'ИИ-РАЗБОР' : 'ПО ДАННЫМ МОДЕЛИ';
  sourceBadge.classList.toggle('ai-source', explanation.source === 'openai');
  $('#explanation-strengths').innerHTML = explanation.strengths.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  $('#explanation-risks').innerHTML = explanation.risks.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  const consequences = explanation.consequences || [];
  $('#explanation-consequences-wrap').hidden = consequences.length === 0;
  $('#explanation-consequences').innerHTML = consequences.map((item) => `<li>${escapeHtml(item)}</li>`).join('');
  const recommendations = explanation.recommendations || [];
  $('#explanation-recommendations-wrap').hidden = recommendations.length === 0;
  $('#explanation-recommendations').textContent = recommendations.join(' ');
  $('#explanation-note').hidden = !explanation.note;
  $('#explanation-note').textContent = explanation.note || '';

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
      return `<tr title="${escapeHtml(contributionTitle)}" class="${indicator.after < 40 ? 'critical-indicator-row' : ''}"><td><strong>${escapeHtml(indicator.label)}</strong> <span class="indicator-id">${escapeHtml(indicator.id)}</span>${indicator.after < 40 ? ' <span class="critical-chip">НИЖЕ 40</span>' : ''}</td><td>${Number(indicator.before).toFixed(1)}</td><td>${Number(indicator.after).toFixed(1)}</td><td class="${deltaClass}">${signed(indicator.delta, 1)}</td></tr>`;
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
  if (!state.report) return;
  const input = $('#team-name');
  const name = input.value.trim().replace(/\s+/g, ' ');
  if (!name || name.length > 40) {
    showToast('Название команды должно содержать от 1 до 40 символов.');
    input.focus();
    return;
  }
  const codeInput = $('#team-code');
  const ownerToken = codeInput.value.trim() || state.teamTokens[teamKey(name)] || null;
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
      codeInput.value = token;
    }
    try {
      localStorage.setItem(TEAM_NAME_KEY, name);
    } catch {
      // The team name remains visible in the form for this session.
    }
    $('#team-save-status').textContent = `План «${name}» сохранён. ${result.entry.owner_token ? 'Код команды показан выше: сохраните его для обновления с другого устройства.' : 'Ваш результат обновлён.'}`;
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

async function useTeamPlan(index) {
  const entry = state.leaderboard[index];
  if (!entry) return;
  state.selections = entry.selections.map((choice) => ({
    measure_id: choice.measure_id,
    district_id: choice.district_id ?? null,
  }));
  state.selectionsVersion++;
  state.report = null;
  state.validation = null;
  saveSelections();
  render();
  await refreshValidation();
  showToast(`План «${entry.team_name}» загружен. Рассчитайте его или измените решения.`);
  $('#catalog-title').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function render() {
  renderSelections();
  renderFilters();
  renderCatalog();
  renderBudgetAndValidation();
  renderResults();
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
  const version = state.selectionsVersion;
  const selections = state.selections.map((choice) => ({ ...choice }));
  state.loading = true;
  renderBudgetAndValidation();
  try {
    const report = await api('/api/analyze', { selections });
    if (version !== state.selectionsVersion) return;
    state.report = report;
    renderResults();
    renderLeaderboard();
    window.setTimeout(() => {
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
  state.selections = alternative.selections.map((choice) => ({
    measure_id: choice.measure_id,
    district_id: choice.district_id ?? null,
  }));
  state.validationRequest++;
  state.selectionsVersion++;
  state.report = null;
  state.validation = null;
  saveSelections();
  render();
  await refreshValidation();
  showToast('План обновлён. Рассчитайте его, чтобы увидеть итог и новые варианты.');
  $('#catalog-title').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function resetScenario() {
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
  $('#mobile-calculate-button').addEventListener('click', () => {
    if (state.report) {
      $('#results-title').focus({ preventScroll: true });
      $('#results-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      calculateScenario();
    }
  });
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
    if (window.matchMedia('(max-width: 760px)').matches) {
      $('#budget-directions').open = false;
      $('#rules-details').open = false;
    }
    renderHero();
    $('#workspace').hidden = false;
    $('#comparison-board').hidden = false;
    $('#mobile-dock').hidden = false;
    render();
    await refreshValidation();
    await refreshLeaderboard();
  } catch (error) {
    $('#app-error').hidden = false;
    $('#app-error-message').textContent = error.message || 'Проверьте, что сервер запущен, и обновите страницу.';
  }
}

init();
