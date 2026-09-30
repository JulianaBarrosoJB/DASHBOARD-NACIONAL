"""Configuração do MotorView Dashboard.

Lê DATABASE_URL e autenticação de st.secrets no Streamlit Community Cloud,
com fallback para variáveis de ambiente/.env no desenvolvimento local.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get(key: str, default=None):
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


def database_url() -> str | None:
    """URL PostgreSQL/Neon do usuário read-only do dashboard."""
    value = _get("DATABASE_URL")
    return str(value).strip() if value else None


def authorized_emails() -> list[str]:
    raw = _get("AUTHORIZED_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def auth_configured() -> bool:
    try:
        import streamlit as st
        auth_section = st.secrets.get("auth")
        if not auth_section:
            return False
        return bool(auth_section.get("microsoft") or auth_section.get("client_id"))
    except Exception:
        return False


def require_auth() -> bool:
    return str(_get("MOTORVIEW_REQUIRE_AUTH", "false")).lower() == "true"


def debug_mode() -> bool:
    return str(_get("MOTORVIEW_DEBUG", "false")).lower() == "true"


def failover_config() -> dict | None:
    """Configuração opcional do ingest cloud de contingência."""
    enabled = str(_get("MOTORVIEW_FAILOVER_ENABLED", "false")).lower() == "true"
    if not enabled:
        return None
    keys = {
        "database_url": _get("FAILOVER_DATABASE_URL"),
        "host": _get("MOTORVIEW_MQTT_HOST"),
        "username": _get("MOTORVIEW_MQTT_USERNAME"),
        "password": _get("MOTORVIEW_MQTT_PASSWORD"),
    }
    if not all(keys.values()):
        return None
    return {
        "database_url": str(keys["database_url"]).strip(),
        "primary_grace_seconds": float(_get("MOTORVIEW_FAILOVER_GRACE_SECONDS", "4")),
        "mqtt": {
            "host": str(keys["host"]).strip(),
            "port": int(_get("MOTORVIEW_MQTT_PORT", "8883")),
            "username": str(keys["username"]),
            "password": str(keys["password"]),
            "topic_filter": str(_get("MOTORVIEW_MQTT_TOPIC_FILTER", "motorview/planta1/#")),
            "client_id": str(_get("MOTORVIEW_FAILOVER_CLIENT_ID", "motorview-cloud-failover-planta1")),
        },
    }
