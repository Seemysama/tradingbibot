import os
import sys
from dataclasses import dataclass
from dotenv import load_dotenv

# Chargement des variables d'environnement depuis le fichier .env
load_dotenv()

@dataclass(frozen=True)
class Settings:
    """
    Configuration centralisée de l'application.
    Les attributs sont en lecture seule (frozen=True).
    """
    BINANCE_API_KEY: str
    BINANCE_API_SECRET: str
    QUESTDB_HOST: str
    QUESTDB_PORT: int
    SYMBOLS: list[str]

    # Machine Learning Settings
    ML_ENABLED: bool = True
    ML_MIN_CONFIDENCE: float = 0.6
    ML_MIN_SAMPLES: int = 1000

def load_config() -> Settings:
    """
    Charge et valide la configuration au démarrage.
    Lève une erreur fatale si une variable critique est manquante.
    """
    try:
        # Récupération des variables avec validation stricte
        binance_key = _get_env_strict("BINANCE_API_KEY")
        binance_secret = _get_env_strict("BINANCE_API_SECRET")
        questdb_host = _get_env_strict("QUESTDB_HOST")
        questdb_port_str = _get_env_strict("QUESTDB_PORT")
        symbols_str = _get_env_strict("SYMBOLS") # Récupération des symboles

        # Conversion et validation des types
        try:
            questdb_port = int(questdb_port_str)
        except ValueError:
            raise ValueError(f"QUESTDB_PORT doit être un entier, reçu: {questdb_port_str}")

        # Parsing des symboles (séparés par virgule)
        symbols = [s.strip() for s in symbols_str.split(',') if s.strip()]
        if not symbols:
             raise ValueError("La liste SYMBOLS est vide.")

        return Settings(
            BINANCE_API_KEY=binance_key,
            BINANCE_API_SECRET=binance_secret,
            QUESTDB_HOST=questdb_host,
            QUESTDB_PORT=questdb_port,
            SYMBOLS=symbols,
            ML_ENABLED=os.getenv("ML_ENABLED", "true").lower() == "true",
            ML_MIN_CONFIDENCE=float(os.getenv("ML_MIN_CONFIDENCE", "0.6")),
            ML_MIN_SAMPLES=int(os.getenv("ML_MIN_SAMPLES", "1000"))
        )

    except Exception as e:
        sys.stderr.write(f"❌ Erreur de configuration critique : {e}\n")
        sys.exit(1)

def _get_env_strict(key: str) -> str:
    """Récupère une variable d'environnement ou lève une erreur si elle est absente/vide."""
    value = os.getenv(key)
    if not value or not value.strip():
        raise ValueError(f"La variable d'environnement '{key}' est manquante ou vide.")
    return value

# Instance globale de configuration
# Sera initialisée explicitement dans le main.py pour contrôler le cycle de vie
config: Settings = None  # type: ignore
