#!/usr/bin/env bash
# Instalador do MotorView Gateway no Raspberry Pi (Raspberry Pi OS / Debian).
# Sim, é tudo em Python puro - roda em qualquer Raspberry Pi com Python 3.9+
# (o Raspberry Pi OS já vem com Python 3 instalado).
#
# O que este script faz:
#   1. cria um ambiente virtual (.venv) dentro desta pasta;
#   2. instala as dependências (requirements.txt);
#   3. copia config.example.yaml -> config.yaml (se ainda não existir) para
#      você editar (porta serial, inversores, etc.);
#   4. adiciona seu usuário ao grupo "dialout" (permissão pra usar a porta
#      serial/USB do conversor RS-485 sem precisar de sudo);
#   5. opcionalmente instala e ativa o serviço systemd (roda sozinho no boot).
#
# Uso:
#   cd motorview/gateway
#   chmod +x install.sh
#   ./install.sh

set -euo pipefail
cd "$(dirname "$0")"

echo "==> Verificando Python 3..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 não encontrado. Instale com: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    exit 1
fi
python3 --version

echo "==> Criando ambiente virtual (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "==> Instalando dependências..."
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

if [ ! -f "config.yaml" ]; then
    echo "==> Criando config.yaml a partir de config.example.yaml (edite antes de rodar!)"
    cp config.example.yaml config.yaml
else
    echo "==> config.yaml já existe, mantendo como está."
fi

if [ ! -f ".env" ]; then
    echo "==> Nenhum .env encontrado nesta pasta - crie um com as credenciais do broker MQTT"
    echo "    (MOTORVIEW_MQTT_HOST, MOTORVIEW_MQTT_USERNAME, MOTORVIEW_MQTT_PASSWORD)."
fi

echo "==> Adicionando usuário '$USER' ao grupo dialout (acesso à porta serial sem sudo)..."
if ! groups "$USER" | grep -q '\bdialout\b'; then
    sudo usermod -aG dialout "$USER"
    echo "    Feito. É preciso encerrar a sessão e entrar de novo (ou reiniciar) para valer."
else
    echo "    Usuário já está no grupo dialout."
fi

echo ""
echo "==> Instalação concluída."
echo ""
echo "Próximos passos:"
echo "  1. Edite config.yaml (porta serial, inversores, host do broker MQTT)."
echo "  2. Edite .env com usuário/senha do broker MQTT."
echo "  3. Teste rodando manualmente:"
echo "       source .venv/bin/activate && python gateway.py"
echo ""

read -r -p "Instalar e ativar como serviço systemd (roda sozinho no boot)? [s/N] " resp
if [[ "$resp" =~ ^[sSyY]$ ]]; then
    SERVICE_PATH="/etc/systemd/system/motorview-gateway.service"
    GATEWAY_DIR="$(pwd)"
    echo "==> Gerando ${SERVICE_PATH} apontando para ${GATEWAY_DIR}..."
    sed \
        -e "s#/home/pi/motorview/gateway#${GATEWAY_DIR}#g" \
        -e "s#^User=pi#User=${USER}#" \
        motorview-gateway.service | sudo tee "$SERVICE_PATH" >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now motorview-gateway
    echo "==> Serviço ativo. Acompanhe com: journalctl -u motorview-gateway -f"
else
    echo "Ok, não instalei o serviço. Quando quiser, rode este script de novo e responda 's'."
fi
