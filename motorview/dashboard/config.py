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
        "username": _get("MOTORVIEW_MQTT_USERNAME"),
        "password": _get("MOTORVIEW_MQTT_PASSWORD"),
        "client_id": _get("MOTORVIEW_MQTT_CLIENT_ID", "motorview-dashboard"),
        "topic_filter": _get("MOTORVIEW_MQTT_TOPIC_FILTER", "motorview/#"),
    }
