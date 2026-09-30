"""
MotorView Dashboard - assinante MQTT (ingestão em tempo real)
==================================================================
Roda em background dentro do próprio processo do Streamlit (thread do
paho-mqtt, via loop_start()) e grava cada mensagem recebida direto no
SQLite (db.py). app.py garante, via st.cache_resource, que só existe
UMA instância disso por processo do servidor.

Tópicos assinados: motorview/<site_id>/<inverter_id>/telemetry, .../fault
e motorview/<site_id>/gateway/status - ver motorview/gateway/mqtt_publisher.py.

Limitação importante (documentada no README do dashboard): isso só
recebe dados enquanto o processo do Streamlit está de pé. No plano
gratuito do Streamlit Community Cloud o app hiberna após um tempo sem
acesso - ao "acordar" ele reconecta e volta a receber dados normalmente,
mas o que foi publicado durante a hibernação não é recuperado aqui (o
gateway mantém esse histórico completo localmente no gateway, em
gateway/data/motorview_gateway.db). Para ingestão 24/7 sem essa lacuna,
rode este mesmo assinante como um worker separado e sempre ativo (ex.:
um pequeno serviço em Render/Railway/VPS) apontando para a mesma base.
"""

import json
import logging
import ssl
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

import db

log = logging.getLogger("motorview.ingest")


class MqttIngestWorker:
    def __init__(self, mqtt_cfg: dict):
        self.cfg = mqtt_cfg
        self.connected = False
        self.last_message_at: datetime | None = None
        self._lock = threading.Lock()

        self.client = mqtt.Client(client_id=mqtt_cfg.get("client_id", "motorview-dashboard"), clean_session=True)
        if mqtt_cfg.get("username"):
            self.client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password"))
        if mqtt_cfg.get("use_tls", True):
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def start(self):
        self.client.connect_async(self.cfg["host"], self.cfg.get("port", 8883), keepalive=30)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe(self.cfg.get("topic_filter", "motorview/#"), qos=1)
            log.info("Assinante MQTT conectado e inscrito em %s", self.cfg.get("topic_filter"))
        else:
            self.connected = False
            log.error("Assinante MQTT falhou ao conectar (rc=%s)", rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        log.warning("Assinante MQTT desconectado (rc=%s)", rc)

    def _on_message(self, client, userdata, msg):
        with self._lock:
            self.last_message_at = datetime.now(timezone.utc)
        try:
            parts = msg.topic.split("/")
            if len(parts) < 3 or parts[0] != "motorview":
                return
            site_id = parts[1]
            payload = json.loads(msg.payload.decode("utf-8"))

            if len(parts) == 4 and parts[2] == "gateway" and parts[3] == "status":
                db.log_connectivity(site_id, payload.get("status", "unknown"), payload.get("ts") or _now_iso())
                return

            if len(parts) != 4:
                return
            inverter_id, kind = parts[2], parts[3]

            if kind == "telemetry":
                db.upsert_inverter(inverter_id, site_id, payload.get("name", inverter_id),
                                    payload.get("ts") or _now_iso())
                db.insert_telemetry(payload)
            elif kind == "current_fast":
                db.upsert_inverter(inverter_id, site_id, payload.get("name", inverter_id),
                                    payload.get("ts") or _now_iso())
                db.insert_fast_current(payload)
            elif kind == "fault":
                db.upsert_inverter(inverter_id, site_id, payload.get("name", inverter_id),
                                    payload.get("ts") or _now_iso())
                db.insert_fault(payload)
        except Exception:
            log.exception("Falha ao processar mensagem MQTT no tópico %s", msg.topic)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
