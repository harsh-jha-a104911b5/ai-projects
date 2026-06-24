# Security — Secret Management & Rotation

## Secret inventory

All secrets are stored in `.env` (gitignored) or a platform secrets manager. Never commit
secrets to the repository.

| Secret | Env var | Scope | Where to manage |
|---|---|---|---|
| DeepSeek API key | `DEEPSEEK_API_KEY` | LLM chat completions only | [platform.deepseek.com](https://platform.deepseek.com) → API Keys |
| Gemini API key | `GEMINI_API_KEY` | Embeddings only (`embed_content`) | [aistudio.google.com](https://aistudio.google.com/apikey) |
| GCP service account | `GOOGLE_SERVICE_ACCOUNT_KEY` (file path) | Calendar + Sheets APIs | [GCP Console](https://console.cloud.google.com/iam-admin/serviceaccounts) → Keys |
| Google Calendar ID | `GOOGLE_CALENDAR_ID` | Read/write one calendar | N/A (email address, not a secret) |
| Google Sheets ID | `GOOGLE_SHEETS_SPREADSHEET_ID` | Read/write one spreadsheet | N/A (not a secret, but PII-bearing) |
| SendGrid API key | `SENDGRID_API_KEY` | Mail Send permission only | [SendGrid](https://app.sendgrid.com/settings/api_keys) |
| Admin API key | `ADMIN_API_KEY` | `/admin/*` endpoints | Self-managed — generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

## Rotation procedures

### DeepSeek API key
1. Generate a new key at platform.deepseek.com → API Keys.
2. Update `DEEPSEEK_API_KEY` in `.env` / secrets manager.
3. Restart the API server (`make api` or redeploy).
4. Delete the old key from the DeepSeek dashboard.

### Gemini API key
1. Generate a new key at aistudio.google.com/apikey.
2. Update `GEMINI_API_KEY` in `.env`.
3. Restart.
4. Delete the old key.

### GCP service account key
1. Go to GCP Console → IAM → Service Accounts → `leadagent@...`.
2. Keys tab → Add Key → Create new JSON key.
3. Replace the local key file (path in `GOOGLE_SERVICE_ACCOUNT_KEY`).
4. Restart.
5. Delete the old key from the GCP console.
6. **Scope check:** The service account should have only:
   - `roles/calendar.writer` on the target calendar (via calendar sharing, not IAM)
   - Google Sheets API access (via spreadsheet sharing, not IAM)
   - No project-level IAM roles unless required.

### SendGrid API key
1. Generate a new key at app.sendgrid.com → Settings → API Keys.
2. Scope: **Mail Send only** (restricted access).
3. Update `SENDGRID_API_KEY` in `.env`.
4. Restart.
5. Revoke the old key.

### Admin API key
1. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Update `ADMIN_API_KEY` in `.env`.
3. Restart. No external service to update.

## Secret scanning

- **gitleaks** runs in CI on every push and PR (`.github/workflows/ci.yml`).
- It scans the full git history, not just the diff.
- If gitleaks flags a commit: rotate the affected credential immediately, then clean
  the history with `git filter-repo` or BFG Repo-Cleaner.

## Deliverability (email)

When `EMAIL_ADAPTER=sendgrid` is active, configure these DNS records on the sending
domain to avoid spam classification:

| Record | Type | Purpose |
|---|---|---|
| SPF | TXT | `v=spf1 include:sendgrid.net ~all` |
| DKIM | CNAME | Provided by SendGrid during domain authentication |
| DMARC | TXT | `v=DMARC1; p=none; rua=mailto:you@domain.com` (start with `none`, tighten to `quarantine` after monitoring) |

Set these up in SendGrid → Settings → Sender Authentication → Domain Authentication.

## HTTPS / TLS

TLS is terminated at the platform level (Railway, Render, Fly.io, etc.) or by a
reverse proxy (nginx + Let's Encrypt / Cloudflare). The app enforces:

- `FORCE_HTTPS=true` → HSTS header + HTTP→HTTPS redirect (checks `X-Forwarded-Proto`)
- Security headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: strict-origin-when-cross-origin`

**Never serve PII-bearing endpoints over plaintext HTTP in production.**
