#!/usr/bin/env bash
#
# setup_servidor.sh — Se corre UNA SOLA VEZ, DENTRO del servidor de Oracle (Ubuntu).
# Deja el bot instalado y corriendo como servicio (systemd), que arranca solo
# con el servidor y se reinicia si se cae.
#
# Uso:
#   cd ~/bot-trading
#   bash deploy/setup_servidor.sh
#
set -euo pipefail

echo "==> Actualizando el sistema e instalando Python..."
sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip

# --- Swap de 2 GB (red de seguridad: la VM free tiene solo 1 GB de RAM) ---
if [ ! -f /swapfile ]; then
  echo "==> Creando 2 GB de swap (por si pandas/numpy piden más memoria)..."
  sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "==> Creando entorno virtual e instalando dependencias..."
cd "$HOME/bot-trading"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "==> Instalando el servicio systemd..."
sudo cp deploy/bot-trading.service /etc/systemd/system/bot-trading.service
sudo systemctl daemon-reload
sudo systemctl enable --now bot-trading

echo "==> Estado del bot:"
sudo systemctl status bot-trading --no-pager || true

echo ""
echo "Listo. Comandos útiles:"
echo "  sudo systemctl status bot-trading      # ver si está andando"
echo "  sudo journalctl -u bot-trading -f      # ver los logs en vivo"
echo "  sudo systemctl restart bot-trading     # reiniciarlo"
