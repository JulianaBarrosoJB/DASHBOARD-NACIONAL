"""MotorView - ingest cloud de contingência HiveMQ -> Neon.

Usado apenas quando o ingest primário do Raspberry estiver indisponível.
Cada mensagem espera alguns segundos antes de tentar gravar. Se o primário
já tiver persistido a mesma chave, o failover não escreve nada.

As tabelas operacionais também possuem UNIQUE + ON CONFLICT DO NOTHING,
criando uma segunda barreira contra duplicidade.
"""

import json
import logging
import queue
import ssl
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import psycopg

log = logging.getLogger("motorview.cloud_failover")

INVERTER_NAMES = {"inv01": "MOTOR 42", "inv02": "MOTOR 44"}


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class CloudFailoverIngest:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.q = queue.Queue(maxsize=5000)
        self.running = True
        self.connected = False
        self.last_message_at = None
        self.last_insert_at = None
        self.last_primary_seen_at = None
        self.inserted = 0
        self.skipped_existing = 0
        self.errors = 0

        mc = cfg["mqtt"]
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION1,
            client_id=mc.get("client_id", "motorview-cloud-failover-planta1"),
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        self.client.username_pw_set(mc["username"], mc["password"])
        self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self.worker = threading.Thread(target=self._db_loop, daemon=True, name="motorview-cloud-failover-db")

    def start(self):
        self.worker.start()
        mc = self.cfg["mqtt"]
        self.client.connect_async(mc["host"], mc.get("port", 8883), keepalive=30)
        self.client.loop_start()
        log.warning("Cloud failover ingest ATIVO")

    def stop(self):
        self.running = False
        try:
            self.client.disconnect()
            self.client.loop_stop()
        except Exception:
            pass

    def status(self):
        return {
            "connected": self.connected,
            "last_message_at": self.last_message_at,
            "last_insert_at": self.last_insert_at,
            "last_primary_seen_at": self.last_primary_seen_at,
            "inserted": self.inserted,
            "skipped_existing": self.skipped_existing,
            "errors": self.errors,
            "queue": self.q.qsize(),
        }

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0
        if rc == 0:
            client.subscribe(self.cfg["mqtt"].get("topic_filter", "motorview/planta1/#"), qos=1)
            log.info("Failover MQTT conectado")
        else:
            log.error("Failover MQTT conexão recusada rc=%s", rc)

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        # connectivity fica exclusivamente com o ingest primário: a tabela
        # atual não tem chave UNIQUE e não queremos duplicidade nessa trilha.
        if msg.topic.endswith("/gateway/status"):
            return
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                return
            self.last_message_at = datetime.now(timezone.utc)
            item = {
                "topic": msg.topic,
                "payload": payload,
                "received_at": _now_iso(),
                "due": time.monotonic() + self.cfg.get("primary_grace_seconds", 4.0),
            }
            self.q.put_nowait(item)
        except queue.Full:
            self.errors += 1
            log.error("Fila do failover cheia; mensagem não enfileirada")
        except Exception:
            self.errors += 1
            log.exception("Falha ao receber mensagem do failover")

    def _db_loop(self):
        conn = None
        while self.running:
            try:
                item = self.q.get(timeout=0.5)
            except queue.Empty:
                continue

            wait = item["due"] - time.monotonic()
            if wait > 0:
                time.sleep(wait)

            try:
                if conn is None or conn.closed:
                    conn = psycopg.connect(
                        self.cfg["database_url"],
                        autocommit=True,
                        connect_timeout=10,
                        application_name="motorview-cloud-failover",
                    )
                inserted = self._persist(conn, item)
                if inserted:
                    self.inserted += 1
                    self.last_insert_at = datetime.now(timezone.utc)
                else:
                    # O registro já existir após a janela de graça é o sinal
                    # de que o ingest primário voltou e chegou antes do failover.
                    self.skipped_existing += 1
                    self.last_primary_seen_at = datetime.now(timezone.utc)
            except Exception:
                self.errors += 1
                log.exception("Falha ao persistir no Neon pelo failover")
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                conn = None
                # recoloca a mensagem; UNIQUE impede duplicidade se a transação
                # tiver sido confirmada antes de uma falha de rede na resposta.
                item["due"] = time.monotonic() + 5
                try:
                    self.q.put_nowait(item)
                except queue.Full:
                    log.error("Fila cheia ao tentar reenfileirar mensagem")

    def _persist(self, conn, item) -> bool:
        topic, p, received_at = item["topic"], item["payload"], item["received_at"]
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != "motorview":
            return False
        site_id, inverter_id, kind = parts[1], parts[2], parts[3]
        if kind not in {"telemetry", "current_fast", "fault"}:
            return False
        ts = p.get("ts") or received_at

        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO motorview.inverters(site_id,inverter_id,name,active)
                    VALUES (%s,%s,%s,TRUE)
                    ON CONFLICT (site_id,inverter_id)
                    DO UPDATE SET name=EXCLUDED.name,active=TRUE,updated_at=NOW()
                    """,
                    (site_id, inverter_id, INVERTER_NAMES.get(inverter_id, p.get("name") or inverter_id)),
                )

                if kind == "telemetry":
                    cur.execute(
                        """
                        INSERT INTO motorview.telemetry (
                          site_id,inverter_id,ts,comm_error,speed_rpm,current_a,dc_link_v,
                          frequency_hz,voltage_v,torque_pct,status_word,fault_code,
                          last_fault_code,last_fault_description,last_fault_current_a,
                          last_fault_dc_link_v,last_fault_frequency_hz,last_fault_igbt_temp_c,
                          last_fault_status_word,second_fault_code,second_fault_description,
                          third_fault_code,third_fault_description,status_bits,payload,received_at
                        ) VALUES (
                          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          %s,%s,%s,%s,%s::jsonb,%s::jsonb,%s
                        )
                        ON CONFLICT (site_id,inverter_id,ts) DO NOTHING
                        RETURNING id
                        """,
                        (
                            site_id,inverter_id,ts,bool(p.get("comm_error",False)),
                            p.get("speed_rpm"),p.get("current_A"),p.get("dc_link_V"),
                            p.get("frequency_Hz"),p.get("voltage_V"),p.get("torque_pct"),
                            p.get("status_word"),p.get("fault_code"),p.get("last_fault_code"),
                            p.get("last_fault_description"),p.get("last_fault_current_A"),
                            p.get("last_fault_dc_link_V"),p.get("last_fault_frequency_Hz"),
                            p.get("last_fault_igbt_temp_C"),p.get("last_fault_status_word"),
                            p.get("second_fault_code"),p.get("second_fault_description"),
                            p.get("third_fault_code"),p.get("third_fault_description"),
                            json.dumps(p.get("status_bits")) if p.get("status_bits") is not None else None,
                            json.dumps(p,ensure_ascii=False),received_at,
                        ),
                    )
                elif kind == "current_fast":
                    cur.execute(
                        """
                        INSERT INTO motorview.current_fast (
                          site_id,inverter_id,ts,window_start,window_end,current_a,current_min_a,
                          current_max_a,current_avg_a,samples,sample_interval_ms,payload,received_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                        ON CONFLICT (site_id,inverter_id,ts) DO NOTHING
                        RETURNING id
                        """,
                        (
                            site_id,inverter_id,ts,p.get("window_start"),p.get("window_end"),
                            p.get("current_A"),p.get("current_min_A"),p.get("current_max_A"),
                            p.get("current_avg_A"),p.get("samples"),p.get("sample_interval_ms"),
                            json.dumps(p,ensure_ascii=False),received_at,
                        ),
                    )
                else:
                    active = bool(p.get("active", int(p.get("fault_code") or 0) != 0))
                    event_type = "fault_active" if active else "fault_cleared"
                    cur.execute(
                        """
                        INSERT INTO motorview.faults (
                          site_id,inverter_id,ts,fault_code,fault_description,event_type,current_a,
                          dc_link_v,frequency_hz,igbt_temp_c,status_word,payload,received_at
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                        ON CONFLICT (site_id,inverter_id,ts,fault_code,event_type) DO NOTHING
                        RETURNING id
                        """,
                        (
                            site_id,inverter_id,ts,int(p.get("fault_code") or 0),
                            p.get("fault_description"),event_type,p.get("current_A"),
                            p.get("dc_link_V"),p.get("frequency_Hz"),p.get("last_fault_igbt_temp_C"),
                            p.get("status_word"),json.dumps(p,ensure_ascii=False),received_at,
                        ),
                    )
                return cur.fetchone() is not None
