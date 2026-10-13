"""Origine de l'écart de valorisation : cours (marché) ou bénéfices (chiffres) ?

Identité comptable : PER = Cours / BPA, donc
    ln(PER_t / PER_t-1) = ln(1 + r_cours) - ln(1 + g_BPA)
On mesure la part de chaque terme dans la variation du PER sur 12 mois.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from .formatting import fmt_pct


class Driver(str, Enum):
    PRICE = "price"
    EARNINGS = "earnings"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class Cause(str, Enum):
    NEWS = "Actualité récente"
    FUNDAMENTALS = "Chiffres (fondamentaux)"
    MARKET_NO_CATALYST = "Marché, sans catalyseur récent identifié"
    MIXED = "Mixte (cours et bénéfices)"
    UNDETERMINED = "Indéterminée"


@dataclass(frozen=True)
class Attribution:
    price_return: float | None
    eps_growth: float | None
    pe_change: float | None
    price_share: float | None  # part du cours dans la variation du PER (0 à 1)
    driver: Driver


def attribute_pe_change(price_return: float | None, eps_growth: float | None, dominance: float = 0.65) -> Attribution:
    if price_return is None or eps_growth is None or price_return <= -1 or eps_growth <= -1:
        return Attribution(price_return, eps_growth, None, None, Driver.UNKNOWN)
    lp = math.log1p(price_return)
    le = -math.log1p(eps_growth)
    pe_change = math.expm1(lp + le)
    denom = abs(lp) + abs(le)
    if denom < 1e-9:
        return Attribution(price_return, eps_growth, pe_change, None, Driver.UNKNOWN)
    share = abs(lp) / denom
    if share >= dominance:
        driver = Driver.PRICE
    elif share <= 1 - dominance:
        driver = Driver.EARNINGS
    else:
        driver = Driver.MIXED
    return Attribution(price_return, eps_growth, pe_change, share, driver)


def describe_attribution(attr: Attribution) -> str:
    if attr.pe_change is None:
        return (
            "Décomposition impossible : rendement sur 52 semaines ou croissance du BPA indisponible "
            "(ou BPA devenu négatif)."
        )
    base = (
        f"Sur 12 mois, cours {fmt_pct(attr.price_return)} et BPA {fmt_pct(attr.eps_growth)}, "
        f"soit une variation du PER de {fmt_pct(attr.pe_change)}"
    )
    if attr.driver is Driver.PRICE:
        return base + " : elle provient principalement du cours, donc d'une révision de l'appréciation du marché."
    if attr.driver is Driver.EARNINGS:
        return base + " : elle provient principalement des bénéfices, l'écart est donc d'origine fondamentale."
    if attr.driver is Driver.MIXED:
        return base + " : elle résulte à la fois du cours et de l'évolution des bénéfices."
    return base + "."


def classify_cause(
    attr: Attribution,
    material_news_count: int | None,
    change_1d: float | None,
    daily_move_threshold: float = 0.04,
) -> Cause:
    """material_news_count=None signifie que le flux d'actualités n'a pas pu être consulté."""
    if attr.driver is Driver.EARNINGS:
        return Cause.FUNDAMENTALS
    if attr.driver is Driver.MIXED:
        return Cause.MIXED
    if attr.driver is Driver.PRICE:
        if material_news_count is None:
            return Cause.UNDETERMINED
        return Cause.NEWS if material_news_count > 0 else Cause.MARKET_NO_CATALYST
    if material_news_count and change_1d is not None and abs(change_1d) >= daily_move_threshold:
        return Cause.NEWS
    return Cause.UNDETERMINED
