# MotorView - ENDTECH

Sistema de monitoramento de motores/inversores em tempo real: lê os
inversores via **Modbus RTU** (RS-485) num Raspberry Pi, publica na nuvem via
**MQTT** e mostra num dashboard web (Streamlit) com gráfico de corrente,
registro de falhas e histórico gravado em banco.

Pasta separada do [`prodview/`](../prodview/README.md) (contagem de botijão)
de propósito - são dois produtos diferentes - mas segue a mesma linha visual
e o mesmo padrão de arquitetura (camada `db.py` isolada, fácil trocar SQLite
por uma base definitiva depois).

## Arquitetura

```
┌─────────────────────────┐        MQTT (TLS)        ┌───────────────────────────┐
│  Raspberry Pi            │  ────────────────────▶  │  Broker MQTT na nuvem      │
│  motorview/gateway/       │   telemetria + falhas    │  (HiveMQ Cloud free tier   │
│                            │   + status (LWT)          │   ou outro de sua escolha) │
│  Modbus RTU (RS-485)      │                           └──────────────┬─────────────┘
│  ◀──────────────▶          │                                          │
│  Inversores WEG CFW-500    │                                          │ MQTT (assinante)
│  (1 slave_id por inversor) │                                          ▼
│                            │                           ┌───────────────────────────┐
│  + log local (SQLite),     │                           │  motorview/dashboard/       │
│    reenvia o que não foi   │                           │  Streamlit, publicado no    │
│    confirmado ao MQTT      │                           │  Streamlit Community Cloud  │
└─────────────────────────┘                           │  - Corrente em tempo real   │
                                                          │  - Registro de falhas       │
                                                          │  - Histórico + export CSV   │
                                                          └───────────────────────────┘
```

## Onde começar

1. **[gateway/README.md](gateway/README.md)** - instalar no Raspberry Pi,
   ligar o RS-485 nos inversores, criar o broker MQTT (passo a passo com
   HiveMQ Cloud free) e deixar rodando como serviço (systemd).
2. **[dashboard/README.md](dashboard/README.md)** - rodar localmente e/ou
   publicar no Streamlit Community Cloud, apontando pro mesmo broker.

## Convenção de tópicos MQTT

```
motorview/<site_id>/<inverter_id>/telemetry   (retained) - leitura periódica
motorview/<site_id>/<inverter_id>/fault       - só quando o código de falha muda
motorview/<site_id>/gateway/status            (retained) - online/offline (Last Will)
```

`site_id` e `inverter_id` são definidos em [`gateway/config.yaml`](gateway/config.example.yaml).

## Decisões já tomadas (e como mudar depois)

- **Inversor**: mapa de registradores inicial para **WEG CFW-500**
  ([`gateway/registers_weg_cfw500.yaml`](gateway/registers_weg_cfw500.yaml)) -
  confirme os endereços com a HMI do inversor antes de confiar 100% neles
  (ver aviso no topo do arquivo). Outra marca/modelo: crie um novo YAML no
  mesmo formato e aponte `register_map:` para ele.
- **Broker MQTT**: instruções prontas para **HiveMQ Cloud (free tier)**,
  mas qualquer broker com usuário/senha + TLS funciona só trocando
  host/porta/credenciais na configuração - não há nada hardcoded específico
  da HiveMQ no código.
- **Banco de dados**: SQLite local dos dois lados (Pi e dashboard) para essa
  primeira versão funcionar sem depender de infraestrutura extra. O ponto de
  troca para uma base definitiva (Postgres, por exemplo) é só a função
  `get_conn()` em cada `db.py` - igual ao padrão já usado no ProdView.

## Próximos passos sugeridos

- Confirmar/ajustar os endereços Modbus com o manual do firmware real dos
  inversores em campo.
- Autenticação de usuários no dashboard (hoje é um link público).
- Alertas (e-mail/WhatsApp/Telegram) quando uma falha é publicada.
- Migrar para Postgres (Supabase/Neon) se precisar de histórico contínuo
  sem lacunas durante hibernação do Streamlit Cloud gratuito.
