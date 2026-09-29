"""
MotorView Gateway - loop principal
=====================================
Roda no Raspberry Pi. A cada ciclo:
  1. lê todos os inversores configurados via Modbus RTU (RS-485);
  2. grava cada leitura no log local (SQLite) - nunca perde dado, mesmo
     sem internet;
  3. publica a telemetria no MQTT (tópico retained, uma mensagem por
     inversor);
  4. se o código de falha mudou (e é diferente de zero), publica um
     evento de falha separado, para o dashboard registrar no histórico
     de falhas mesmo que a leitura seguinte já esteja "normal";
  5. tenta reenviar qualquer linha do log local que não tenha sido
     confirmada como publicada (proteção contra queda de link MQTT).

Uso:
    cd motorview/gateway
    cp config.example.yaml config.yaml   # e edite
    pip install -r requirements.txt
    python gateway.py
"""

import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import load_config, register_map_path, ConfigError
from modbus_client import RegisterMap, InverterReader, build_serial_client
from mqtt_publisher import MqttPublisher
from storage import LocalStore

_running = True


def _handle_stop(signum, frame):
    global _running
    _running = False


def setup_logging(logging_cfg: dict):
    level = getattr(logging, logging_cfg.get("level", "INFO").upper(), logging.INFO)
    handlers = [logging.StreamHandler(sys.stdout)]
    log_file = logging_cfg.get("file")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        sys.exit(1)

    setup_logging(cfg.get("logging", {}))
    log = logging.getLogger("motorview.gateway")

    site_id = cfg["site_id"]
    serial_client = build_serial_client(cfg["serial"])
    if not serial_client.connect():
        log.error("Não foi possível abrir a porta serial %s - verifique o cabo/adaptador RS-485.", cfg["serial"]["port"])
        sys.exit(1)

    register_maps: dict[str, RegisterMap] = {}
    readers: dict[str, InverterReader] = {}
    for inv in cfg["inverters"]:
        map_path = register_map_path(inv)
        if str(map_path) not in register_maps:
            register_maps[str(map_path)] = RegisterMap(map_path)
        readers[inv["id"]] = InverterReader(serial_client, inv["slave_id"], register_maps[str(map_path)])

    store = LocalStore(cfg["local_log"]["db_path"], cfg["local_log"].get("retention_days", 90))

    mqtt_enabled = cfg.get("mqtt", {}).get("enabled", True)
    mqtt_pub = None
    if mqtt_enabled:
        mqtt_pub = MqttPublisher(cfg["mqtt"], site_id)
        mqtt_pub.connect()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    last_fault_code: dict[str, int] = {inv["id"]: 0 for inv in cfg["inverters"]}
    inv_names = {inv["id"]: inv["name"] for inv in cfg["inverters"]}
    poll_interval = cfg.get("poll_interval_seconds", 2)
    last_purge = time.monotonic()

    if mqtt_enabled:
        log.info(
            "MotorView Gateway iniciado - site=%s, %d inversor(es), publicando em %s:%s",
            site_id, len(readers), cfg["mqtt"]["host"], cfg["mqtt"]["port"]
        )
    else:
        log.info(
            "MotorView Gateway iniciado em modo local - site=%s, %d inversor(es), MQTT desabilitado",
            site_id, len(readers)
        )

    while _running:
        cycle_start = time.monotonic()

        for inv_id, reader in readers.items():
            values = reader.read()
            ts = now_iso()
            if values is None:
                # falha de comunicação Modbus - registra como evento de conectividade,
                # o dashboard mostra o inversor como "sem leitura" até voltar.
                payload = {"ts": ts, "inverter_id": inv_id, "name": inv_names[inv_id], "comm_error": True}
                topic = mqtt_pub.topic_telemetry(inv_id) if mqtt_pub else f"local/{site_id}/{inv_id}/telemetry"
                store.record_telemetry(inv_id, topic, payload)
                if mqtt_pub:
                    mqtt_pub.publish(topic, payload, retain=True)
                log.warning("%s sem resposta Modbus", inv_id)
                continue

            payload = {"ts": ts, "inverter_id": inv_id, "name": inv_names[inv_id], "comm_error": False, **values}

            topic = mqtt_pub.topic_telemetry(inv_id) if mqtt_pub else f"local/{site_id}/{inv_id}/telemetry"
            row_id = store.record_telemetry(inv_id, topic, payload)

            if mqtt_pub:
                if mqtt_pub.publish(topic, payload, retain=True):
                    store.mark_sent("telemetry_log", row_id)
            else:
                store.mark_sent("telemetry_log", row_id)

            log.info("%s leitura: %s", inv_id, values)

            fault_code = int(values.get("fault_code") or 0)
            if fault_code != last_fault_code[inv_id]:
                last_fault_code[inv_id] = fault_code
                fault_payload = {
                    "ts": ts,
                    "inverter_id": inv_id,
                    "name": inv_names[inv_id],
                    "fault_code": fault_code,
                    "fault_description": values.get("fault_description"),
                    "active": fault_code != 0,
                }
                fault_topic = mqtt_pub.topic_fault(inv_id) if mqtt_pub else f"local/{site_id}/{inv_id}/fault"
                frow_id = store.record_fault(inv_id, fault_topic, fault_payload)
                if mqtt_pub:
                    if mqtt_pub.publish(fault_topic, fault_payload, retain=False):
                        store.mark_sent("fault_log", frow_id)
                else:
                    store.mark_sent("fault_log", frow_id)
                if fault_code:
                    log.warning("Falha detectada em %s: %s", inv_id, fault_payload["fault_description"])
                else:
                    log.info("Falha em %s foi resetada", inv_id)

        # reenvia o que ficou pendente de ciclos anteriores (queda de MQTT)
        if mqtt_pub and mqtt_pub.connected:
            for row in store.pending("telemetry_log"):
                if mqtt_pub.publish(row["topic"], row["payload"], retain=True):
                    store.mark_sent("telemetry_log", row["id"])
            for row in store.pending("fault_log"):
                if mqtt_pub.publish(row["topic"], row["payload"], retain=False):
                    store.mark_sent("fault_log", row["id"])

        if time.monotonic() - last_purge > 3600:
            store.purge_old()
            last_purge = time.monotonic()

        elapsed = time.monotonic() - cycle_start
        time.sleep(max(0.0, poll_interval - elapsed))

    log.info("Encerrando MotorView Gateway...")
    if mqtt_pub:
        mqtt_pub.disconnect()
    store.close()
    serial_client.close()


if __name__ == "__main__":
    main()
