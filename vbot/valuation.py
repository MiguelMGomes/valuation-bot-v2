"""Moteur de valorisation relative — déterministe et testable.

Principe : chaque multiple est comparé (1) à sa médiane historique et (2) à la
médiane des pairs. L'écart de chaque multiple est la moyenne des écarts
disponibles ; le score global est la moyenne pondérée de ces écarts.
Score négatif = décote, positif = prime.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from .formatting import fmt_num, fmt_pct
from .models import MULTIPLE_LABELS, CompanySnapshot

DEFAULT_WEIGHTS: dict[str, float] = {"pe": 0.30, "ev_ebitda": 0.30, "p_fcf": 0.20, "ps": 0.10, "pb": 0.10}
MAX_MEANINGFUL_MULTIPLE = 500.0  # au-delà, le multiple n'est plus interprétable
GAP_CLIP = 1.0  # écart plafonné à +100 % pour limiter l'effet des valeurs extrêmes


class Verdict(str, Enum):
    UNDERVALUED = "undervalued"
    OVERVALUED = "overvalued"
    NEUTRAL = "neutral"
    INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class ValuationConfig:
    undervalued_threshold: float = -0.20
    overvalued_threshold: float = 0.20
    min_metrics: int = 3
    min_history_points: int = 3
    min_peers: int = 3
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass(frozen=True)
class MultipleAssessment:
    key: str
    current: float | None
    hist_median: float | None
    hist_n: int
    peer_median: float | None
    peer_n: int
    vs_hist: float | None
    vs_peers: float | None

    @property
    def label(self) -> str:
        return MULTIPLE_LABELS.get(self.key, self.key)

    @property
    def combined(self) -> float | None:
        gaps = [g for g in (self.vs_hist, self.vs_peers) if g is not None]
        return sum(gaps) / len(gaps) if gaps else None


@dataclass(frozen=True)
class ValuationResult:
    symbol: str
    verdict: Verdict
    score: float | None
    confidence: str
    assessments: tuple[MultipleAssessment, ...]
    flags: tuple[str, ...]
    peg: float | None

    @property
    def used(self) -> tuple[MultipleAssessment, ...]:
        return tuple(a for a in self.assessments if a.combined is not None)


def is_meaningful(x: object) -> bool:
    """Un multiple n'est exploitable que s'il est fini et strictement positif."""
    return (
        isinstance(x, (int, float))
        and not isinstance(x, bool)
        and math.isfinite(x)
        and 0 < x <= MAX_MEANINGFUL_MULTIPLE
    )


def robust_median(values: Iterable[object]) -> tuple[float | None, int]:
    valid = [float(v) for v in values if is_meaningful(v)]  # type: ignore[arg-type]
    return (statistics.median(valid), len(valid)) if valid else (None, 0)


def relative_gap(current: float | None, reference: float | None) -> float | None:
    if not (is_meaningful(current) and is_meaningful(reference)):
        return None
    return max(-GAP_CLIP, min(GAP_CLIP, current / reference - 1.0))  # type: ignore[operator]


def assess_multiple(
    key: str,
    current: float | None,
    history: Iterable[object],
    peer_values: Iterable[object],
    cfg: ValuationConfig,
) -> MultipleAssessment:
    hist_med, hist_n = robust_median(history)
    peer_med, peer_n = robust_median(peer_values)
    cur = current if is_meaningful(current) else None
    vs_hist = relative_gap(cur, hist_med) if hist_n >= cfg.min_history_points else None
    vs_peers = relative_gap(cur, peer_med) if peer_n >= cfg.min_peers else None
    return MultipleAssessment(key, cur, hist_med, hist_n, peer_med, peer_n, vs_hist, vs_peers)


def compute_peg(snapshot: CompanySnapshot) -> float | None:
    pe = snapshot.multiples.get("pe")
    growth = snapshot.fundamentals.get("eps_growth")
    if is_meaningful(pe) and growth is not None and growth > 0:
        return pe / (growth * 100)  # type: ignore[operator]
    return None


def _confidence(used: list[MultipleAssessment], score: float) -> str:
    if score == 0:
        return "faible"
    sign = 1 if score > 0 else -1
    agreement = sum(1 for a in used if (a.combined or 0) * sign > 0) / len(used)
    both_refs = sum(1 for a in used if a.vs_hist is not None and a.vs_peers is not None) / len(used)
    if len(used) >= 4 and agreement >= 0.75 and both_refs >= 0.5:
        return "élevée"
    if len(used) >= 3 and agreement >= 0.6:
        return "moyenne"
    return "faible"


def _flags(snapshot: CompanySnapshot, verdict: Verdict, peg: float | None) -> list[str]:
    flags: list[str] = []
    f = snapshot.fundamentals
    if not is_meaningful(snapshot.multiples.get("pe")):
        flags.append("PER non significatif (résultat négatif ou donnée absente) : appréciation fondée sur les autres multiples.")
    eps_g, rev_g, de = f.get("eps_growth"), f.get("revenue_growth"), f.get("debt_to_equity")
    if verdict is Verdict.UNDERVALUED:
        if eps_g is not None and eps_g <= -0.10:
            flags.append(
                f"BPA en recul de {fmt_pct(eps_g, signed=False)} sur 12 mois : la décote peut refléter "
                "une dégradation durable (risque de « value trap »)."
            )
        if rev_g is not None and rev_g < 0:
            flags.append(f"Chiffre d'affaires en baisse de {fmt_pct(rev_g, signed=False)} sur 12 mois.")
        if de is not None and de > 2:
            flags.append(
                f"Endettement élevé (dette / capitaux propres = {fmt_num(de, 2)}) : la décote peut rémunérer un risque financier."
            )
    if verdict is Verdict.OVERVALUED and peg is not None and eps_g is not None and peg <= 1.5:
        flags.append(
            f"Croissance du BPA de {fmt_pct(eps_g)} sur 12 mois (PEG ≈ {fmt_num(peg, 2)}) : "
            "la prime est en partie justifiée par la croissance."
        )
    return flags


def evaluate(
    snapshot: CompanySnapshot,
    peer_multiples: dict[str, list[float]],
    cfg: ValuationConfig | None = None,
) -> ValuationResult:
    cfg = cfg or ValuationConfig()
    assessments = tuple(
        assess_multiple(
            key,
            snapshot.multiples.get(key),
            snapshot.history.get(key, []),
            peer_multiples.get(key, []),
            cfg,
        )
        for key in cfg.weights
    )
    used = [a for a in assessments if a.combined is not None]
    peg = compute_peg(snapshot)
    if len(used) < cfg.min_metrics:
        verdict, score, confidence = Verdict.INSUFFICIENT, None, "insuffisante"
    else:
        total_w = sum(cfg.weights[a.key] for a in used)
        score = sum(cfg.weights[a.key] * a.combined for a in used) / total_w  # type: ignore[operator]
        if score <= cfg.undervalued_threshold:
            verdict = Verdict.UNDERVALUED
        elif score >= cfg.overvalued_threshold:
            verdict = Verdict.OVERVALUED
        else:
            verdict = Verdict.NEUTRAL
        confidence = _confidence(used, score)
    return ValuationResult(
        symbol=snapshot.symbol,
        verdict=verdict,
        score=score,
        confidence=confidence,
        assessments=assessments,
        flags=tuple(_flags(snapshot, verdict, peg)),
        peg=peg,
    )
