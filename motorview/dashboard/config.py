"""
MotorView Dashboard - configuração do cliente MQTT
======================================================
Lê credenciais do broker de st.secrets (Streamlit Community Cloud - veja
"Settings -> Secrets" do app) com fallback para variáveis de ambiente/.env
(útil para rodar localmente). Nunca commite senha em texto puro.
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


def mqtt_config() -> dict:
    return {
        "host": _get("MOTORVIEW_MQTT_HOST"),
        "port": int(_get("MOTORVIEW_MQTT_PORT", 8883)),
        "use_tls": str(_get("MOTORVIEW_MQTT_USE_TLS", "true")).lower() != "false",
        # IMPORTANTE: aqui deve ir sempre a credencial "subscribe only" do
        # broker (ex.: motorview-ingest) - nunca a credencial de publicação
        # do gateway (motorview-gateway-planta1).
        "username": _get("MOTORVIEW_MQTT_USERNAME"),
        "password": _get("MOTORVIEW_MQTT_PASSWORD"),
        "client_id": _get("MOTORVIEW_MQTT_CLIENT_ID", "motorview-dashboard"),
        "topic_filter": _get("MOTORVIEW_MQTT_TOPIC_FILTER", "motorview/#"),
    }


def authorized_emails() -> list[str]:
    """Allowlist de e-mails autorizados a usar o dashboard (2ª camada de
    autorização, além do 'Assignment required' do Entra Enterprise App).
    Configurado via secret/env AUTHORIZED_EMAILS, separado por vírgula."""
    raw = _get("AUTHORIZED_EMAILS", "")
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


def auth_configured() -> bool:
    """True se o bloco [auth]/[auth.microsoft] já foi preenchido em
    secrets.toml (login Microsoft pronto pra ativar) - ver auth.py."""
    try:
        import streamlit as st
        auth_section = st.secrets.get("auth")
        if not auth_section:
            return False
        return bool(auth_section.get("microsoft") or auth_section.get("client_id"))
    except Exception:
        return False


def require_auth() -> bool:
    """MOTORVIEW_REQUIRE_AUTH=true bloqueia o dashboard (fail-closed) se os
    Secrets de auth não estiverem configurados, em vez de abrir sem login
    por engano em produção. Default false (modo aberto) para não travar o
    desenvolvimento local."""
    return str(_get("MOTORVIEW_REQUIRE_AUTH", "false")).lower() == "true"
