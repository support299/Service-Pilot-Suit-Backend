#!/usr/bin/env bash
# Install Redis + Celery worker/beat (and tighten Gunicorn) on the Suite EC2 host.
#
# From your Mac (repo checkout):
#   chmod +x deploy/setup-celery.sh && ./deploy/setup-celery.sh
#
# On the server:
#   sudo SKIP_GUNICORN=0 bash deploy/setup-celery.sh --local
#
# Overrides:
#   SSH_KEY=~/Downloads/service-pilot.pem ./deploy/setup-celery.sh
#   SKIP_GUNICORN=1 ./deploy/setup-celery.sh

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_KEY="${SSH_KEY:-$HOME/Downloads/service-pilot.pem}"
SSH_HOST="${SSH_HOST:-ubuntu@ec2-18-227-239-254.us-east-2.compute.amazonaws.com}"
REMOTE_APP="${REMOTE_APP:-/home/ubuntu/backend/Service-Pilot-Suit-Backend}"
SKIP_GUNICORN="${SKIP_GUNICORN:-0}"

install_on_host() {
  local app_dir="$1"
  export SKIP_GUNICORN="${SKIP_GUNICORN:-0}"

  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq redis-server

  if ! swapon --show | grep -q .; then
    if [[ ! -f /swapfile ]]; then
      sudo fallocate -l 1G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=1024
      sudo chmod 600 /swapfile
      sudo mkswap /swapfile
    fi
    sudo swapon /swapfile || true
    if ! grep -q '/swapfile' /etc/fstab; then
      echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    fi
    echo "Swap enabled (1G)"
  fi

  if [[ -f "${app_dir}/deploy/redis-suit.conf" ]]; then
    sudo mkdir -p /etc/redis/redis.conf.d
    sudo cp "${app_dir}/deploy/redis-suit.conf" /etc/redis/redis.conf.d/suit.conf
    if ! grep -qF 'include /etc/redis/redis.conf.d/suit.conf' /etc/redis/redis.conf; then
      echo 'include /etc/redis/redis.conf.d/suit.conf' | sudo tee -a /etc/redis/redis.conf >/dev/null
    fi
  fi
  # Ensure localhost-only (default on Ubuntu, but pin it)
  sudo sed -i 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf || true
  sudo systemctl enable redis-server
  sudo systemctl restart redis-server
  redis-cli ping | grep -q PONG

  "${app_dir}/venv/bin/pip" install -q 'celery==5.4.0' 'redis==5.2.1'

  sudo cp "${app_dir}/deploy/systemd/celery-worker.service" /etc/systemd/system/celery-worker.service
  sudo cp "${app_dir}/deploy/systemd/celery-beat.service" /etc/systemd/system/celery-beat.service
  if [[ "${SKIP_GUNICORN}" != "1" ]]; then
    sudo cp "${app_dir}/deploy/systemd/gunicorn.service" /etc/systemd/system/gunicorn.service
  fi

  # Beat creates its schedule file itself — do not pre-touch (empty file breaks dbm/shelve).
  sudo rm -f "${app_dir}/celerybeat-schedule" "${app_dir}/celerybeat-schedule.db" \
    "${app_dir}/celerybeat-schedule.dat" "${app_dir}/celerybeat-schedule.bak" \
    "${app_dir}/celerybeat-schedule.dir" "${app_dir}/celerybeat.pid" 2>/dev/null || true

  sudo systemctl daemon-reload
  sudo systemctl enable celery-worker celery-beat
  sudo systemctl restart celery-worker
  sudo systemctl restart celery-beat
  if [[ "${SKIP_GUNICORN}" != "1" ]]; then
    sudo systemctl restart gunicorn
  fi

  sleep 3
  echo "=== redis ==="
  redis-cli info memory | grep -E 'used_memory_human|maxmemory_human' || true
  echo "=== services ==="
  systemctl is-active redis-server celery-worker celery-beat gunicorn
  echo "=== celery ping ==="
  cd "${app_dir}"
  sudo -u ubuntu env HOME=/home/ubuntu \
    "${app_dir}/venv/bin/celery" -A config inspect ping -t 10 || true
  echo "Celery + Redis ready."
}

if [[ "${1:-}" == "--local" ]]; then
  install_on_host "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  exit 0
fi

SSH_OPTS=(
  -i "$SSH_KEY"
  -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=accept-new
)

echo "==> Checking SSH key: $SSH_KEY"
[[ -f "$SSH_KEY" ]] || { echo "PEM missing: $SSH_KEY"; exit 1; }
chmod 400 "$SSH_KEY" 2>/dev/null || true

echo "==> Syncing deploy/ + celery settings → ${SSH_HOST}:${REMOTE_APP}"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" "mkdir -p '${REMOTE_APP}/deploy/systemd'"
rsync -avz \
  -e "ssh ${SSH_OPTS[*]}" \
  "$ROOT/deploy/" \
  "${SSH_HOST}:${REMOTE_APP}/deploy/"
scp "${SSH_OPTS[@]}" \
  "$ROOT/config/settings.py" \
  "${SSH_HOST}:${REMOTE_APP}/config/settings.py"
scp "${SSH_OPTS[@]}" \
  "$ROOT/deploy/setup-celery.sh" \
  "${SSH_HOST}:${REMOTE_APP}/deploy/setup-celery.sh"

echo "==> Running remote install"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" \
  "chmod +x '${REMOTE_APP}/deploy/setup-celery.sh' && \
   SKIP_GUNICORN='${SKIP_GUNICORN}' sudo -E bash '${REMOTE_APP}/deploy/setup-celery.sh' --local"

echo ""
echo "Done."
echo "Logs:  ssh … 'sudo journalctl -u celery-worker -f'"
echo "       ssh … 'sudo journalctl -u celery-beat -f'"
