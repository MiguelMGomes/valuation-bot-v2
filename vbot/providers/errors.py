"""Exceptions des fournisseurs de données (sans dépendance réseau, pour les tests)."""


class MarketDataError(RuntimeError):
    """Erreur générique d'un fournisseur de données de marché."""


class MarketDataAccessError(MarketDataError):
    """Accès refusé : clé invalide ou endpoint non inclus dans l'abonnement."""
