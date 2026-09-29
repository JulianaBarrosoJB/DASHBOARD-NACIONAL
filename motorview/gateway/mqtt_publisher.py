"""
MotorView Gateway - publicação MQTT segura
==========================================
Tópicos:
  motorview/<site>/<inv>/telemetry       telemetria completa (retained)
  motorview/<site>/<inv>/current_fast    resumo rápido de corrente (não retido)
  motorview/<site>/<inv>/fault           evento de falha (não retido)
  motorview/<site>/gateway/status        online/offline
"""

import json
import logging
import ssl
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

log = logging.getLogger("motorview.mqtt")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MqttPublisher:
    def __init__(self, mqtt_cfg: dict, site_id: str):
        self.site_id = site_id
        self.qos = mqtt_cfg.get("qos", 1)
        self.connected = False

        self.client = mqtt.Client(
            client_id=mqtt_cfg.get("client_id", "motorview-gateway"),
            clean_session=True,
        )
        self.client.username_pw_set(mqtt_cfg["username"], mqtt_cfg["password"])
        if mqtt_cfg.get("use_tls", True):
            self.client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )

        status_topic = f"motorview/{site_id}/gateway/status"
        # O timestamp exato da queda não existe no dispositivo quando o Last Will
        # é emitido pelo broker. O ingestor grava o horário de recebimento.
        self.client.will_set(
            status_topic,
            payload=json.dumps({"status": "offline", "ts": None, "source": "lwt"}),
            qos=1,
            retain=True,
        )

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self._host = mqtt_cfg["host"]
        self._port = mqtt_cfg.get("port", 8883)
        self._keepalive = mqtt_cfg.get("keepalive_seconds", 30)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            log.info("Conectado ao broker MQTT %s:%s", self._host, self._port)
            client.publish(
                f"motorview/{self.site_id}/gateway/status",
                json.dumps({"status": "online", "ts": _now_iso(), "source": "gateway"}),
                qos=1,
                retain=True,
            )
        else:
            self.connected = False
            log.error("Falha ao conectar no MQTT (rc=%s)", rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        log.warning("Desconectado do broker MQTT (rc=%s)", rc)

    def connect(self):
        self.client.connect_async(self._host, self._port, keepalive=self._keepalive)
        self.client.loop_start()

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def topic_telemetry(self, inverter_id: str) -> str:
        return f"motorview/{self.site_id}/{inverter_id}/telemetry"

    def topic_fast_current(self, inverter_id: str) -> str:
        return f"motorview/{self.site_id}/{inverter_id}/current_fast"

    def topic_fault(self, inverter_id: str) -> str:
        return f"motorview/{self.site_id}/{inverter_id}/fault"

    def publish(self, topic: str, payload: dict, retain: bool = False) -> bool:
        if not self.connected:
            return False
        info = self.client.publish(
            topic, json.dumps(payload), qos=self.qos, retain=retain
        )
        return info.rc == mqtt.MQTT_ERR_SUCCESS
