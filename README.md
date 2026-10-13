# vbot — Bot Discord de détection de sous/surévaluation d'actions (MVP)

Surveille une liste d'actions (US et Europe), compare leurs multiples de valorisation à leur
historique et à leurs pairs, identifie l'origine de l'écart (cours ou bénéfices),
relève les actualités significatives et publie un rapport chiffré sur Discord.

## Méthode

| Étape | Calcul | Nature |
|---|---|---|
| Valorisation relative | PER, VE/EBITDA, P/FCF, P/CA, P/ANC comparés à leur médiane historique et à la médiane des pairs ; score = moyenne pondérée des écarts (30/30/20/10/10) | Déterministe |
| Verdict | score ≤ -20 % : sous-évaluation apparente ; ≥ +20 % : surévaluation apparente (seuils configurables) | Déterministe |
| Origine de l'écart | ln(ΔPER) = ln(1 + r_cours) − ln(1 + g_BPA) sur 12 mois : part du cours vs part des bénéfices | Déterministe |
| Cause | bénéfices dominants → « Chiffres » ; cours dominant + actualité → « Actualité » ; cours dominant sans actualité → « Marché sans catalyseur » | Déterministe |
| Vigilance | value trap (BPA/CA en baisse), levier, PER non significatif, prime justifiée par la croissance (PEG) | Déterministe |
| Synthèse rédigée | Reformulation par Claude ; rejetée si elle contient un chiffre absent des données | IA, facultative |

« Sous-évaluée » signifie ici **décote relative** par rapport aux références, pas
valeur intrinsèque. Aucun backtest n'a été réalisé : la pertinence prédictive des
signaux n'est pas démontrée.

## Installation locale

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # puis renseigner les clés
python -m pytest -q
```

### Discord
1. https://discord.com/developers/applications → *New Application* → onglet *Bot* → copier le token dans `DISCORD_TOKEN`.
2. *OAuth2 → URL Generator* : scopes `bot` et `applications.commands` ; permissions *View Channels*, *Send Messages*, *Embed Links*.
3. Ouvrir l'URL générée pour inviter le bot. Activer le mode développeur Discord, clic droit sur le salon d'alertes → *Copier l'identifiant* → `DISCORD_ALERT_CHANNEL_ID` ; idem pour le serveur → `DISCORD_GUILD_ID`.
Aucun intent privilégié n'est nécessaire.

### Source de données
Par défaut **Yahoo Finance** (`DATA_PROVIDER=yahoo`) via la bibliothèque non officielle
`yfinance` : aucune clé requise, actions US et européennes (suffixes Yahoo : `MC.PA`,
`SAP.DE`, `SHEL.L`...). Les multiples historiques sont recalculés à partir des comptes
annuels publiés (4 à 5 exercices) et du cours de clôture de chaque exercice.

Limites : pas d'API officielle, usage personnel uniquement (conditions Yahoo), blocages
possibles (HTTP 429) surtout depuis un serveur. Les requêtes sont espacées
(`YAHOO_MIN_INTERVAL_S`) et mises en cache. En cas de blocage durable :
`DATA_PROVIDER=finnhub` + `FINNHUB_API_KEY` (clé gratuite sur https://finnhub.io/register,
actions US uniquement en offre gratuite).

Pairs : secteur Yahoo par défaut ; pour les valeurs européennes, des pairs choisis à la main
sont souvent plus pertinents (`PEERS_FILE=config/peers.json`, modèle dans
`config/peers.example.json`).

**Contrôle obligatoire avant mise en service :**
```bash
docker compose run --rm vbot python scripts/check_data.py AAPL MC.PA
```

### Lancement
```bash
python -m vbot
```

## Docker
```bash
docker compose up -d --build
docker compose logs -f vbot
```
Sauvegarde de la base : `docker compose cp vbot:/data/vbot.sqlite3 ./backup.sqlite3`

## Commandes
| Commande | Accès | Effet |
|---|---|---|
| `/analyse <ticker>` | tous (1 / 30 s / utilisateur) | rapport complet immédiat |
| `/watchlist liste` | tous | valeurs surveillées |
| `/watchlist ajouter|retirer <ticker>` | *Gérer le serveur* | gestion de la liste |
| `/scan` | *Gérer le serveur* | scan immédiat |

Les alertes automatiques ne sont publiées que pour un verdict sous/surévalué, au
premier signal, à chaque changement d'état, puis au plus une fois par `ALERT_COOLDOWN_HOURS`.

## Sécurité
- Secrets uniquement dans `.env` (exclu de Git et de l'image Docker) ; clé Finnhub transmise par en-tête HTTP.
- Contenus externes nettoyés ; mentions Discord désactivées (`AllowedMentions.none()`).
- Actualités suspectes (injection de consignes) exclues de l'IA ; l'IA n'a aucun outil ni pouvoir de décision.
- Conteneur exécuté sans privilèges root. Aucune donnée personnelle stockée (RGPD).

## Limites connues
- Yahoo Finance : source non officielle, susceptible d'être bloquée ou modifiée sans préavis.
- Croissance du BPA (Yahoo) : dernier trimestre vs même trimestre N-1, approximation de la variation sur 12 mois.
- Historique non calculé si la devise de cotation diffère de celle des comptes (ADR) ; tronqué après une division du nominal.
- Fondamentaux TTM/annuels : décalage possible avec la dernière publication.
- Fenêtre d'actualités (30 j) plus courte que la fenêtre d'attribution (12 mois).
- Pairs fournis par Finnhub, non retraités ; multiples sectoriels non comparables entre industries (banques, foncières).
