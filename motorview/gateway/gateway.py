"""
MotorView Gateway - aquisição Modbus + armazenamento local + MQTT
=================================================================
Estratégia:
- telemetria completa: normalmente a cada 2 s;
- inversores críticos: corrente bruta local a cada 100 ms;
- MQTT de corrente rápida: agregado a cada 500 ms (min/max/média/última);
- falha do inversor crítico: checada rapidamente e, ao mudar, força snapshot
  completo incluindo histórico P0050..P0070;
- tudo com timestamp UTC em milissegundos;
- amostras brutas rápidas ficam no SQLite local, não no HiveMQ.
"""

import logging
import signal
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import ConfigError, load_config, register_map_path
from modbus_client import InverterReader, RegisterMap, build_serial_client
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
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _fault_payload(ts: str, inv_id: str, name: str, values: dict) -> dict:
    keys = (
        "fault_code", "fault_description",
        "last_fault_code", "last_fault_description",
        "last_fault_current_A", "last_fault_dc_link_V",
        "last_fault_frequency_Hz", "last_fault_igbt_temp_C",
        "last_fault_status_word", "last_fault_status_bits",
        "second_fault_code", "second_fault_description",
        "third_fault_code", "third_fault_description",
        "current_A", "dc_link_V", "frequency_Hz",
        "status_word", "status_bits",
    )
    payload = {
        "ts": ts,
        "inverter_id": inv_id,
        "name": name,
        "active": int(values.get("fault_code") or 0) != 0,
    }
    for key in keys:
        if key in values:
            payload[key] = values[key]
    return payload


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
        log.error(
            "Não foi possível abrir a porta serial %s.",
            cfg["serial"]["port"],
        )
        sys.exit(1)

    register_maps: dict[str, RegisterMap] = {}
    readers: dict[str, InverterReader] = {}
    inv_names: dict[str, str] = {}

    for inv in cfg["inverters"]:
        map_path = register_map_path(inv)
        if str(map_path) not in register_maps:
            register_maps[str(map_path)] = RegisterMap(map_path)
        readers[inv["id"]] = InverterReader(
            serial_client, inv["slave_id"], register_maps[str(map_path)]
        )
        inv_names[inv["id"]] = inv["name"]

    fast_cfg = cfg.get("fast_monitoring", {})
    fast_enabled = bool(fast_cfg.get("enabled", False))
    critical_ids = [
        inv_id for inv_id in fast_cfg.get("inverters", [])
        if inv_id in readers
    ]

    sample_interval = max(
        0.05, float(fast_cfg.get("current_sample_interval_ms", 100)) / 1000.0
    )
    publish_interval = max(
        sample_interval,
        float(fast_cfg.get("current_publish_interval_ms", 500)) / 1000.0,
    )
    fault_interval = max(
        0.1, float(fast_cfg.get("fault_poll_interval_ms", 250)) / 1000.0
    )
    raw_flush_interval = max(
        0.5, float(fast_cfg.get("raw_flush_interval_ms", 1000)) / 1000.0
    )

    store = LocalStore(
        cfg["local_log"]["db_path"],
        cfg["local_log"].get("retention_days", 90),
        fast_cfg.get("raw_retention_days", 7),
    )

    mqtt_enabled = cfg.get("mqtt", {}).get("enabled", True)
    mqtt_pub = None
    if mqtt_enabled:
        mqtt_pub = MqttPublisher(cfg["mqtt"], site_id)
        mqtt_pub.connect()

    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    full_interval = float(cfg.get("poll_interval_seconds", 2))
    comm_heartbeat = float(cfg.get("comm_error_heartbeat_seconds", 60))
    offline_retry = float(cfg.get("offline_retry_seconds", 30))

    last_fault_code: dict[str, int | None] = {inv_id: None for inv_id in readers}
    last_comm_error: dict[str, bool | None] = {inv_id: None for inv_id in readers}
    last_comm_publish: dict[str, float] = {inv_id: 0.0 for inv_id in readers}
    next_comm_retry: dict[str, float] = {inv_id: 0.0 for inv_id in readers}

    fast_windows: dict[str, list[dict]] = {inv_id: [] for inv_id in critical_ids}
    raw_buffer: list[dict] = []

    now_mono = time.monotonic()
    next_full = now_mono
    next_sample = now_mono
    next_fast_publish = now_mono + publish_interval
    next_fault_poll = now_mono
    next_raw_flush = now_mono + raw_flush_interval
    next_purge = now_mono + 3600

    if mqtt_enabled:
        log.info(
            "MotorView Gateway iniciado - site=%s, %d inversor(es), MQTT %s:%s",
            site_id, len(readers), cfg["mqtt"]["host"], cfg["mqtt"]["port"]
        )
    else:
        log.info(
            "MotorView Gateway iniciado em modo local - site=%s, %d inversor(es)",
            site_id, len(readers)
        )

    if fast_enabled and critical_ids:
        log.info(
            "Monitoramento rápido ativo em %s: corrente %.0f ms, MQTT %.0f ms, falha %.0f ms",
            ",".join(critical_ids),
            sample_interval * 1000,
            publish_interval * 1000,
            fault_interval * 1000,
        )

    while _running:
        now_mono = time.monotonic()

        # 1) Corrente crítica em alta frequência - uma leitura de registrador.
        if fast_enabled and critical_ids and now_mono >= next_sample:
            for inv_id in critical_ids:
                current = readers[inv_id].read_field("current_A")
                ts = now_iso()
                if current is not None:
                    sample = {
                        "ts": ts,
                        "inverter_id": inv_id,
                        "current_A": float(current),
                    }
                    raw_buffer.append(sample)
                    fast_windows[inv_id].append(sample)
            next_sample = time.monotonic() + sample_interval

        # 2) Detecção rápida de falha no(s) inversor(es) crítico(s).
        if fast_enabled and critical_ids and now_mono >= next_fault_poll:
            for inv_id in critical_ids:
                code = readers[inv_id].read_field("fault_code")
                if code is None:
                    continue
                code = int(code)
                previous = last_fault_code.get(inv_id)
                if previous is None:
                    last_fault_code[inv_id] = code
                elif code != previous:
                    last_fault_code[inv_id] = code
                    # A mudança força um snapshot completo imediatamente.
                    values = readers[inv_id].read()
                    if values is None:
                        values = {"fault_code": code}
                    ts = now_iso()
                    payload = _fault_payload(
                        ts, inv_id, inv_names[inv_id], values
                    )
                    topic = (
                        mqtt_pub.topic_fault(inv_id)
                        if mqtt_pub else f"local/{site_id}/{inv_id}/fault"
                    )
                    row_id = store.record_fault(inv_id, topic, payload)
                    if mqtt_pub and mqtt_pub.publish(topic, payload, retain=False):
                        store.mark_sent("fault_log", row_id)
                    elif not mqtt_pub:
                        store.mark_sent("fault_log", row_id)
                    log.warning(
                        "Mudança de falha %s: %s -> %s",
                        inv_id, previous, code
                    )
            next_fault_poll = time.monotonic() + fault_interval

        # 3) Publicação agregada da corrente rápida.
        if fast_enabled and critical_ids and now_mono >= next_fast_publish:
            for inv_id in critical_ids:
                window = fast_windows[inv_id]
                if not window:
                    continue
                vals = [s["current_A"] for s in window]
                payload = {
                    "ts": now_iso(),
                    "window_start": window[0]["ts"],
                    "window_end": window[-1]["ts"],
                    "inverter_id": inv_id,
                    "name": inv_names[inv_id],
                    "current_A": vals[-1],
                    "current_min_A": round(min(vals), 4),
                    "current_max_A": round(max(vals), 4),
                    "current_avg_A": round(statistics.fmean(vals), 4),
                    "samples": len(vals),
                    "sample_interval_ms": int(round(sample_interval * 1000)),
                }
                topic = (
                    mqtt_pub.topic_fast_current(inv_id)
                    if mqtt_pub else f"local/{site_id}/{inv_id}/current_fast"
                )
                row_id = store.record_fast_current(inv_id, topic, payload)
                if mqtt_pub and mqtt_pub.publish(topic, payload, retain=False):
                    store.mark_sent("fast_current_log", row_id)
                elif not mqtt_pub:
                    store.mark_sent("fast_current_log", row_id)
                fast_windows[inv_id] = []
            next_fast_publish = time.monotonic() + publish_interval

        # 4) Flush em lote das amostras brutas locais.
        if raw_buffer and now_mono >= next_raw_flush:
            store.record_current_samples(raw_buffer)
            raw_buffer = []
            next_raw_flush = time.monotonic() + raw_flush_interval

        # 5) Telemetria completa.
        if now_mono >= next_full:
            for inv_id, reader in readers.items():
                now_try = time.monotonic()

                # Se o slave já foi confirmado offline, não deixe ele bloquear a
                # mesma serial a cada ciclo de 2 s. Tenta novamente apenas no
                # intervalo configurado (ex.: 30 s). O estado de erro continua
                # sendo publicado por heartbeat sem novas tentativas Modbus.
                if last_comm_error[inv_id] is True and now_try < next_comm_retry[inv_id]:
                    if now_try - last_comm_publish[inv_id] >= comm_heartbeat:
                        ts = now_iso()
                        payload = {
                            "ts": ts,
                            "inverter_id": inv_id,
                            "name": inv_names[inv_id],
                            "comm_error": True,
                        }
                        topic = (
                            mqtt_pub.topic_telemetry(inv_id)
                            if mqtt_pub else f"local/{site_id}/{inv_id}/telemetry"
                        )
                        row_id = store.record_telemetry(inv_id, topic, payload)
                        if mqtt_pub and mqtt_pub.publish(topic, payload, retain=True):
                            store.mark_sent("telemetry_log", row_id)
                        elif not mqtt_pub:
                            store.mark_sent("telemetry_log", row_id)
                        last_comm_publish[inv_id] = now_try
                    continue

                values = reader.read()
                ts = now_iso()

                if values is None:
                    now_err = time.monotonic()
                    should_publish = (
                        last_comm_error[inv_id] is not True
                        or now_err - last_comm_publish[inv_id] >= comm_heartbeat
                    )
                    last_comm_error[inv_id] = True
                    next_comm_retry[inv_id] = now_err + offline_retry
                    if should_publish:
                        payload = {
                            "ts": ts,
                            "inverter_id": inv_id,
                            "name": inv_names[inv_id],
                            "comm_error": True,
                        }
                        topic = (
                            mqtt_pub.topic_telemetry(inv_id)
                            if mqtt_pub else f"local/{site_id}/{inv_id}/telemetry"
                        )
                        row_id = store.record_telemetry(inv_id, topic, payload)
                        if mqtt_pub and mqtt_pub.publish(topic, payload, retain=True):
                            store.mark_sent("telemetry_log", row_id)
                        elif not mqtt_pub:
                            store.mark_sent("telemetry_log", row_id)
                        last_comm_publish[inv_id] = now_err
                    log.warning(
                        "%s sem resposta Modbus; nova tentativa em %.0f s",
                        inv_id, offline_retry
                    )
                    continue

                recovered = last_comm_error[inv_id] is True
                last_comm_error[inv_id] = False
                next_comm_retry[inv_id] = 0.0

                payload = {
                    "ts": ts,
                    "inverter_id": inv_id,
                    "name": inv_names[inv_id],
                    "comm_error": False,
                    **values,
                }
                topic = (
                    mqtt_pub.topic_telemetry(inv_id)
                    if mqtt_pub else f"local/{site_id}/{inv_id}/telemetry"
                )
                row_id = store.record_telemetry(inv_id, topic, payload)
                if mqtt_pub and mqtt_pub.publish(topic, payload, retain=True):
                    store.mark_sent("telemetry_log", row_id)
                elif not mqtt_pub:
                    store.mark_sent("telemetry_log", row_id)

                if recovered:
                    log.info("%s comunicação restabelecida", inv_id)

                # Para inversores não críticos (ou como redundância), detecta
                # mudança de falha também na telemetria completa.
                code = int(values.get("fault_code") or 0)
                previous = last_fault_code.get(inv_id)
                if previous is None:
                    last_fault_code[inv_id] = code
                elif code != previous:
                    last_fault_code[inv_id] = code
                    fault_payload = _fault_payload(
                        ts, inv_id, inv_names[inv_id], values
                    )
                    fault_topic = (
                        mqtt_pub.topic_fault(inv_id)
                        if mqtt_pub else f"local/{site_id}/{inv_id}/fault"
                    )
                    frow_id = store.record_fault(inv_id, fault_topic, fault_payload)
                    if mqtt_pub and mqtt_pub.publish(
                        fault_topic, fault_payload, retain=False
                    ):
                        store.mark_sent("fault_log", frow_id)
                    elif not mqtt_pub:
                        store.mark_sent("fault_log", frow_id)

            next_full = time.monotonic() + full_interval

        # 6) Outbox: reenvia agregados/telemetria/falhas quando a internet volta.
        if mqtt_pub and mqtt_pub.connected:
            for table in ("telemetry_log", "fault_log", "fast_current_log"):
                for row in store.pending(table):
                    retain = table == "telemetry_log"
                    if mqtt_pub.publish(row["topic"], row["payload"], retain=retain):
                        store.mark_sent(table, row["id"])

        if now_mono >= next_purge:
            store.purge_old()
            next_purge = time.monotonic() + 3600

        # Scheduler leve; as chamadas Modbus são síncronas, então este sleep
        # não tenta criar concorrência na mesma serial.
        time.sleep(0.005)

    log.info("Encerrando MotorView Gateway...")
    if raw_buffer:
        store.record_current_samples(raw_buffer)
    if mqtt_pub:
        mqtt_pub.disconnect()
    store.close()
    serial_client.close()


if __name__ == "__main__":
    main()
