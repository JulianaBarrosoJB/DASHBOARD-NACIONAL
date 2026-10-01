"""Configuração do worker MQTT -> PostgreSQL do MotorView."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Variável obrigatória ausente: {name}")
    return value


def load_config() -> dict:
    cfg = {
        "database_url": _required("DATABASE_URL"),
        "mqtt": {
            "host": _required("MOTORVIEW_MQTT_HOST"),
            "port": int(os.getenv("MOTORVIEW_MQTT_PORT", "8883")),
            "username": _required("MOTORVIEW_MQTT_USERNAME"),
            "password": _required("MOTORVIEW_MQTT_PASSWORD"),
            "topic_filter": os.getenv(
                "MOTORVIEW_MQTT_TOPIC_FILTER", "motorview/suape/#"
            ),
            "client_id": os.getenv(
                "MOTORVIEW_MQTT_CLIENT_ID", "motorview-neon-ingest-suape"
            ),
        },
        "spool_path": os.getenv(
            "MOTORVIEW_INGEST_SPOOL_PATH",
            str(BASE_DIR / "data" / "ingest_spool.db"),
        ),
        "batch_size": max(10, int(os.getenv("MOTORVIEW_INGEST_BATCH_SIZE", "1000"))),
        "compact_interval_seconds": max(
            300, int(os.getenv("MOTORVIEW_COMPACT_INTERVAL_SECONDS", "3600"))
        ),
        "log_level": os.getenv("MOTORVIEW_INGEST_LOG_LEVEL", "INFO").upper(),
    }
    return cfg
