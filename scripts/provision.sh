#!/bin/bash
#
# Provision the existing DigitalOcean droplet for CDP Intern Portal.
# Safe to run on a droplet already running classapp — does not touch port 8000.
#
# Usage (on the droplet):
#   curl -sSL https://raw.githubusercontent.com/cyberdefendersprogram/internapp/main/scripts/provision.sh | bash

set -euo pipefail

echo "=== CDP Intern Portal Provisioning ==="
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# ── Docker (already installed for classapp; verify) ───────────────────────────
echo ">>> Verifying Docker..."
docker compose version || {
    echo "Installing Docker Compose plugin..."
    apt install -y docker-compose-plugin
}

# ── Nginx (already installed; no reinstall needed) ────────────────────────────
echo ">>> Verifying Nginx..."
nginx -v

# ── Certbot (already installed; no reinstall needed) ──────────────────────────
echo ">>> Verifying Certbot..."
certbot --version

# ── Firewall (ports 22/80/443 already open for classapp; no changes) ─────────
echo ">>> Firewall OK (shared with classapp)"

# ── Application directories ───────────────────────────────────────────────────
echo ">>> Creating internapp directories..."
mkdir -p /opt/internapp/env
mkdir -p /var/lib/internapp
mkdir -p /etc/internapp

chmod 700 /opt/internapp/env
chmod 700 /etc/internapp
chmod 755 /var/lib/internapp

# ── docker-compose.yml on server ─────────────────────────────────────────────
echo ">>> Writing /opt/internapp/docker-compose.yml..."
cat > /opt/internapp/docker-compose.yml << 'COMPOSE'
services:
  app:
    image: ghcr.io/cyberdefendersprogram/internapp:latest
    ports:
      - "127.0.0.1:8001:8001"
    env_file:
      - ./env/.env
    volumes:
      - /var/lib/internapp:/var/lib/internapp
      - /etc/internapp:/etc/internapp:ro
    environment:
      - SQLITE_PATH=/var/lib/internapp/app.db
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
COMPOSE

echo ""
echo "=== Provisioning complete ==="
echo ""
echo "Next steps:"
echo ""
echo "1. Copy .env to the server:"
echo "   scp .env root@DROPLET_IP:/opt/internapp/env/.env"
echo "   chmod 600 /opt/internapp/env/.env"
echo ""
echo "2. Copy service account JSON:"
echo "   scp .secrets/service-account.json root@DROPLET_IP:/etc/internapp/service-account.json"
echo "   chmod 600 /etc/internapp/service-account.json"
echo ""
echo "3. Install nginx config:"
echo "   scp nginx/internapp.conf root@DROPLET_IP:/etc/nginx/sites-available/internapp"
echo "   # On server:"
echo "   ln -s /etc/nginx/sites-available/internapp /etc/nginx/sites-enabled/"
echo "   nginx -t && systemctl reload nginx"
echo ""
echo "4. Get TLS certificate:"
echo "   certbot --nginx -d intern.cyberdefendersprogram.com"
echo ""
echo "5. Add GitHub secrets (Settings > Secrets > Actions):"
echo "   DROPLET_HOST  — droplet IP"
echo "   DROPLET_USER  — root"
echo "   DROPLET_SSH_KEY — private SSH key"
echo ""
echo "6. Push to main to trigger first deploy:"
echo "   git push origin main"
echo ""
