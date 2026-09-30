"""MotorView - worker 24/7 HiveMQ -> Neon PostgreSQL.

O callback MQTT apenas valida/encaminha mensagens para uma fila local.
Uma thread separada grava no PostgreSQL, evitando bloquear o loop MQTT.
Em indisponibilidade temporária do banco, a mensagem atual é retentada
com backoff e as próximas permanecem na fila (até o limite configurado).
"""

import json
import logging
import queue
import signal
import ssl
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from config import ConfigError, load_config
from database import MotorViewDatabase

_running = True


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def stop_handler(signum, frame):
    global _running
    _running = False


class IngestWorker:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.log = logging.getLogger("motorview.ingest")
        self.db = MotorViewDatabase(cfg["database_url"])
        self.items = queue.Queue(maxsize=cfg["queue_size"])
        self.db_thread = threading.Thread(
            target=self._database_loop,
            name="motorview-postgres",
            daemon=True,
        )

        mc = cfg["mqtt"]
        # Sessão persistente: com o mesmo client_id, mensagens QoS 1 podem
        # permanecer associadas à sessão do assinante durante desconexões.
        self.client = mqtt.Client(
            client_id=mc["client_id"],
            clean_session=False,
        )
        self.client.username_pw_set(mc["username"], mc["password"])
        self.client.tls_set(
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            self.log.error("Falha ao conectar ao MQTT (rc=%s)", rc)
            return
        topic_filter = self.cfg["mqtt"]["topic_filter"]
        client.subscribe(topic_filter, qos=1)
        self.log.info("MQTT conectado; inscrito em %s com QoS 1", topic_filter)

    def _on_disconnect(self, client, userdata, rc):
        if _running:
            self.log.warning("MQTT desconectado (rc=%s); reconexão automática ativa", rc)

    def _on_message(self, client, userdata, msg):
        received_at = now_iso()
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload JSON não é objeto")
            self.items.put_nowait((msg.topic, payload, received_at))
        except queue.Full:
            self.log.error(
                "Fila cheia (%d); mensagem não enfileirada: %s",
                self.items.maxsize,
                msg.topic,
            )
        except Exception:
            self.log.exception("Mensagem MQTT inválida em %s", msg.topic)

    def _database_loop(self):
        backoff = 1
        current = None

        while _running or current is not None or not self.items.empty():
            if current is None:
                try:
                    current = self.items.get(timeout=0.5)
                except queue.Empty:
                    continue

            topic, payload, received_at = current
            try:
                self.db.process(topic, payload, received_at)
                self.items.task_done()
                current = None
                backoff = 1
            except Exception:
                self.log.exception(
                    "Falha ao gravar %s; nova tentativa em %ss (fila=%d)",
                    topic, backoff, self.items.qsize(),
                )
                self.db.close()
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

        self.db.close()

    def run(self):
        # Falha cedo se a credencial/DB estiver incorreta.
        self.db.connect()
        self.db_thread.start()

        mc = self.cfg["mqtt"]
        self.client.connect_async(mc["host"], mc["port"], keepalive=30)
        self.client.loop_start()

        self.log.info("MotorView ingest worker iniciado")

        try:
            while _running:
                time.sleep(0.5)
        finally:
            self.log.info("Encerrando worker; fila pendente=%d", self.items.qsize())
            self.client.loop_stop()
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.db_thread.join(timeout=30)
            self.db.close()


def main():
    try:
        cfg = load_config()
    except (ConfigError, ValueError) as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, cfg["log_level"], logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    try:
        IngestWorker(cfg).run()
    except KeyboardInterrupt:
        pass
    except Exception:
        logging.getLogger("motorview.ingest").exception("Worker encerrado por erro fatal")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
