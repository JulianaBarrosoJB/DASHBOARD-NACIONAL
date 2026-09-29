# MotorView Gateway (Raspberry Pi)

Serviço em Python que roda no Raspberry Pi, lê os inversores WEG (CFW-500 por
padrão, configurável) via **Modbus RTU / RS-485**, grava tudo localmente
(SQLite) e publica na nuvem via **MQTT** para o [dashboard](../dashboard/README.md)
consumir em tempo real.

## 1. Hardware

- Raspberry Pi (qualquer modelo com USB ou GPIO UART) com Raspberry Pi OS.
- Conversor **USB-RS485** (mais simples, aparece como `/dev/ttyUSB0`) ou um
  módulo RS-485 ligado direto nos pinos GPIO UART (`/dev/ttyAMA0` ou
  `/dev/serial0` - nesse caso é preciso desabilitar o console serial em
  `raspi-config` -> Interface Options -> Serial Port -> login shell: No,
  hardware: Yes).
- Ligação RS-485: **A/D+** e **B/D-** do conversor nos bornes A e B do
  inversor. No CFW500: **P0308 = endereço/slave ID**, **P0310 = baud rate**,
  **P0311 = formato dos bytes/paridade**, **P0312 = protocolo (2 = Modbus RTU)**,
  **P0313 = ação em erro de comunicação** e **P0314 = watchdog serial**. Todos os inversores no mesmo barramento compartilham A/B,
  cada um com um `slave_id` diferente.
- Resistor de terminação de 120 Ω nas duas pontas do barramento RS-485 se o
  cabo for longo (> ~15 m) ou houver muito ruído elétrico.

### Tela de boot sem o logo do Raspberry (opcional)

Se um monitor for conectado ao Pi em algum momento (ex.: instalação, suporte
técnico) e você não quer que apareça a telinha arco-íris/logo do Raspberry
Pi OS, dá pra desativar em 1 minuto:

```bash
sudo raspi-config
# System Options -> Boot / Auto Login -> Console (sem logo)
# Display Options -> Boot Splash Screen -> Disable (Bookworm)
```

Ou direto pelos arquivos de boot (funciona por SSH, sem precisar de monitor):

```bash
sudo raspi-config nonint do_boot_splash 1     # desativa a splash arco-íris
```

E para também silenciar as mensagens de texto do kernel na tela (deixa a
tela preta em vez de rolar log de boot), edite `/boot/firmware/cmdline.txt`
(**tudo numa linha só**, sem quebrar) acrescentando ao final:

```
quiet loglevel=0 logo.nologo vt.global_cursor_default=0
```

Reinicie (`sudo reboot`) para valer. **Importante**: isso só afeta o que
aparece numa tela conectada ao Pi - não muda nada no hardware (a placa
continua com "Raspberry Pi" escrito nela, e o endereço MAC da porta de rede
tem um prefixo público registrado à Raspberry Pi Foundation, então um scan
de rede ainda identifica o fabricante). Para esconder de verdade fisicamente
e na rede, seria preciso um invólucro fechado e trocar o MAC address - não é
algo que a escolha do sistema operacional resolve.

## 2. Instalação

É tudo em Python puro - roda em qualquer Raspberry Pi com Python 3.9+ (o
Raspberry Pi OS já vem com Python 3 de fábrica), sem precisar de nenhuma
outra linguagem/runtime.

```bash
cd ~
git clone <url-do-seu-repositorio> motorview-src   # ou copie a pasta motorview/ pro Pi
cd motorview-src/motorview/gateway
```

**Caminho rápido (recomendado)** - o script abaixo cria o ambiente virtual,
instala as dependências, copia `config.example.yaml` -> `config.yaml`,
libera a porta serial pro seu usuário (grupo `dialout`) e, se você quiser,
já deixa instalado como serviço systemd (seção 5):

```bash
chmod +x install.sh
./install.sh
```

**Ou manualmente**, se preferir:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Depois (nos dois caminhos), edite `config.yaml`:

- `serial.port`: `/dev/ttyUSB0` (conversor USB) ou `/dev/ttyAMA0` (GPIO).
- `serial.baudrate` / `parity`: têm que bater com P0310/P0311 do CFW500.
  No padrão de fábrica: 19200 bit/s, 8E1. No teste atual com o AS320P-B:
  9600 bit/s, 8N1.
- `inverters`: um item por inversor no barramento, com `slave_id` único.
- `mqtt.host` / `mqtt.port`: dados do seu broker (veja seção 3).

**Nunca** coloque a senha do MQTT direto no `config.yaml` se for versionar o
repositório. Esta pasta já vem com um arquivo `.env` pronto para você
preencher (`config.py` lê essas variáveis e sobrescreve o `config.yaml`
automaticamente):

```
MOTORVIEW_MQTT_HOST=xxxxxxxx.s1.eu.hivemq.cloud
MOTORVIEW_MQTT_PORT=8883
MOTORVIEW_MQTT_USERNAME=motorview-gateway
MOTORVIEW_MQTT_PASSWORD=sua-senha-aqui
```

(`config.yaml` e `.env` já estão no `.gitignore` desta pasta - pode colocar
a senha de verdade sem risco de subir pro GitHub.)

## 3. Broker MQTT - HiveMQ Cloud (free tier)

1. Crie uma conta grátis em <https://www.hivemq.com/mqtt-cloud-broker/>.
2. Crie um **cluster free** (fica pronto em ~1 min) - anote o **host**
   (algo como `xxxxxxxx.s1.eu.hivemq.cloud`), a porta TLS é sempre `8883`.
3. Em "Access Management" -> "Manage Credentials", crie um usuário/senha
   (ex.: `motorview-gateway`) - é o que vai no `.env` acima.
4. Repita a criação de outro usuário (ex.: `motorview-dashboard`, só leitura
   se o plano permitir) para o [dashboard](../dashboard/README.md) usar.
5. Teste rápido com `mosquitto_sub` (se tiver o `mosquitto-clients`
   instalado): 
   ```bash
   mosquitto_sub -h xxxxxxxx.s1.eu.hivemq.cloud -p 8883 --capath /etc/ssl/certs \
     -u motorview-gateway -P 'sua-senha' -t 'motorview/#' -v
   ```

Se preferir outro broker (EMQX Cloud, ThingsBoard, Mosquitto próprio, AWS IoT
Core), só troque `mqtt.host`/`mqtt.port`/credenciais em `config.yaml` - o
código não depende de HiveMQ especificamente. Só o AWS IoT Core foge um pouco
do padrão usuário/senha (usa certificados por dispositivo); avise se for essa
a opção que quiser usar que eu ajusto `mqtt_publisher.py`.

## 4. Rodar

```bash
python gateway.py
```

Deve aparecer no log algo como `Conectado ao broker MQTT ...` e, a cada
`poll_interval_seconds`, uma leitura por inversor. `Ctrl+C` encerra
graciosamente (fecha porta serial, desconecta do MQTT).

## 5. Rodar sempre, como serviço (systemd)

Se você já respondeu "s" no `install.sh` (seção 2), isso já está feito -
pule para o `journalctl` abaixo. Senão, manualmente:

```bash
sudo cp motorview-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now motorview-gateway
sudo systemctl status motorview-gateway
journalctl -u motorview-gateway -f     # acompanhar o log ao vivo
```

Ajuste `WorkingDirectory`/`ExecStart`/`User` no `.service` se copiou o
projeto para outro caminho/usuário que não `/home/pi/motorview/gateway`
(o `install.sh` já faz esse ajuste automaticamente).

## 6. O que ele publica

Para cada inversor (`site_id` e `inverter_id` vêm do `config.yaml`):

- `motorview/<site_id>/<inverter_id>/telemetry` (retained) - JSON com
  `ts, current_A, voltage_V, frequency_Hz, speed_rpm, torque_pct, dc_link_V,
  status_word, status_bits, fault_code, fault_description, comm_error`.
- `motorview/<site_id>/<inverter_id>/fault` - publicado só quando o código
  de falha muda (inclusive quando volta a zero = falha resetada).
- `motorview/<site_id>/gateway/status` (retained) - `{"status":"online"}` ao
  conectar, e `{"status":"offline"}` automaticamente (Last Will) se o
  gateway cair ou perder a conexão.

## 7. Sobre os endereços Modbus do CFW-500

O arquivo [`registers_weg_cfw500.yaml`](registers_weg_cfw500.yaml) traz um
mapa **best-effort** dos parâmetros mais comuns (corrente, tensão,
frequência, rpm, palavra de status, código de falha) usando a convenção de
fábrica do CFW-500 (endereço Modbus = número do parâmetro). **Confirme os
valores comparando com a HMI do inversor antes de usar em produção** -
podem variar por firmware/variante. Se usar outra marca/modelo, crie um
novo arquivo de mapa (mesmo formato) e aponte `register_map:` para ele em
`config.yaml`.
