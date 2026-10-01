"""MotorView - worker durável HiveMQ -> Neon PostgreSQL."""

import json
import logging
import signal
import ssl
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from config import ConfigError, load_config
from database import MotorViewDatabase
from spool import DurableSpool

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
        self.spool = DurableSpool(cfg["spool_path"])
        self.db_thread = threading.Thread(
            target=self._database_loop,
            name="motorview-postgres",
            daemon=True,
        )

        mc = cfg["mqtt"]
        # ACK manual: o broker só recebe PUBACK depois que a mensagem foi
        # persistida no spool SQLite. Assim uma queda do processo não perde
        # mensagens que estavam apenas em RAM.
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=mc["client_id"],
            clean_session=False,
            protocol=mqtt.MQTTv311,
            manual_ack=True,
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
            payload_text = msg.payload.decode("utf-8")
            payload = json.loads(payload_text)
            if not isinstance(payload, dict):
                raise ValueError("payload JSON não é objeto")

            self.spool.add(msg.topic, payload_text, received_at)

            # Só confirma ao HiveMQ depois de persistir localmente.
            if msg.qos > 0:
                rc = client.ack(msg.mid, msg.qos)
                if rc != mqtt.MQTT_ERR_SUCCESS:
                    self.log.error("Falha ao confirmar MQTT mid=%s rc=%s", msg.mid, rc)
        except Exception:
            self.log.exception(
                "Falha ao persistir mensagem MQTT %s; conexão será refeita para redelivery",
                msg.topic,
            )
            # Sem ACK manual, desconectar força a sessão persistente a tentar
            # entregar novamente a mensagem QoS 1.
            try:
                client.disconnect()
            except Exception:
                pass

    def _database_loop(self):
        backoff = 1
        batch_size = self.cfg["batch_size"]
        compact_interval = self.cfg["compact_interval_seconds"]
        next_compact = time.monotonic() + 60

        while _running:
            now = time.monotonic()

            if now >= next_compact:
                try:
                    self.db.compact_history()
                    next_compact = time.monotonic() + compact_interval
                    backoff = 1
                except Exception:
                    self.log.exception(
                        "Falha na compactação histórica; nova tentativa em 60s"
                    )
                    self.db.close()
                    next_compact = time.monotonic() + 60

            batch = self.spool.pending(batch_size)
            if not batch:
                time.sleep(0.2)
                continue

            try:
                self.db.process_batch(batch)
                self.spool.delete([row["id"] for row in batch])
                backoff = 1
            except Exception:
                self.log.exception(
                    "Falha ao gravar lote no PostgreSQL; nova tentativa em %ss (spool=%d)",
                    backoff,
                    self.spool.count(),
                )
                self.db.close()
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

        self.db.close()

    def run(self):
        # O worker não pode depender do PostgreSQL para iniciar. Se o Neon
        # estiver indisponível, o MQTT continua recebendo e persistindo no
        # spool local; a thread de banco reconecta com backoff e drena o
        # backlog quando o PostgreSQL voltar.
        self.db_thread.start()

        mc = self.cfg["mqtt"]
        self.client.connect_async(mc["host"], mc["port"], keepalive=30)
        self.client.loop_start()

        self.log.info(
            "MotorView ingest worker iniciado; spool pendente=%d",
            self.spool.count(),
        )

        try:
            while _running:
                time.sleep(0.5)
        finally:
            # Não é necessário drenar tudo no shutdown: o spool é persistente.
            self.log.info(
                "Encerrando worker; spool persistente pendente=%d",
                self.spool.count(),
            )
            try:
                self.client.disconnect()
            except Exception:
                pass
            self.client.loop_stop()
            self.db_thread.join(timeout=10)
            self.db.close()
            self.spool.close()


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
