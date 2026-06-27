# Deployment Guide — Single-Instance Production Setup

One deployment = one business client. This guide covers the manual onboarding
procedure that a future self-serve form will automate.

---

## Option A: Render + Neon (recommended — fastest to live)

### 1. Provision Neon Postgres

1. Sign up at [neon.tech](https://neon.tech) (free tier: 0.5 GB).
2. Create a project → default branch → database `leadagent`.
3. Enable the **pgvector** extension: run `CREATE EXTENSION IF NOT EXISTS vector;`
   in the SQL Editor (or it will be enabled by migrations).
4. Copy the connection string: `postgresql://user:pass@host/leadagent?sslmode=require`

### 2. Create Render Web Service

1. Sign up at [render.com](https://render.com).
2. New → Web Service → connect your GitHub repo.
3. Settings:
   - **Root Directory:** `LeadAgent`
   - **Runtime:** Docker
   - **Instance Type:** Free (or Starter for always-on)
4. The health check at `/health` will auto-detect.

### 3. Set environment variables (Render Dashboard → Environment)

**Required:**

| Variable | Value |
|---|---|
| `DATABASE_URL` | Neon connection string |
| `DEEPSEEK_API_KEY` | Your DeepSeek API key |
| `GEMINI_API_KEY` | Your Gemini API key (embeddings) |
| `ADMIN_API_KEY` | Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ENV` | `production` |
| `FORCE_HTTPS` | `true` |
| `PORT` | `10000` (Render default) |

**Client-specific:**

| Variable | Value |
|---|---|
| `COMPANY_NAME` | The client's business name |
| `ALLOWED_ORIGINS` | The client's website domain (e.g. `https://example.com`) |
| `GOOGLE_SERVICE_ACCOUNT_KEY` | Base64-encoded JSON: `base64 -w0 service-account.json` |
| `GOOGLE_CALENDAR_ID` | The client's calendar email |
| `CALENDAR_ADAPTER` | `google` |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | The client's lead sheet ID |
| `CRM_ADAPTER` | `sheets` |

**Optional branding:**

| Variable | Default | Description |
|---|---|---|
| `WIDGET_TITLE` | "Chat with us" | Chat header text |
| `WIDGET_COLOR` | `#2563eb` | Brand color (hex) |
| `WIDGET_POSITION` | `right` | `left` or `right` |

### 4. Deploy

Push to the connected branch. Render builds the Docker image and deploys.
Migrations run automatically on startup.

Your app is live at: `https://leadagent-XXXX.onrender.com`

### 5. Ingest the client's website

```bash
# Run from the Render shell (Dashboard → Shell), or locally with the production DATABASE_URL:
python scripts/ingest.py --url https://client-site.com --depth 2
```

### 6. Verify

1. Open `https://your-app.onrender.com/health` → `{"status":"ok"}`
2. Open `https://your-app.onrender.com/widget/demo.html` → chat widget loads
3. Start a conversation → agent answers from the client's KB
4. Book a meeting → calendar event created
5. Check traces: `curl -H "X-Admin-Key: YOUR_KEY" https://your-app.onrender.com/admin/traces`

### 7. Generate the client's embed snippet

Open `https://your-app.onrender.com/embed-snippet` — copy the `<script>` tag
and give it to the client.

Or visit the demo page: `https://your-app.onrender.com/widget/demo.html`

---

## Option B: VPS + Caddy (cheaper long-term)

### Prerequisites
- A VPS ($5/mo: DigitalOcean, Hetzner, Linode)
- A domain pointed to the VPS IP
- Docker + Docker Compose installed

### 1. Clone and configure

```bash
git clone git@github.com:YOUR/repo.git
cd repo/LeadAgent
cp .env.example .env
# Edit .env with production values (same as the Render table above)
```

### 2. Caddy reverse proxy (auto-TLS)

Create `Caddyfile`:
```
leadagent.yourdomain.com {
    reverse_proxy localhost:8000
}
```

Run Caddy: `caddy run` (or as a systemd service).
Caddy automatically provisions Let's Encrypt TLS certificates.

### 3. Start the stack

```bash
docker compose up -d
# Migrations run on startup via scripts/run_api.py
```

### 4. Ingest + verify

Same as Option A steps 5–7, using your domain instead of `*.onrender.com`.

---

## Onboarding a new client (manual checklist)

1. [ ] Provision a new instance (Render service or VPS container)
2. [ ] Create Neon database (or reuse if shared infra)
3. [ ] Set all required + client-specific env vars
4. [ ] Deploy → verify `/health`
5. [ ] Create a Google Sheet, share with the service account → set `GOOGLE_SHEETS_SPREADSHEET_ID`
6. [ ] Share the client's Google Calendar with the service account → set `GOOGLE_CALENDAR_ID`
7. [ ] Ingest the client's website: `python scripts/ingest.py --url https://...`
8. [ ] Open demo page, run a test conversation
9. [ ] Generate embed snippet → hand to client
10. [ ] Set `ALLOWED_ORIGINS` to the client's domain
11. [ ] (Optional) Set up SendGrid for booking confirmation emails

For multiple simultaneous demos before multi-tenant: spin a separate instance per prospect.
