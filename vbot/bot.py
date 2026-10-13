"""Bot Discord : commandes slash, scan planifié, envoi des alertes."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import tasks

from .analyzer import AnalysisError, Analyzer
from .config import Settings, normalize_symbol
from .discord_render import report_to_embed
from .providers.errors import MarketDataError
from .providers.base import MarketDataProvider
from .storage import Store

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScanSummary:
    analysed: int = 0
    alerts: int = 0
    errors: list[str] = field(default_factory=list)


class ScanInProgress(RuntimeError):
    pass


class ValuationBot(discord.Client):
    def __init__(self, settings: Settings, analyzer: Analyzer, store: Store, provider: MarketDataProvider) -> None:
        super().__init__(intents=discord.Intents.default(), allowed_mentions=discord.AllowedMentions.none())
        self.settings = settings
        self.analyzer = analyzer
        self.store = store
        self.provider = provider
        self.tree = app_commands.CommandTree(self)
        self._scan_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        register_commands(self)
        self.tree.error(self._on_tree_error)
        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()  # propagation globale pouvant prendre du temps
        self.scan_loop.change_interval(minutes=self.settings.scan_interval_minutes)
        self.scan_loop.start()

    async def on_ready(self) -> None:
        log.info("Connecté en tant que %s", self.user)

    async def close(self) -> None:
        self.scan_loop.cancel()
        await self.provider.aclose()
        await asyncio.to_thread(self.store.close)
        await super().close()

    # ----- Scan planifié -------------------------------------------------
    @tasks.loop(minutes=240)
    async def scan_loop(self) -> None:
        try:
            summary = await self.run_scan()
            log.info("Scan terminé : %d analysés, %d alertes, %d erreurs", summary.analysed, summary.alerts, len(summary.errors))
        except ScanInProgress:
            log.info("Scan planifié ignoré : un scan est déjà en cours")
        except Exception:
            log.exception("Échec du scan planifié")

    @scan_loop.before_loop
    async def _before_scan(self) -> None:
        await self.wait_until_ready()

    async def _alert_channel(self) -> discord.abc.Messageable:
        channel_id = self.settings.alert_channel_id
        channel = self.get_channel(channel_id) or await self.fetch_channel(channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(f"Le salon {channel_id} ne permet pas l'envoi de messages")
        return channel

    async def run_scan(self) -> ScanSummary:
        if self._scan_lock.locked():
            raise ScanInProgress()
        async with self._scan_lock:
            summary = ScanSummary()
            symbols = await asyncio.to_thread(self.store.list_symbols)
            channel = await self._alert_channel()
            for symbol in symbols:
                try:
                    result = await self.analyzer.analyze(symbol)
                except (AnalysisError, MarketDataError) as exc:
                    summary.errors.append(f"{symbol} : {exc}")
                    log.warning("Analyse %s impossible : %s", symbol, exc)
                    continue
                summary.analysed += 1
                now = _now()
                verdict = result.valuation.verdict.value
                alert = await asyncio.to_thread(
                    self.store.should_alert, symbol, verdict, self.settings.alert_cooldown_hours, now
                )
                if alert:
                    try:
                        await channel.send(embed=report_to_embed(result.report))
                        summary.alerts += 1
                    except discord.HTTPException as exc:
                        alert = False
                        summary.errors.append(f"{symbol} : envoi Discord en échec ({exc.status})")
                await asyncio.to_thread(
                    self.store.record_signal,
                    symbol, verdict, result.valuation.score, result.valuation.confidence,
                    result.cause.value, alert, now,
                )
            return summary

    # ----- Gestion des erreurs des commandes -----------------------------
    async def _on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"Commande disponible dans {error.retry_after:.0f} s."
        elif isinstance(error, app_commands.MissingPermissions):
            message = "Permission « Gérer le serveur » requise."
        elif isinstance(error, app_commands.NoPrivateMessage):
            message = "Commande utilisable uniquement sur un serveur."
        else:
            log.error("Erreur de commande", exc_info=getattr(error, "original", error))
            message = "Erreur interne. Consultez les journaux du bot."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def register_commands(bot: ValuationBot) -> None:
    tree = bot.tree

    @tree.command(name="analyse", description="Rapport de valorisation d'une action")
    @app_commands.describe(symbole="Ticker Yahoo, ex. AAPL, MC.PA, AIR.PA")
    @app_commands.guild_only()
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.user.id)
    async def analyse(interaction: discord.Interaction, symbole: str) -> None:
        try:
            symbol = normalize_symbol(symbole)
        except ValueError:
            await interaction.response.send_message("Symbole invalide.", ephemeral=True)
            return
        await interaction.response.defer(thinking=True)
        try:
            result = await bot.analyzer.analyze(symbol)
        except (AnalysisError, MarketDataError) as exc:
            await interaction.followup.send(f"Analyse impossible pour {symbol} : {exc}")
            return
        await interaction.followup.send(embed=report_to_embed(result.report))

    @tree.command(name="scan", description="Lance immédiatement l'analyse de la watchlist")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def scan(interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            summary = await bot.run_scan()
        except ScanInProgress:
            await interaction.followup.send("Un scan est déjà en cours.", ephemeral=True)
            return
        lines = [f"Scan terminé : {summary.analysed} analysé(s), {summary.alerts} alerte(s) publiée(s)."]
        lines += [f"• {e}" for e in summary.errors[:10]]
        await interaction.followup.send("\n".join(lines)[:1900], ephemeral=True)

    watchlist = app_commands.Group(name="watchlist", description="Gestion des valeurs surveillées", guild_only=True)

    @watchlist.command(name="liste", description="Affiche les valeurs surveillées")
    async def wl_list(interaction: discord.Interaction) -> None:
        symbols = await asyncio.to_thread(bot.store.list_symbols)
        text = ", ".join(symbols) if symbols else "Watchlist vide."
        await interaction.response.send_message(text[:1900], ephemeral=True)

    @watchlist.command(name="ajouter", description="Ajoute une valeur à surveiller")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def wl_add(interaction: discord.Interaction, symbole: str) -> None:
        try:
            symbol = normalize_symbol(symbole)
        except ValueError:
            await interaction.response.send_message("Symbole invalide.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        current = await asyncio.to_thread(bot.store.list_symbols)
        if len(current) >= bot.settings.max_watchlist:
            await interaction.followup.send(f"Limite atteinte ({bot.settings.max_watchlist} valeurs).", ephemeral=True)
            return
        try:
            known = await bot.provider.exists(symbol)
        except MarketDataError as exc:
            await interaction.followup.send(f"Vérification impossible : {exc}", ephemeral=True)
            return
        if not known:
            await interaction.followup.send(f"{symbol} inconnu de {bot.provider.name}.", ephemeral=True)
            return
        added = await asyncio.to_thread(bot.store.add_symbol, symbol, _now())
        await interaction.followup.send(f"{symbol} ajouté." if added else f"{symbol} déjà présent.", ephemeral=True)

    @watchlist.command(name="retirer", description="Retire une valeur de la surveillance")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def wl_remove(interaction: discord.Interaction, symbole: str) -> None:
        try:
            symbol = normalize_symbol(symbole)
        except ValueError:
            await interaction.response.send_message("Symbole invalide.", ephemeral=True)
            return
        removed = await asyncio.to_thread(bot.store.remove_symbol, symbol)
        await interaction.response.send_message(f"{symbol} retiré." if removed else f"{symbol} absent.", ephemeral=True)

    tree.add_command(watchlist)
