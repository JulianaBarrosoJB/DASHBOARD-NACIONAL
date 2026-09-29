"""
MotorView Gateway - carregamento de configuração
==================================================
Lê config.yaml (copiado de config.example.yaml) e permite sobrescrever
segredos (principalmente a senha do MQTT) por variável de ambiente/.env,
para não deixar senha em texto puro versionada por engano.
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"

load_dotenv(BASE_DIR / ".env")


class ConfigError(RuntimeError):
    pass


def load_config(path: Path | None = None) -> dict:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(
            f"Arquivo de configuração não encontrado: {cfg_path}\n"
            "Copie config.example.yaml para config.yaml e ajuste os valores."
        )

    with open(cfg_path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)

    # Segredos por variável de ambiente (.env) têm prioridade sobre o YAML,
    # mas só quando preenchidos - uma variável presente e vazia no .env
    # (ex.: template ainda não preenchido) não deve apagar um valor já
    # configurado em config.yaml.
    mqtt = cfg.setdefault("mqtt", {})
    if os.getenv("MOTORVIEW_MQTT_HOST"):
        mqtt["host"] = os.getenv("MOTORVIEW_MQTT_HOST")
    if os.getenv("MOTORVIEW_MQTT_USERNAME"):
        mqtt["username"] = os.getenv("MOTORVIEW_MQTT_USERNAME")
    if os.getenv("MOTORVIEW_MQTT_PASSWORD"):
        mqtt["password"] = os.getenv("MOTORVIEW_MQTT_PASSWORD")
    if os.getenv("MOTORVIEW_MQTT_PORT"):
        mqtt["port"] = int(os.getenv("MOTORVIEW_MQTT_PORT"))

    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    if not cfg.get("inverters"):
        raise ConfigError("config.yaml precisa listar ao menos um inversor em 'inverters'.")
    mqtt = cfg.get("mqtt", {})
    if mqtt.get("enabled", True):
        if not mqtt.get("host") or "xxxxxxxx" in str(mqtt.get("host", "")):
            raise ConfigError(
                "Configure o host do broker MQTT em config.yaml (mqtt.host) "
                "ou na variável de ambiente MOTORVIEW_MQTT_HOST."
            )
        if not mqtt.get("password"):
            raise ConfigError(
                "Configure a senha do MQTT em config.yaml (mqtt.password) ou, de preferência, "
                "na variável de ambiente MOTORVIEW_MQTT_PASSWORD (arquivo .env)."
            )


def register_map_path(inverter_cfg: dict) -> Path:
    return BASE_DIR / inverter_cfg["register_map"]
