"""Contrôle anti-hallucination : tout chiffre d'une synthèse IA doit figurer dans les données sources."""
from __future__ import annotations

import re

_NUM_RE = re.compile(
    r"(?<![\w.,])[-+−]?\d{1,3}(?:[\u00a0\u202f ]\d{3})+(?:,\d+)?(?!\d)"
    r"|(?<![\w.,])[-+−]?\d+(?:[.,]\d+)*"
)


def _candidates(raw: str) -> tuple[float, ...]:
    """Interprétations possibles d'un nombre (conventions française et anglaise), en valeur absolue."""
    s = re.sub(r"[\u00a0\u202f ]", "", raw.replace("−", "-").replace("+", ""))
    cands: set[str] = set()
    if "," in s and "." in s:
        cands.add(s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", "."))
    elif "," in s:
        cands.add(s.replace(",", "."))
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
            cands.add(s.replace(",", ""))
    elif s.count(".") > 1:
        cands.add(s.replace(".", ""))
    else:
        cands.add(s)
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
            cands.add(s.replace(".", ""))
    out: list[float] = []
    for c in cands:
        try:
            out.append(abs(float(c)))
        except ValueError:
            continue
    return tuple(out)


def extract_numbers(text: str) -> list[tuple[str, tuple[float, ...]]]:
    return [(m.group(0), _candidates(m.group(0))) for m in _NUM_RE.finditer(text or "")]


def _close(value: float, reference: float) -> bool:
    if abs(value - reference) <= 0.051 + 0.005 * reference:
        return True
    # arrondi à l'entier autorisé (ex. 23,47 -> 23)
    return value.is_integer() and reference >= 1 and round(reference) == value


def ungrounded_numbers(summary: str, sources: str) -> list[str]:
    allowed = [v for _, cands in extract_numbers(sources) for v in cands]
    bad: list[str] = []
    for raw, cands in extract_numbers(summary):
        if not cands:
            continue
        if any(c.is_integer() and c <= 12 for c in cands):
            continue  # petits entiers usuels (« 12 mois », « 3 multiples »)
        if not any(_close(c, a) for c in cands for a in allowed):
            bad.append(raw)
    return bad
