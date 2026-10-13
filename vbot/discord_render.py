"""Conversion d'un Report en embed Discord (respect des limites de taille de l'API)."""
from __future__ import annotations

import discord

from .report import DISCLAIMER, Report
from .valuation import Verdict

COLORS = {
    Verdict.UNDERVALUED: 0x2E7D32,
    Verdict.OVERVALUED: 0xC62828,
    Verdict.NEUTRAL: 0x607D8B,
    Verdict.INSUFFICIENT: 0xEF6C00,
}
EMBED_TOTAL_LIMIT = 6000


def _clip(text: str, limit: int = 1024) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def report_to_embed(report: Report) -> discord.Embed:
    def build(include_ai: bool) -> discord.Embed:
        embed = discord.Embed(
            title=_clip(report.title, 256),
            description=_clip(f"{report.summary}\n\n*{report.method_note}*", 4096),
            color=COLORS[report.verdict],
            timestamp=report.as_of,
        )
        embed.add_field(name="Multiples de valorisation", value=f"```\n{_clip(report.multiples_table, 1000)}\n```", inline=False)
        if report.arguments:
            embed.add_field(name="Pourquoi", value=_clip("\n".join(f"• {a}" for a in report.arguments)), inline=False)
        embed.add_field(name=_clip(f"Origine de l'écart : {report.cause_label}", 256), value=_clip(report.cause_detail), inline=False)
        embed.add_field(
            name="Actualités significatives",
            value=_clip("\n".join(report.news_lines) or "Aucune actualité spécifique significative sur la période analysée."),
            inline=False,
        )
        if include_ai and report.ai_summary:
            embed.add_field(name="Synthèse rédigée par IA (chiffres contrôlés)", value=_clip(report.ai_summary), inline=False)
        if report.vigilance:
            embed.add_field(name="Points de vigilance", value=_clip("\n".join(f"• {v}" for v in report.vigilance)), inline=False)
        embed.set_footer(text=_clip(f"{DISCLAIMER} Source des données : {report.source}.", 2048))
        return embed

    embed = build(include_ai=True)
    if len(embed) > EMBED_TOTAL_LIMIT:
        embed = build(include_ai=False)
    return embed
