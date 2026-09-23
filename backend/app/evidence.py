"""Canonical, engine-grounded statements. A provider may select, never rewrite them."""

from __future__ import annotations

from typing import Any

from .engine import DISTRICTS, INDICATORS, MEASURES, simulate
from .recommender import recommend_alternatives

SECTIONS = ("summary", "strengths", "risks", "consequences", "recommendations")
EPSILON = 1e-9


def _number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def _signed(value: float) -> str:
    return ("+" if value > 0 else "") + _number(value)


def _indicator_name(item: dict[str, Any]) -> str:
    return f"«{item['label']}» в районе {item['district_name']}"


def _indicator_details(item: dict[str, Any]) -> list[str]:
    return [
        (
            f"Расчёт {item['district_id']}/{item['id']}: {_number(item['before'])} → "
            f"{_number(item['after'])}; изменение {_signed(item['delta'])} пункта по шкале 0–100."
        ),
        *[
            f"Источник: {source['source_id']} «{source['source_name']}», "
            f"вклад {_signed(source['amount'])} пункта до ограничения шкалы 0–100."
            for source in item['contributions']
        ],
    ]


def _choice_key(choice: dict[str, Any]) -> tuple[str, str | None]:
    return choice["measure_id"], choice.get("district_id")


def _place(choice: tuple[str, str | None]) -> str:
    measure_id, district_id = choice
    location = DISTRICTS[district_id]["name"] if district_id else "весь город"
    return f"«{MEASURES[measure_id]['name']}» ({location})"


def _verified_alternatives(
    report: dict[str, Any], alternatives: list[dict[str, Any]] | None
) -> list[tuple[dict[str, Any], str]]:
    """Recompute scores and replacement names; supplied prose/numbers are not evidence."""
    current = [
        {"measure_id": item["id"], "district_id": item["district_id"]}
        for item in report["selected_measures"]
    ]
    current_keys = {_choice_key(choice) for choice in current}

    def checked(items: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
        result = []
        seen = set()
        for item in items:
            try:
                choices = item["selections"]
                candidate = simulate(choices)
                keys = frozenset(_choice_key(choice) for choice in choices)
            except (KeyError, TypeError, ValueError):
                continue
            removed, added = current_keys - keys, keys - current_keys
            if len(removed) != 1 or len(added) != 1 or keys in seen:
                continue
            # Match the recommender's visible-improvement contract, using fresh scores.
            if candidate["score"] <= report["score"] or round(candidate["score"], 2) <= round(report["score"], 2):
                continue
            seen.add(keys)
            description = f"Заменить {_place(next(iter(removed)))} на {_place(next(iter(added)))}"
            result.append((candidate, description))
        return sorted(result, key=lambda pair: (-pair[0]["score"], pair[0]["total_cost"], pair[1]))[:3]

    verified = checked(alternatives or [])
    if not verified:
        # An empty caller list is not proof that no improving replacement exists.
        search = recommend_alternatives(current, current_report=report)
        verified = checked(search["alternatives"])
    return verified


def build_fact_catalog(
    report: dict[str, Any], alternatives: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Keep a small set of material changes, remaining weaknesses and verified options."""
    facts: list[dict[str, Any]] = []

    def add(fact_id: str, text: str, details: list[str], *sections: str) -> None:
        facts.append({"id": fact_id, "text": text, "details": details, "allowed_sections": list(sections)})

    add(
        "scenario",
        f"Сценарий набрал {report['score']:.2f} из 100 — "
        f"{report['display_score_delta']:+.2f} к базовым {report['baseline_score']:.2f}. "
        f"Потрачено {report['total_cost']} из {report['budget']} условных единиц.",
        [
            f"Источник: локальная расчётная модель {report['model_version']}; все данные синтетические.",
            (
                f"Score: {_number(report['baseline_score'])} → {_number(report['score'])}; "
                f"точное изменение {_signed(report['score_delta'])}; в тексте разность округлённых оценок."
            ),
            f"Бюджет: {report['total_cost']} + остаток {report['budget_remaining']} = {report['budget']}.",
        ],
        "summary",
    )
    add(
        "budget",
        f"Остаток бюджета — {report['budget_remaining']} из {report['budget']} единиц; "
        "он не добавляет баллы к Score.",
        ["Score = 0,7 × средняя оценка + 0,3 × минимальная оценка района − число показателей ниже 40.",
         f"В формуле нет слагаемого за остаток бюджета; потрачено {report['total_cost']} единиц."],
        "risks", "consequences",
    )
    city_delta = report["city_average"] - report["baseline_city_average"]
    add(
        "city.average",
        f"Средняя оценка города с учётом населения: {report['baseline_city_average']:.2f} → "
        f"{report['city_average']:.2f} балла.",
        [
            f"Точное изменение средневзвешенной оценки: {_signed(city_delta)}.",
            *[f"{district['name']}: вес населения {_number(100 * district['population_share'])}%; "
              f"оценка {_number(district['score_before'])} → {_number(district['score_after'])}."
              for district in report["districts"]],
        ],
        "summary", "consequences", *(["strengths"] if city_delta > 0 else []),
    )

    indicators = [
        {**item, "district_id": district["id"], "district_name": district["name"]}
        for district in report["districts"] for item in district["indicators"]
    ]
    positive = sorted((item for item in indicators if item["delta"] > 0), key=lambda item: -item["delta"])
    for item in positive[:3]:
        add(
            f"gain.{item['district_id']}.{item['id']}",
            f"Показатель {_indicator_name(item)} вырос: {_number(item['before'])} → {_number(item['after'])} "
            f"({_signed(item['delta'])} пункта).",
            _indicator_details(item), "strengths", "consequences",
        )
    if not positive:
        add("gains.none", "В этом расчёте нет показателей с положительным изменением.",
            [f"Проверены изменения всех {len(indicators)} показателей районов; ни одно не больше нуля."],
            "strengths", "consequences")

    best_delta = max(district["score_delta"] for district in report["districts"])
    if best_delta > 0:
        best = [district for district in report["districts"] if abs(district["score_delta"] - best_delta) < EPSILON]
        names = ", ".join(district["name"] for district in best)
        add(
            "district.most_improved",
            f"Наибольший прирост оценки района: {names} ({_signed(best_delta)} балла)"
            + ("; прирост одинаков у нескольких районов." if len(best) > 1 else "."),
            [f"{district['name']}: {_number(district['score_before'])} → {_number(district['score_after'])}; "
             f"изменение {_signed(district['score_delta'])}." for district in report["districts"]],
            "strengths", "consequences",
        )

    before_min = min(district["score_before"] for district in report["districts"])
    after_min = min(district["score_after"] for district in report["districts"])
    weakest = [district for district in report["districts"] if abs(district["score_after"] - after_min) < EPSILON]
    weakest_text = []
    for district in weakest:
        change = (f"не меняется ({district['score_after']:.2f} балла)" if abs(district["score_delta"]) < EPSILON
                  else f"меняется с {district['score_before']:.2f} до {district['score_after']:.2f} балла")
        status = "остаётся" if abs(district["score_before"] - before_min) < EPSILON else "становится"
        rank = "слабейшим" if len(weakest) == 1 else "одним из слабейших"
        weakest_text.append(f"К концу модельного горизонта оценка района {district['name']} {change}. "
                            f"Район {status} {rank} по качеству жизни.")
    add("district.weakest", " ".join(weakest_text),
        [f"{district['name']}: оценка {_number(district['score_before'])} → {_number(district['score_after'])}."
         for district in report["districts"]], "risks", "consequences")

    critical = sorted(report["critical_indicators"], key=lambda item: item["value"])
    baseline_critical_count = sum(item["before"] < 40 for item in indicators)
    critical_details = [f"{item['district_name']}, «{item['indicator_label']}»: {_number(item['value'])} < 40."
                        for item in critical]
    add(
        "critical",
        (f"После выбранных мер {len(critical)} показателей ниже порога 40; "
         f"их штраф в Score — {len(critical)} балла. Примеры: "
         + ", ".join(f"«{item['indicator_label']}» — {item['district_name']} ({_number(item['value'])})"
                     for item in critical[:3]) + ".") if critical
        else "После выбранных мер ни один показатель не остаётся ниже порога 40; штраф за критические показатели равен нулю.",
        critical_details + [
            f"Проверены {len(indicators)} показателей; критический порог строго < 40, штраф −1 за каждый.",
            (f"Число критических показателей: {baseline_critical_count} → {len(critical)}; "
             f"изменение штрафного слагаемого Score: {_signed(baseline_critical_count - len(critical))}."),
        ],
        "risks", "consequences",
    )

    lowest = sorted(indicators, key=lambda item: item["after"])[:3]
    add("indicators.lowest", "Наиболее низкие итоговые показатели: " + "; ".join(
        f"{_indicator_name(item)} — {_number(item['after'])}" for item in lowest) + ".",
        [detail for item in lowest for detail in _indicator_details(item)], "risks")
    unchanged = sorted((item for item in indicators if item["delta"] == 0), key=lambda item: item["after"])[:3]
    if unchanged:
        add("indicators.unchanged", "Среди показателей без изменений самые низкие: " + "; ".join(
            f"{_indicator_name(item)} — {_number(item['after'])}" for item in unchanged) + ".",
            [detail for item in unchanged for detail in _indicator_details(item)], "risks", "consequences")
    negative = sorted((item for item in indicators if item["delta"] < 0), key=lambda item: item["delta"])[:3]
    if negative:
        add("indicators.decreased", "Снижение относительно исходного города: " + "; ".join(
            f"{_indicator_name(item)} — {_number(item['before'])} → {_number(item['after'])} "
            f"({_signed(item['delta'])})" for item in negative) + ".",
            [detail for item in negative for detail in _indicator_details(item)], "risks", "consequences")

    negative_effects = [effect for effect in report["applied_effects"] if effect["realised_effect"] < 0]
    if negative_effects:
        add("effects.negative", "Отдельные меры имеют отрицательный вклад в показатели до ограничения шкалы: " + "; ".join(
            f"«{effect['source_name']}» — «{INDICATORS[effect['indicator_id']]['label']}» "
            f"в районе {DISTRICTS[effect['district_id']]['name']} ({_signed(effect['realised_effect'])} пункта)"
            for effect in negative_effects) + ". Итоговое изменение учитывает также остальные меры.",
            [f"{effect['source_id']}: полный эффект {_signed(effect['full_effect'])} × "
             f"реализованная доля {_number(effect['lag_share'])} = {_signed(effect['realised_effect'])}."
             for effect in negative_effects], "risks", "consequences")

    for synergy in report["applied_synergies"]:
        names = " + ".join(f"«{MEASURES[measure_id]['name']}»" for measure_id in synergy["measures"])
        location = DISTRICTS[synergy["district_id"]]["name"] if synergy["district_id"] else "все районы"
        add(
            "synergy." + ".".join(synergy["measures"]),
            f"Сработала синергия {names}: {_signed(synergy['amount'])} пункта к показателю "
            f"«{INDICATORS[synergy['indicator_id']]['label']}» ({location}) до ограничения шкалы 0–100.",
            [(f"Источник: правило синергии {' + '.join(synergy['measures'])}; "
              f"обе меры выбраны, бонус {_signed(synergy['amount'])} добавлен расчётным ядром."),
             "Это вклад в показатель, а не отдельный аддитивный вклад в Score."],
            "strengths", "consequences",
        )

    for measure in report["selected_measures"]:
        if measure["type"] != "city":
            continue
        effects = [effect for effect in report["applied_effects"] if effect["source_id"] == measure["id"]]
        unique_effects = {effect["indicator_id"]: effect["realised_effect"] for effect in effects}
        add(
            f"city.{measure['id']}",
            f"Городская мера «{measure['name']}» даёт во всех районах вклад до ограничения шкалы: "
            + "; ".join(f"«{INDICATORS[indicator_id]['label']}» {_signed(amount)} пункта"
                        for indicator_id, amount in unique_effects.items()) + ".",
            [f"{measure['id']}, {DISTRICTS[effect['district_id']]['name']}, {effect['indicator_id']}: "
             f"{_signed(effect['full_effect'])} × {_number(effect['lag_share'])} = {_signed(effect['realised_effect'])}."
             for effect in effects], "strengths", "consequences",
        )

    delayed = sorted((measure for measure in report["selected_measures"] if measure["lag"] > 0),
                     key=lambda item: (-item["lag"], item["id"]))
    if delayed:
        horizon = report["horizon_quarters"]
        # City effects repeat for each district; show each measure/indicator once.
        delayed_ids = {measure["id"] for measure in delayed}
        lag_effects = {
            (effect["source_id"], effect["indicator_id"]): effect
            for effect in report["applied_effects"] if effect["source_id"] in delayed_ids
        }
        add(
            "effects.lag",
            f"На горизонте {horizon} кварталов лаг уже учтён в реализованной доле эффекта: "
            + "; ".join(f"«{measure['name']}» — {_number(100 * (horizon - measure['lag']) / horizon)}%"
                        for measure in delayed[:3]) + ". Это доля эффекта в расчёте, не вероятность и не прогноз.",
            [f"{measure['id']} «{measure['name']}»: лаг {measure['lag']} кварт.; "
             f"({horizon} − {measure['lag']}) / {horizon} = {_number((horizon - measure['lag']) / horizon)}."
             for measure in delayed]
            + [f"{effect['source_id']}, {INDICATORS[effect['indicator_id']]['label']}: "
               f"полный эффект {_signed(effect['full_effect'])} × {_number(effect['lag_share'])} = "
               f"{_signed(effect['realised_effect'])} пункта до ограничения шкалы."
               for effect in lag_effects.values()],
            "risks", "consequences",
        )

    verified = _verified_alternatives(report, alternatives)
    for index, (candidate, description) in enumerate(verified, start=1):
        current_values = {(item["district_id"], item["id"]): item["after"] for item in indicators}
        differences = [
            {"label": item["label"], "district_name": district["name"],
             "before": current_values[(district["id"], item["id"])], "after": item["after"],
             "delta": item["after"] - current_values[(district["id"], item["id"])]}
            for district in candidate["districts"] for item in district["indicators"]
            if item["after"] != current_values[(district["id"], item["id"])]]
        gains = sorted((item for item in differences if item["delta"] > 0), key=lambda item: -item["delta"])
        losses = sorted((item for item in differences if item["delta"] < 0), key=lambda item: item["delta"])
        comparison = []
        for label, items in (("Наибольший выигрыш", gains), ("Наибольшая потеря", losses)):
            if items:
                item = items[0]
                comparison.append(f"{label} относительно текущего плана: {_indicator_name(item)} — "
                                  f"{_number(item['before'])} → {_number(item['after'])} ({_signed(item['delta'])}).")
        if not losses:
            comparison.append("Снижения показателей относительно текущего плана нет.")
        add(
            f"alternative.{index}",
            f"Проверенный вариант: {description}. Score {candidate['score']:.2f} "
            f"({round(round(candidate['score'], 2) - round(report['score'], 2), 2):+.2f} к текущему плану). "
            + " ".join(comparison) + " Вариант не применён.",
            [f"Источник: повторная локальная симуляция допустимой одиночной замены, модель {report['model_version']}.",
             (f"Score текущего плана {_number(report['score'])} → {_number(candidate['score'])}; "
              f"точное изменение {_signed(candidate['score'] - report['score'])}."),
             f"Стоимость {report['total_cost']} → {candidate['total_cost']}; бюджет {report['budget']}.",
             f"Критические показатели: {report['critical_count']} → {candidate['critical_count']}.",
             "Все сравнения ниже — с текущим планом, не с исходным городом.",
             *[f"{_indicator_name(item)}: {_number(item['before'])} → {_number(item['after'])}; "
               f"{_signed(item['delta'])} пункта." for item in differences]],
            "recommendations",
        )
    if not verified:
        add("alternatives.none", "Среди допустимых одиночных замен улучшения Score при отображении до сотых не найдено.",
            ["Источник: локальный перебор одиночных замен и переносов с проверкой бюджета и совместимости.",
             f"Текущий Score {report['score']:.2f}; допустимых вариантов с большей округлённой оценкой нет."],
            "recommendations")
    return facts


def fallback_selection(catalog: list[dict[str, Any]], *, critical_count: int) -> dict[str, list[str]]:
    """Prioritize changes and unresolved limitations, rather than generic budget prose."""
    by_id = {fact["id"]: fact for fact in catalog}
    preferred = {
        "summary": ["scenario"],
        "strengths": [*[fact["id"] for fact in catalog if fact["id"].startswith("gain.")][:1],
                      *[fact["id"] for fact in catalog if fact["id"].startswith("synergy.")],
                      "district.most_improved", "city.average", "gains.none"],
        "risks": ["indicators.decreased" if "indicators.decreased" in by_id else "effects.negative",
                  "indicators.unchanged" if "indicators.unchanged" in by_id else "indicators.lowest", "effects.lag"],
        "consequences": ["district.weakest", "critical", *[fact["id"] for fact in catalog if fact["id"].startswith("city.M")]],
        "recommendations": ["alternative.1", "alternatives.none"],
    }
    # A remaining critical indicator is more important than a merely low one.
    if critical_count:
        preferred["risks"].insert(0, "critical")
    return {
        section: [
            fact_id for fact_id in preferred[section]
            if fact_id in by_id and section in by_id[fact_id]["allowed_sections"]
        ][:3]
        for section in SECTIONS
    }


def render_selection(selection: dict[str, list[str]], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {fact["id"]: fact for fact in catalog}
    evidence = {section: [{key: by_id[fact_id][key] for key in ("id", "text", "details")}
                          for fact_id in selection[section]] for section in SECTIONS}
    return {
        "summary": " ".join(fact["text"] for fact in evidence["summary"]),
        **{section: [fact["text"] for fact in evidence[section]] for section in SECTIONS[1:]},
        "evidence": evidence,
        "grounding": "verified_fact_selection",
    }
