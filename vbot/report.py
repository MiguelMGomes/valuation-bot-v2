"""Construction du rapport (indépendant de Discord) : chiffré, argumenté, sourcé."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .attribution import Attribution, Cause, describe_attribution
from .formatting import fmt_num, fmt_pct
from .models import CompanySnapshot
from .news import TaggedNews, format_news_for_llm, sanitize
from .valuation import MultipleAssessment, ValuationConfig, ValuationResult, Verdict

VERDICT_TITLES: dict[Verdict, tuple[str, str]] = {
    Verdict.UNDERVALUED: ("🟢", "Sous-évaluation apparente"),
    Verdict.OVERVALUED: ("🔴", "Surévaluation apparente"),
    Verdict.NEUTRAL: ("⚪", "Valorisation proche des références"),
    Verdict.INSUFFICIENT: ("🟠", "Données insuffisantes pour conclure"),
}

DISCLAIMER = (
    "Analyse automatisée à titre informatif. Ne constitue ni un conseil en investissement "
    "ni une recommandation personnalisée."
)

_MD_RE = re.compile(r"([*_~|>\\])")


def md_escape(text: str) -> str:
    return _MD_RE.sub(r"\\\1", text)


@dataclass(frozen=True)
class Report:
    symbol: str
    verdict: Verdict
    title: str
    summary: str
    method_note: str
    multiples_table: str
    arguments: tuple[str, ...]
    cause_label: str
    cause_detail: str
    news_lines: tuple[str, ...]
    vigilance: tuple[str, ...]
    facts: str
    news_for_llm: str
    as_of: datetime
    source: str = "Finnhub"
    ai_summary: str | None = None


def _table(assessments: tuple[MultipleAssessment, ...]) -> str:
    rows = [f"{'Multiple':<10}{'Actuel':>8}{'Hist.':>8}{'Pairs':>8}{'Écart':>9}"]
    for a in assessments:
        rows.append(
            f"{a.label:<10}{fmt_num(a.current):>8}{fmt_num(a.hist_median):>8}"
            f"{fmt_num(a.peer_median):>8}{fmt_pct(a.combined, 0):>9}"
        )
    return "\n".join(rows)


def _argument(a: MultipleAssessment) -> str:
    refs = []
    if a.vs_hist is not None:
        refs.append(f"{fmt_num(a.hist_median)} en médiane sur {a.hist_n} exercices ({fmt_pct(a.vs_hist)})")
    if a.vs_peers is not None:
        refs.append(f"{fmt_num(a.peer_median)} pour la médiane de {a.peer_n} pairs ({fmt_pct(a.vs_peers)})")
    return f"{a.label} de {fmt_num(a.current)}, contre " + " et ".join(refs) + "."


def _select_arguments(valuation: ValuationResult, limit: int = 3) -> list[MultipleAssessment]:
    used = list(valuation.used)
    if valuation.verdict is Verdict.UNDERVALUED:
        used.sort(key=lambda a: a.combined)  # type: ignore[arg-type, return-value]
    elif valuation.verdict is Verdict.OVERVALUED:
        used.sort(key=lambda a: a.combined, reverse=True)  # type: ignore[arg-type, return-value]
    else:
        used.sort(key=lambda a: abs(a.combined or 0), reverse=True)
    return used[:limit]


def _news_line(t: TaggedNews) -> str:
    date = t.item.published_at.strftime("%d/%m")
    headline = md_escape(sanitize(t.item.headline, 110).replace("[", "(").replace("]", ")"))
    source = md_escape(sanitize(t.item.source, 30))
    url = t.item.url
    safe_url = url.startswith("https://") and len(url) <= 200 and not re.search(r"[\s()<>]", url)
    text = f"[{headline}]({url})" if safe_url else headline
    warn = " ⚠️ contenu suspect, non exploité" if t.suspicious else ""
    return f"• {date} · {t.categories[0]} · {text} ({source}){warn}"


def _cause_detail(cause: Cause, attribution: Attribution, news: list[TaggedNews] | None, lookback: int) -> str:
    parts = [describe_attribution(attribution)]
    if news is None:
        parts.append("Flux d'actualités indisponible lors de l'analyse : la piste « actualité » n'a pas pu être vérifiée.")
    elif cause is Cause.NEWS:
        parts.append(f"{len(news)} actualité(s) spécifique(s) significative(s) sur {lookback} jours (détail ci-dessous).")
    elif cause is Cause.MARKET_NO_CATALYST:
        parts.append(
            f"Aucune actualité spécifique significative sur {lookback} jours : le mouvement pourrait relever "
            "de facteurs sectoriels, macroéconomiques ou de flux (hypothèse non vérifiée)."
        )
    elif news:
        parts.append(f"{len(news)} actualité(s) significative(s) relevée(s) sur {lookback} jours, à mettre en regard.")
    return " ".join(parts)


def build_report(
    snapshot: CompanySnapshot,
    valuation: ValuationResult,
    attribution: Attribution,
    cause: Cause,
    news: list[TaggedNews] | None,
    cfg: ValuationConfig,
    lookback_days: int,
    now: datetime,
    source: str = "n.d.",
) -> Report:
    icon, verdict_label = VERDICT_TITLES[valuation.verdict]
    name = md_escape(sanitize(snapshot.name, 80))
    industry = md_escape(sanitize(snapshot.industry, 60))
    n_used, n_total = len(valuation.used), len(valuation.assessments)

    summary = (
        f"**{name}** · {industry}\n"
        f"Cours : {fmt_num(snapshot.price, 2)} {snapshot.currency} ({fmt_pct(snapshot.change_1d)} sur la séance)\n"
        f"Score de valorisation : **{fmt_pct(valuation.score)}** · Confiance : **{valuation.confidence}** · "
        f"Multiples exploités : {n_used}/{n_total}"
    )
    method_note = (
        "Score = écart moyen pondéré des multiples par rapport à leur médiane historique et à la médiane "
        f"des pairs (négatif = décote). Seuils : {fmt_pct(cfg.undervalued_threshold, 0)} / "
        f"{fmt_pct(cfg.overvalued_threshold, 0)}."
    )

    arguments = [_argument(a) for a in _select_arguments(valuation)]
    if valuation.peg is not None:
        arguments.append(f"PEG (PER / croissance du BPA) ≈ {fmt_num(valuation.peg, 2)}.")

    vigilance = list(valuation.flags) + list(snapshot.notes)
    if valuation.verdict is Verdict.INSUFFICIENT:
        vigilance.append(
            f"Seulement {n_used} multiple(s) comparable(s) sur {n_total} (minimum requis : {cfg.min_metrics})."
        )
    if snapshot.price is None:
        vigilance.append("Cours indisponible (marché fermé, symbole non couvert ou donnée manquante).")

    news_lines = tuple(_news_line(t) for t in (news or [])[:3])
    news_for_llm = format_news_for_llm(news or [])

    facts_lines = [
        f"Société : {sanitize(snapshot.name, 80)} ({snapshot.symbol}), secteur {sanitize(snapshot.industry, 60)}",
        f"Verdict du moteur : {verdict_label}, score {fmt_pct(valuation.score)}, confiance {valuation.confidence}",
        "Multiples (actuel / médiane historique / médiane pairs / écart combiné) :",
    ]
    for a in valuation.assessments:
        facts_lines.append(
            f"- {a.label} : {fmt_num(a.current)} / {fmt_num(a.hist_median)} / {fmt_num(a.peer_median)} / {fmt_pct(a.combined)}"
        )
    facts_lines += [
        f"Décomposition 12 mois : cours {fmt_pct(attribution.price_return)}, BPA {fmt_pct(attribution.eps_growth)}, "
        f"PER {fmt_pct(attribution.pe_change)}",
        f"Cause retenue par le moteur : {cause.value}",
    ]
    if valuation.peg is not None:
        facts_lines.append(f"PEG : {fmt_num(valuation.peg, 2)}")
    facts_lines += [f"Vigilance : {v}" for v in vigilance]

    return Report(
        symbol=snapshot.symbol,
        verdict=valuation.verdict,
        title=f"{icon} {verdict_label} — {snapshot.symbol}",
        summary=summary,
        method_note=method_note,
        multiples_table=_table(valuation.assessments),
        arguments=tuple(arguments),
        cause_label=cause.value,
        cause_detail=_cause_detail(cause, attribution, news, lookback_days),
        news_lines=news_lines,
        vigilance=tuple(vigilance),
        facts="\n".join(facts_lines),
        news_for_llm=news_for_llm,
        as_of=now,
        source=source,
    )
