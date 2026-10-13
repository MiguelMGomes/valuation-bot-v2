"""Veille d'actualités : filtrage, catégorisation et neutralisation des contenus externes.

Les titres de presse sont des données non fiables : ils sont nettoyés avant
affichage et avant toute transmission au modèle de langage.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .models import NewsItem

CATEGORIES: dict[str, tuple[str, ...]] = {
    "Résultats / prévisions": (
        "earnings", "results", "quarterly", "revenue", "guidance", "outlook", "forecast", "eps",
        "beats", "misses", "profit warning", "résultats", "chiffre d'affaires", "prévisions",
    ),
    "Analystes": (
        "upgrade", "upgrades", "downgrade", "downgrades", "price target", "rating", "overweight",
        "underweight", "outperform", "underperform", "relève", "abaisse", "objectif de cours",
    ),
    "Opérations capitalistiques": (
        "acquisition", "acquire", "acquires", "merger", "takeover", "buyout", "spin-off", "stake",
        "fusion", "opa", "cession",
    ),
    "Juridique / réglementaire": (
        "lawsuit", "investigation", "probe", "antitrust", "regulator", "regulators", "fined",
        "settlement", "recall", "subpoena", "enquête", "amende", "sanction", "procès",
    ),
    "Gouvernance": (
        "ceo", "cfo", "chief executive", "resigns", "steps down", "appoints", "appointed",
        "démission", "nomination", "directeur général",
    ),
    "Capital / dividende": (
        "buyback", "repurchase", "dividend", "share offering", "secondary offering", "dilution",
        "stock split", "dividende", "augmentation de capital", "rachat d'actions",
    ),
    "Activité / produits": (
        "contract", "partnership", "launch", "launches", "approval", "fda", "contrat",
        "partenariat", "lancement",
    ),
}

_CATEGORY_RE = {
    cat: re.compile("|".join(r"(?<!\w)" + re.escape(k) + r"(?!\w)" for k in kws), re.IGNORECASE)
    for cat, kws in CATEGORIES.items()
}

_NOISE_RE = re.compile(
    r"stocks? to (buy|watch|sell)|^\s*\d+\s+(best|top|stocks)|should you buy|is it time to|"
    r"market (wrap|recap)|stock market today|top (gainers|losers)",
    re.IGNORECASE,
)

_INJECTION_RE = re.compile(
    r"ignore (all |the )?(previous|prior|above) instructions|disregard (the )?(system|previous)|"
    r"you are now|system prompt|ignore (toutes )?les instructions|</?\s*(system|assistant|user)\s*>",
    re.IGNORECASE,
)

_NAME_STOPWORDS = {
    "inc", "corp", "corporation", "co", "ltd", "plc", "sa", "se", "nv", "ag", "group",
    "holdings", "holding", "the", "company", "class", "and", "international",
}


@dataclass(frozen=True)
class TaggedNews:
    item: NewsItem
    categories: tuple[str, ...]
    suspicious: bool  # contenu ressemblant à une injection de consignes


def sanitize(text: str | None, limit: int = 280) -> str:
    """Nettoie un texte externe : caractères de contrôle, URL, balises, mentions Discord."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch if ch.isprintable() else " " for ch in text)
    text = re.sub(r"https?://\S+", "", text)
    text = text.replace("`", "'").replace("<", "‹").replace(">", "›")
    text = text.replace("@", "@\u200b")  # neutralise @everyone / @here
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def categorize(text: str) -> tuple[str, ...]:
    return tuple(cat for cat, rx in _CATEGORY_RE.items() if rx.search(text))


def is_noise(headline: str) -> bool:
    return bool(_NOISE_RE.search(headline or ""))


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text or ""))


def company_token(name: str | None) -> str | None:
    for tok in re.findall(r"[A-Za-zÀ-ÿ0-9&]+", name or ""):
        low = tok.lower()
        if len(low) >= 3 and low not in _NAME_STOPWORDS:
            return low
    return None


def mentions_company(text: str, symbol: str, company_name: str | None) -> bool:
    if len(symbol) >= 3 and re.search(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])", text):
        return True
    tok = company_token(company_name)
    return bool(tok and re.search(rf"(?<!\w){re.escape(tok)}(?!\w)", text, re.IGNORECASE))


def select_material_news(
    items: Iterable[NewsItem],
    symbol: str,
    company_name: str | None,
    now: datetime,
    lookback_days: int,
    max_items: int = 5,
) -> list[TaggedNews]:
    """Retient les actualités récentes, spécifiques à la société et porteuses d'un événement identifiable."""
    cutoff = now - timedelta(days=lookback_days)
    seen: set[str] = set()
    selected: list[TaggedNews] = []
    for item in sorted(items, key=lambda n: n.published_at, reverse=True):
        if not (cutoff <= item.published_at <= now + timedelta(hours=1)):
            continue
        key = re.sub(r"[^a-z0-9]", "", item.headline.lower())[:80]
        if not key or key in seen:
            continue
        seen.add(key)
        if is_noise(item.headline):
            continue
        text = f"{item.headline} {item.summary}"
        categories = categorize(text)
        if not categories or not mentions_company(text, symbol, company_name):
            continue
        selected.append(TaggedNews(item=item, categories=categories, suspicious=looks_like_injection(text)))
        if len(selected) >= max_items:
            break
    return selected


def format_news_for_llm(news: Iterable[TaggedNews]) -> str:
    lines = []
    for t in news:
        if t.suspicious:
            continue  # jamais transmis au modèle
        date = t.item.published_at.strftime("%d/%m/%Y")
        lines.append(
            f"- [{date}] [{', '.join(t.categories)}] {sanitize(t.item.headline, 160)} — {sanitize(t.item.summary, 240)}"
        )
    return "\n".join(lines)
