(function () {
  'use strict';

  // Keep all report and team text in HTML text nodes; the exported document has no scripts.
  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/([\uD800-\uDBFF])([\uDC00-\uDFFF])|[\uD800-\uDFFF]|\u0000/g, (match, high, low) => high ? high + low : '\uFFFD')
      .replace(/[&<>"']/g, (character) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
      })[character]);
  }

  function numberOrNull(value) {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatNumber(value, digits = 0) {
    const number = numberOrNull(value);
    return number === null ? '—' : number.toFixed(digits).replace('.', ',');
  }

  function formatSigned(value, digits = 2) {
    const number = numberOrNull(value);
    if (number === null) return '—';
    const rounded = Number(number.toFixed(digits));
    return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${formatNumber(Math.abs(rounded), digits)}`;
  }

  function listOrFallback(value, fallback) {
    const items = Array.isArray(value) ? value : typeof value === 'string' ? [value] : [];
    const nonempty = items.filter((item) => typeof item === 'string' && item.trim());
    return (nonempty.length ? nonempty : fallback).slice(0, 3);
  }

  function renderList(items) {
    return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
  }

  window.buildPresentationHtml = function buildPresentationHtml(report, teamName = '') {
    const data = report && typeof report === 'object' ? report : {};
    const explanation = data.explanation && typeof data.explanation === 'object' ? data.explanation : {};
    const measures = Array.isArray(data.selected_measures) ? data.selected_measures.slice(0, 5) : [];
    const districts = Array.isArray(data.districts) ? data.districts : [];
    const critical = Array.isArray(data.critical_indicators) ? data.critical_indicators : [];
    const synergies = Array.isArray(data.applied_synergies) ? data.applied_synergies : [];
    const score = numberOrNull(data.score);
    const baseline = numberOrNull(data.baseline_score);
    const delta = numberOrNull(data.display_score_delta)
      ?? (score !== null && baseline !== null ? Number(score.toFixed(2)) - Number(baseline.toFixed(2)) : null);
    const spent = numberOrNull(data.total_cost);
    const budget = numberOrNull(data.budget);
    const remaining = numberOrNull(data.budget_remaining) ?? (spent !== null && budget !== null ? budget - spent : null);
    const spentPercent = spent !== null && budget !== null && budget > 0
      ? Math.max(0, Math.min(100, spent / budget * 100)) : 0;
    const team = String(teamName ?? '').trim();

    const choicesHtml = measures.length ? measures.map((measure, index) => {
      const location = measure.type === 'city' ? 'Весь город' : measure.district_name || 'Район не указан';
      return `<li class="choice">
        <span class="choice-number">${String(index + 1).padStart(2, '0')}</span>
        <div class="choice-copy"><strong>${escapeHtml(measure.name)}</strong><span>${escapeHtml(measure.direction_label || 'Мероприятие')} · ${escapeHtml(location)}</span></div>
        <span class="choice-cost">${formatNumber(measure.cost)} ед.</span>
      </li>`;
    }).join('') : '<li class="empty">Выбранные мероприятия отсутствуют.</li>';

    const districtRows = districts.length ? districts.map((district) => {
      const districtDelta = numberOrNull(district.score_delta)
        ?? (numberOrNull(district.score_after) !== null && numberOrNull(district.score_before) !== null
          ? Number(district.score_after) - Number(district.score_before) : null);
      const weakest = district.id === data.weakest_district_id;
      return `<tr${weakest ? ' class="weakest-row"' : ''}>
        <th scope="row">${escapeHtml(district.name)}${weakest ? ' <span class="focus-tag">Фокус</span>' : ''}</th>
        <td>${formatNumber(district.score_before, 2)}</td>
        <td><strong>${formatNumber(district.score_after, 2)}</strong></td>
        <td class="${districtDelta !== null && districtDelta < 0 ? 'negative' : 'positive'}">${formatSigned(districtDelta)}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="4">Данные о районах отсутствуют.</td></tr>';

    const changes = (Array.isArray(data.indicator_changes) ? [...data.indicator_changes] : districts.flatMap((district) =>
      (Array.isArray(district.indicators) ? district.indicators : []).map((indicator) => ({
        ...indicator, district_name: district.name,
      }))
    )).filter((item) => item && numberOrNull(item.delta) !== null && Math.abs(Number(item.delta)) > 0.000001)
      .sort((a, b) => Math.abs(Number(b.delta)) - Math.abs(Number(a.delta)))
      .slice(0, 4);
    const changesHtml = changes.length ? changes.map((item) => `<li class="change-card">
      <div><strong>${escapeHtml(item.label || item.id)}</strong><span>${escapeHtml(item.district_name || 'Район не указан')}</span></div>
      <div class="change-values"><span>${formatNumber(item.before, 1)} → ${formatNumber(item.after, 1)}</span>
        <strong class="${Number(item.delta) < 0 ? 'negative' : 'positive'}">${formatSigned(item.delta, 1)}</strong></div>
    </li>`).join('') : '<li class="empty">Изменений показателей нет.</li>';

    const strongestChange = changes.find((item) => Number(item.delta) > 0);
    const defaultStrengths = [
      delta !== null && delta > 0
        ? `Итоговый Score вырос на ${formatSigned(delta)} балла относительно исходного.`
        : `Итоговый Score составляет ${formatNumber(score, 2)} из 100.`,
      strongestChange
        ? `Вырос показатель «${strongestChange.label || strongestChange.id}» в районе ${strongestChange.district_name}: ${formatSigned(strongestChange.delta, 1)} пункта.`
        : 'Районные показатели отражают рассчитанный эффект выбранных мер.',
    ];
    const defaultRisks = [
      critical.length
        ? `После мер остаётся ${formatNumber(data.critical_count ?? critical.length)} показателей ниже порога 40.`
        : 'После мер показателей ниже критического порога 40 не осталось.',
      remaining !== null && remaining > 0
        ? `Остаток бюджета — ${formatNumber(remaining)} ед.; он не прибавляет баллы к Score.`
        : 'Сравните влияние мер на самый слабый район и другие районы.',
    ];
    const summary = typeof explanation.summary === 'string' && explanation.summary.trim()
      ? explanation.summary
      : `Итоговый Score — ${formatNumber(score, 2)} из 100 (${formatSigned(delta)} к исходным ${formatNumber(baseline, 2)}).`;
    const strengths = listOrFallback(explanation.strengths, defaultStrengths);
    const risks = listOrFallback(explanation.risks, defaultRisks);
    const recommendations = listOrFallback(explanation.recommendations, [
      'Сравните другие сочетания мер и направьте внимание на самый слабый район, затем пересчитайте сценарий.',
    ]);

    const criticalExamples = critical.slice(0, 2).map((item) =>
      `${item.indicator_label || item.indicator_id} — ${item.district_name || 'район не указан'} (${formatNumber(item.value, 1)})`
    ).join('; ');
    const consequenceItems = [
      `Самый слабый район после изменений: ${data.weakest_district_name || 'не указан'}.`,
      critical.length
        ? `Критических показателей (ниже 40): ${formatNumber(data.critical_count ?? critical.length)}. ${criticalExamples}${critical.length > 2 ? ' и другие.' : '.'}`
        : `Критических показателей (ниже 40): ${formatNumber(data.critical_count ?? 0)}.`,
      synergies.length
        ? `Синергия мер: ${synergies.slice(0, 2).map((item) => `${Array.isArray(item.measures) ? item.measures.join(' + ') : 'меры'} — ${item.description || 'дополнительный эффект'}`).join('; ')}${synergies.length > 2 ? ' и другие.' : '.'}`
        : 'Дополнительная синергия выбранных мер не сработала.',
    ];

    return `<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Пять решений — презентация сценария</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #1b342e; background: #e9eee6; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 28px 16px 44px; }
    button { font: inherit; }
    .toolbar { max-width: 1120px; margin: 0 auto 18px; display: flex; justify-content: space-between; align-items: center; gap: 16px; color: #43584d; font-size: 14px; }
    .print-button { border: 0; border-radius: 12px; background: #1b342e; color: white; padding: 12px 18px; font-weight: 700; cursor: pointer; }
    .print-button:hover, .print-button:focus-visible { background: #315c48; }
    .print-button:focus-visible { outline: 3px solid #93b871; outline-offset: 3px; }
    .deck { max-width: 1120px; margin: auto; display: grid; gap: 22px; }
    .slide { min-width: 0; min-height: 650px; background: #fcfdf9; border-radius: 24px; padding: 42px 48px 34px; box-shadow: 0 14px 45px #17302718; display: flex; flex-direction: column; gap: 20px; overflow-wrap: anywhere; }
    .slide-top, .slide-bottom { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .slide-top { border-bottom: 1px solid #dce5da; padding-bottom: 14px; }
    .eyebrow, .page-number, .kicker { text-transform: uppercase; letter-spacing: .13em; font-size: 11px; font-weight: 800; }
    .eyebrow { margin: 0; color: #41725c; }
    .page-number { color: #718478; white-space: nowrap; }
    .slide-bottom { margin-top: auto; padding-top: 12px; border-top: 1px solid #dce5da; color: #65766a; font-size: 12px; }
    h1, h2, h3, p { margin: 0; }
    h1, h2 { letter-spacing: -.045em; line-height: 1.08; }
    h1 { font-size: clamp(34px, 5vw, 56px); }
    h1 em { font-style: normal; color: #538166; }
    h2 { font-size: clamp(30px, 4vw, 44px); }
    h3 { font-size: 17px; letter-spacing: -.02em; }
    .intro-header { display: flex; justify-content: space-between; align-items: end; gap: 24px; }
    .subtitle { color: #647569; font-size: 15px; line-height: 1.45; margin-top: 8px; }
    .team { align-self: start; max-width: 42%; padding: 10px 14px; border-radius: 10px; background: #eaf0e3; color: #32513c; font-size: 13px; }
    .team strong { display: block; font-size: 16px; }
    .hero-stats { display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; }
    .score-card, .budget-card { border-radius: 18px; padding: 22px 25px; }
    .score-card { background: #1b342e; color: white; }
    .budget-card { background: #edf2e8; }
    .kicker { color: #779d83; }
    .budget-card .kicker { color: #557664; }
    .big-score { display: flex; align-items: baseline; gap: 8px; margin: 5px 0 8px; }
    .big-score strong { font-size: 56px; line-height: 1; letter-spacing: -.07em; }
    .big-score span, .score-meta, .budget-meta { color: #c8d8ca; font-size: 13px; }
    .score-meta { display: flex; flex-wrap: wrap; gap: 7px 14px; }
    .score-meta strong { color: #d9f17d; font-weight: 700; }
    .budget-amount { display: flex; align-items: baseline; gap: 8px; margin: 12px 0; }
    .budget-amount strong { font-size: 39px; letter-spacing: -.06em; }
    .budget-amount span, .budget-meta { color: #567063; }
    .budget-track { height: 9px; border-radius: 20px; background: #d5e2d3; overflow: hidden; margin-bottom: 12px; }
    .budget-track span { display: block; height: 100%; background: #4c8063; border-radius: inherit; }
    .budget-meta { color: #3e5948; }
    .section-heading { display: flex; justify-content: space-between; align-items: baseline; gap: 14px; }
    .section-heading p { color: #718478; font-size: 13px; }
    .choices, .changes { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .choice, .change-card { border: 1px solid #dce6da; border-radius: 12px; background: white; }
    .choice { display: flex; align-items: center; gap: 12px; padding: 13px 14px; min-width: 0; }
    .choice:last-child:nth-child(odd) { grid-column: 1 / -1; }
    .choice-number { color: #74947d; font-size: 13px; font-weight: 800; }
    .choice-copy { display: grid; gap: 3px; min-width: 0; flex: 1; }
    .choice-copy strong { font-size: 14px; }
    .choice-copy span { font-size: 12px; color: #6a7c70; }
    .choice-cost { font-size: 12px; font-weight: 800; white-space: nowrap; }
    .district-table-wrap { overflow-x: auto; }
    .district-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 15px; }
    .district-table th, .district-table td { padding: 13px 12px; border-bottom: 1px solid #e1e9df; }
    .district-table thead th { color: #637b69; background: #edf2e8; font-size: 11px; text-transform: uppercase; letter-spacing: .09em; }
    .district-table th[scope="row"] { font-weight: 700; }
    .weakest-row { background: #f4f5e9; }
    .focus-tag { display: inline-block; margin-left: 5px; padding: 3px 6px; border-radius: 5px; background: #dbe7c9; color: #395c3c; font-size: 10px; text-transform: uppercase; vertical-align: middle; }
    .positive { color: #24704c; }
    .negative { color: #ac5044; }
    .changes { gap: 12px; }
    .change-card { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 16px; }
    .change-card > div { display: grid; gap: 5px; }
    .change-card strong { font-size: 14px; }
    .change-card span { color: #718478; font-size: 12px; }
    .change-values { text-align: right; white-space: nowrap; }
    .change-values strong { font-size: 20px; }
    .empty { grid-column: 1 / -1; color: #6b7d70; padding: 14px; }
    .summary { max-width: 90ch; line-height: 1.5; color: #40594a; font-size: 15px; white-space: pre-line; }
    .insights { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .insight-card { background: #edf2e8; border-radius: 16px; padding: 19px 21px; }
    .insight-card.risks { background: #f7f0e9; }
    .insight-card h3 { margin-bottom: 10px; }
    .insight-card ul, .consequences ul, .recommendations ul { margin: 0; padding-left: 19px; line-height: 1.42; font-size: 13px; }
    li + li { margin-top: 6px; }
    .consequences { border-top: 1px solid #dce5da; padding-top: 15px; }
    .consequences h3, .recommendations h3 { margin-bottom: 9px; }
    .recommendations { border-left: 4px solid #8cb76d; padding: 12px 18px; background: #f1f6e8; border-radius: 0 12px 12px 0; }
    .disclaimer { color: #566b5b; max-width: 84ch; line-height: 1.4; }
    @media (max-width: 680px) {
      body { padding: 12px 10px 28px; }
      .slide { min-height: 0; padding: 24px 20px; border-radius: 16px; gap: 18px; }
      .intro-header, .hero-stats, .insights, .choices, .changes { display: grid; grid-template-columns: 1fr; }
      .team { max-width: 100%; }
      .choice:last-child:nth-child(odd) { grid-column: auto; }
      .district-table { min-width: 450px; }
      .slide-bottom { align-items: start; }
    }
    @page { size: A4 landscape; margin: 10mm; }
    @media print {
      :root { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
      body { padding: 0; background: white; }
      .toolbar { display: none; }
      .deck { display: block; max-width: none; }
      .slide { height: 188mm; min-height: 0; margin: 0; padding: 7mm 9mm; border-radius: 0; box-shadow: none; gap: 13px; break-inside: avoid; page-break-inside: avoid; }
      .slide:not(:last-child) { break-after: page; page-break-after: always; }
      .slide-top { padding-bottom: 9px; }
      .slide-bottom { padding-top: 9px; }
      .big-score strong { font-size: 48px; }
      .score-card, .budget-card { padding: 16px 20px; }
      .choice { padding: 10px 12px; }
      .district-table th, .district-table td { padding: 10px 12px; }
      .change-card { padding: 11px 14px; }
      .insight-card { padding: 13px 17px; }
    }
  </style>
</head>
<body>
  <div class="toolbar"><span>Презентация сценария · 3 слайда</span><button class="print-button" type="button" onclick="window.print()">Печать / PDF</button></div>
  <main class="deck">
    <section class="slide" aria-labelledby="slide-one-title">
      <div class="slide-top"><p class="eyebrow">Городская лаборатория · План действий</p><span class="page-number">01 / 03</span></div>
      <header class="intro-header"><div><h1 id="slide-one-title">Пять решений.<br /><em>Один город.</em></h1><p class="subtitle">Результат вашего сценария развития города</p></div>${team ? `<p class="team">Команда <strong>${escapeHtml(team)}</strong></p>` : ''}</header>
      <div class="hero-stats">
        <div class="score-card"><p class="kicker">Astana Quality of Life Score</p><div class="big-score"><strong>${formatNumber(score, 2)}</strong><span>из 100</span></div><p class="score-meta"><span>Было ${formatNumber(baseline, 2)} → стало ${formatNumber(score, 2)}</span><strong>${formatSigned(delta)} к исходному</strong></p></div>
        <div class="budget-card"><p class="kicker">Использованный бюджет</p><div class="budget-amount"><strong>${formatNumber(spent)}</strong><span>/ ${formatNumber(budget)} ед.</span></div><div class="budget-track" aria-hidden="true"><span style="width: ${spentPercent}%"></span></div><p class="budget-meta">Осталось ${formatNumber(remaining)} условных единиц</p></div>
      </div>
      <div class="section-heading"><h3>Выбранные мероприятия</h3><p>${measures.length} из 5 решений</p></div>
      <ol class="choices">${choicesHtml}</ol>
      <div class="slide-bottom"><span>Модельный результат · Баллы по шкале 0–100</span><span>План / 01</span></div>
    </section>
    <section class="slide" aria-labelledby="slide-two-title">
      <div class="slide-top"><p class="eyebrow">Изменения по районам</p><span class="page-number">02 / 03</span></div>
      <header><h2 id="slide-two-title">Что изменилось в районах</h2><p class="subtitle">Сравнение районных баллов до и после выбранных мер</p></header>
      <div class="district-table-wrap"><table class="district-table"><thead><tr><th scope="col">Район</th><th scope="col">До</th><th scope="col">После</th><th scope="col">Изменение</th></tr></thead><tbody>${districtRows}</tbody></table></div>
      <div class="section-heading"><h3>Самые заметные изменения показателей</h3><p>Пункты по шкале 0–100</p></div>
      <ul class="changes">${changesHtml}</ul>
      <div class="slide-bottom"><span>Баллы районов и показатели рассчитаны одной моделью</span><span>Эффект / 02</span></div>
    </section>
    <section class="slide" aria-labelledby="slide-three-title">
      <div class="slide-top"><p class="eyebrow">Выводы сценария</p><span class="page-number">03 / 03</span></div>
      <header><h2 id="slide-three-title">Что означает результат</h2><p class="subtitle">Сильные стороны, риски и следующие шаги</p></header>
      <p class="summary">${escapeHtml(summary)}</p>
      <div class="insights"><section class="insight-card" aria-labelledby="strengths-title"><h3 id="strengths-title">Сильные стороны</h3>${renderList(strengths)}</section><section class="insight-card risks" aria-labelledby="risks-title"><h3 id="risks-title">Риски и компромиссы</h3>${renderList(risks)}</section></div>
      <section class="consequences" aria-labelledby="consequences-title"><h3 id="consequences-title">Последствия выбранных мер</h3>${renderList(consequenceItems)}</section>
      <section class="recommendations" aria-labelledby="recommendations-title"><h3 id="recommendations-title">Рекомендации для следующего сценария</h3>${renderList(recommendations)}</section>
      <div class="slide-bottom"><span class="disclaimer">Все данные, показатели и эффекты мер синтетические. Это демонстрационный модельный сценарий, а не официальный прогноз города.</span><span>Выводы / 03</span></div>
    </section>
  </main>
</body>
</html>`;
  };
})();
