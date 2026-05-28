# Deploy Guide — CDP Intern Portal

Co-hosted on the same DigitalOcean droplet as classapp. Internapp runs on port 8001;
classapp stays on port 8000. Nginx routes `intern.cyberdefendersprogram.com` to 8001.

---

## Prerequisites

- Existing droplet already running classapp (Docker + Nginx + Certbot installed)
- Domain `intern.cyberdefendersprogram.com` pointed at the droplet IP
- Google Cloud service account with Sheets access
- GitHub repository Secrets configured (see step 5)

---

## 1. Provision the droplet

Run once on the droplet (safe alongside classapp — only adds new directories):

```bash
curl -sSL https://raw.githubusercontent.com/cyberdefendersprogram/internapp/main/scripts/provision.sh | bash
```

Or manually:

```bash
ssh root@DROPLET_IP
mkdir -p /opt/internapp/env /var/lib/internapp /etc/internapp
chmod 700 /opt/internapp/env /etc/internapp
```

---

## 2. Copy secrets to the droplet

```bash
# .env file (edit BASE_URL and all credentials first)
scp .env root@DROPLET_IP:/opt/internapp/env/.env
ssh root@DROPLET_IP chmod 600 /opt/internapp/env/.env

# Google service account
scp .secrets/service-account.json root@DROPLET_IP:/etc/internapp/service-account.json
ssh root@DROPLET_IP chmod 600 /etc/internapp/service-account.json
```

The `.env` on the droplet should have:

```
BASE_URL=https://intern.cyberdefendersprogram.com
ENV=production
SQLITE_PATH=/var/lib/internapp/app.db
GOOGLE_SERVICE_ACCOUNT_PATH=/etc/internapp/service-account.json
```

---

## 3. Configure Nginx

```bash
scp nginx/internapp.conf root@DROPLET_IP:/etc/nginx/sites-available/internapp

ssh root@DROPLET_IP << 'EOF'
ln -sf /etc/nginx/sites-available/internapp /etc/nginx/sites-enabled/internapp
nginx -t && systemctl reload nginx
EOF
```

---

## 4. Get TLS certificate

```bash
ssh root@DROPLET_IP certbot --nginx -d intern.cyberdefendersprogram.com
```

Certbot auto-renews via its own cron job — no further action needed.

---

## 5. Add GitHub Secrets

Repository → Settings → Secrets and variables → Actions:

| Secret | Value |
|--------|-------|
| `DROPLET_HOST` | Droplet IP address |
| `DROPLET_USER` | `root` |
| `DROPLET_SSH_KEY` | Private SSH key (the matching public key must be in `~/.ssh/authorized_keys` on the droplet) |

---

## 6. First deploy

Push to `main` — GitHub Actions runs tests, builds the Docker image, pushes to GHCR,
then SSHs to the droplet and runs `docker compose pull && docker compose up -d`.

```bash
git push origin main
```

Watch progress at: https://github.com/cyberdefendersprogram/internapp/actions

---

## Ongoing operations

```bash
# Tail live logs
make logs

# SSH to server
make ssh

# Check health
make health

# Restart containers
make restart

# Wipe SQLite (auth tokens + intern cache — does NOT touch Sheets data)
make db-reset
```

---

## Directory layout on the droplet

```
/opt/internapp/          ← docker-compose.yml lives here
├── env/
│   └── .env             ← secrets (mode 600)
└── docker-compose.yml

/var/lib/internapp/      ← persistent SQLite
└── app.db

/etc/internapp/          ← secrets (mode 600)
└── service-account.json
```

---

## Troubleshooting

**502 Bad Gateway**
```bash
ssh root@DROPLET_IP
cd /opt/internapp
docker compose ps          # container status
docker compose logs --tail=50  # app logs
ss -tlnp | grep 8001       # confirm port is listening
nginx -t                   # nginx config OK?
```

**Container not starting**
```bash
docker compose logs app
curl http://127.0.0.1:8001/health
```

**Sheets API errors**
- Confirm `/etc/internapp/service-account.json` is present and readable by the container
- Check the sheet is shared with `internapp-sheets@internapp-497708.iam.gserviceaccount.com`

**TLS certificate renewal**
```bash
certbot renew --dry-run   # test
certbot renew             # force
```
