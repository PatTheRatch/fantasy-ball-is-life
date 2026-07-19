# Full Court Press — Deployment Runbook

Self-hosted on Patrick's VPS (Docker + Caddy). Supabase stays external.

## Architecture

```
Internet → :80/:443 → Caddy ─┬─ /api/* → backend:8000 (uvicorn)
                              └─ /*     → frontend/dist/ (static, SPA fallback)
```

Only Caddy publishes ports. Backend talks to Supabase externally. No DB on the VPS.

## Bootstrap (first-time setup, run as root)

### 1. Install Docker
```bash
apt-get update && apt-get install -y docker.io docker-compose-v2
```

### 2. Create service user
```bash
useradd --system --shell /usr/sbin/nologin --create-home fcp-svc
```

### 3. Create app directory
```bash
mkdir -p /srv/fullcourtpress/frontend/dist
chown -R fcp-svc:fcp-svc /srv/fullcourtpress
```

### 4. Deploy key user for CI
```bash
useradd --system --shell /bin/bash --create-home deploy
mkdir -p /home/deploy/.ssh
# Add CI public key to /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

# Grant deploy user sudo for docker compose only
echo "deploy ALL=(ALL) NOPASSWD: /usr/bin/docker compose up -d --build --remove-orphans, /usr/bin/docker compose ps, /usr/bin/docker compose down" > /etc/sudoers.d/deploy
```

### 5. Populate secrets
Create `/srv/fullcourtpress/.env`, owned by `fcp-svc`, `chmod 600`:

```bash
# Required vars (copy from Patrick's password manager):
SUPABASE_URL=https://wuzoengojiqotusulwhj.supabase.co
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
CRED_ENCRYPTION_KEY=
WORKER_SECRET=
PUBLIC_APP_URL=https://fcp.patrickmcdowell.dev
ANTHROPIC_API_KEY=
RECAP_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
ESPN_LEAGUE_ID=3853870
ESPN_SEASON=2026
ESPN_SWID=
ESPN_S2=
DRAFT_LEAGUE_YEAR=2025
```

### 6. Firewall
```bash
apt-get install -y ufw
ufw default deny incoming
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### 7. SSH hardening
Edit `/etc/ssh/sshd_config`:
```
PermitRootLogin no
PasswordAuthentication no
```
Then `systemctl reload sshd`.

### 8. fail2ban
```bash
apt-get install -y fail2ban
# Default SSH jail is enabled automatically
```

### 9. unattended-upgrades
```bash
apt-get install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades  # select "Yes"
```

### 10. Systemd timer (snapshot refresh)
```bash
cp deploy/fcp-snapshot-refresh.service /etc/systemd/system/
cp deploy/fcp-snapshot-refresh.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now fcp-snapshot-refresh.timer
```

### 11. DNS
Add an `A` record in the `patrickmcdowell.dev` zone:
```
fcp.patrickmcdowell.dev → <VPS_IP>
```

## Deploy flow

A merge to `main` triggers `.github/workflows/deploy.yml`:

1. Backend tests + frontend type-check + build
2. Frontend builds with prod env vars (from GitHub Secrets)
3. `scp`-s the code + built frontend to the VPS
4. `ssh`-es in and runs `sudo docker compose up -d --build`

No interactive root session. No secret in logs.

## Rollback

```bash
# On the VPS, as deploy user:
cd /srv/fullcourtpress
git log --oneline -5          # find the good commit
git revert <bad-commit>
git push origin main           # triggers CI → rebuilds + deploys
```

Or manually:
```bash
git checkout <good-commit>
sudo docker compose up -d --build
```

Caddy's cert storage is in a named volume (`caddy_data`) and survives rebuilds.

## Logs

```bash
sudo docker compose logs -f              # all services
sudo docker compose logs backend -f      # backend only
sudo journalctl -u fcp-snapshot-refresh  # cron timer
```

## Verification checklist

- [ ] `https://fcp.patrickmcdowell.dev` loads with valid TLS
- [ ] `http://` redirects to HTTPS (or is refused — `.dev` is HSTS)
- [ ] Port 8000 not reachable externally: `curl http://<VPS_IP>:8000` times out
- [ ] Login / signup / password reset work
- [ ] `curl -X POST https://fcp.patrickmcdowell.dev/api/admin/refresh/patriot-games -H "X-Worker-Secret: $WORKER_SECRET"` returns 200
- [ ] Newsroom loads real data from Supabase
- [ ] `sudo ufw status` shows only 22/80/443 allowed
- [ ] SSH rejects password + root login
- [ ] `ps aux | grep uvicorn` shows process running as `app` user (inside container)
- [ ] `unattended-upgrades` active: `systemctl status unattended-upgrades`
- [ ] `.env` is `600` owned by `fcp-svc`: `ls -la /srv/fullcourtpress/.env`
