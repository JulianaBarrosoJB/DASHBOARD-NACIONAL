# MotorView Ingest Worker

Worker independente do Streamlit que assina o HiveMQ Cloud e persiste os
dados do MotorView no PostgreSQL/Neon.

## Fluxo

CFW500 -> Raspberry Gateway -> HiveMQ -> este worker -> Neon PostgreSQL

Tópicos tratados:

- motorview/<site>/<inverter>/telemetry -> motorview.telemetry
- motorview/<site>/<inverter>/current_fast -> motorview.current_fast
- motorview/<site>/<inverter>/fault -> motorview.faults
- motorview/<site>/gateway/status -> motorview.connectivity

As amostras brutas de corrente de ~100 ms continuam locais no gateway e
não passam por este worker. O sincronismo raw será implementado em lote,
separadamente.

## Configuração

Crie um .env a partir de .env.example. Nunca versione senhas.

A credencial MQTT deve ser de assinatura (subscribe-only). A credencial
PostgreSQL deve ter somente CONNECT no banco, USAGE no schema motorview e
as permissões necessárias de SELECT/INSERT/UPDATE nas tabelas.

## Execução

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python worker.py

O worker usa uma sessão MQTT persistente (clean_session=False), QoS 1,
fila em memória entre MQTT e PostgreSQL, reconexão MQTT e retry do banco
com backoff. Inserts de telemetria/corrente/falha são idempotentes pelas
constraints UNIQUE da Migration 001.
