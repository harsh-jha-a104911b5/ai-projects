# TODO.md — Deferred Work

Items explicitly out of scope for the current milestone. Pick up in the appropriate milestone.

**Current status: M6 complete, hardened, deployment artifacts ready.**

---

## Pre-pilot hardening — Complete

### Tier 1 (breach/leak)
- [x] **Security headers** — HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy.
- [x] **Widget XSS audit** — all user/model content via textContent; test asserts no dynamic innerHTML.
- [x] **Admin hardening** — constant-time key compare, audit logging, PII redaction (`?redact=true`).
- [x] **SQL audit** — all 12 execute() paths confirmed parameterized.
- [x] **Error sanitization** — generic 500 handler, no stack traces to client.
- [x] **Secrets audit** — .env gitignored, GCP key gitignored, credentials scoped to calendar+sheets.

### Tier 2 (LLM abuse)
- [x] **Prompt injection defense** — security rules in prompt, KB data delimiters, strict tool arg validation.
- [x] **Security evals** — 8 scenarios (prompt extraction, grounding bypass, injection, data leak).
- [x] **Cost ceiling** — per-conversation token budget (50k) + daily ceiling (500k), configurable.
- [x] **Proxy-aware rate limiting** — X-Forwarded-For with TRUSTED_PROXY_IPS, admin rate limit separate.

### Data lifecycle
- [x] **Delete endpoint** — `DELETE /admin/conversations/{id}` for deletion requests.
- [x] **Purge endpoint** — `POST /admin/purge?days=N` for retention TTL.
- [x] **Email adapter** — SMTP + .ics, code-ready. Pending: Gmail App Password setup.

### Pre-pilot closeout
- [x] **SendGrid email adapter** — code-ready, replaces SMTP approach.
- [ ] **BLOCKED: Live email test** — needs SendGrid account + API key + verified sender.
  Outstanding: trigger real booking → email arrives → .ics opens in Google/Apple/Outlook.
- [x] **gitleaks CI** — `.github/workflows/ci.yml`, scans full history on push/PR.
- [x] **SECURITY.md** — secret inventory, rotation procedures, deliverability DNS records.
- [x] **CRM decision** — Google Sheets confirmed for v1 pilot. Live write verified.

### Deferred
- [ ] **GoHighLevel CRM** — adapter interface ready, needs GHL account/API key.
- [ ] **OAuth calendar guest-add** — service accounts can't invite guests without domain-wide delegation.
- [ ] **SendGrid domain authentication** — SPF/DKIM/DMARC DNS records (do when SendGrid account is set up).

---

## M6 — Complete

- [x] **Google Sheets CRM** — `GoogleSheetsCRMAdapter`, env-selected (`CRM_ADAPTER=sheets`).
- [x] **Live test gating** — `live` marker; `make test` excludes; `make test-live` available.
- [x] **Chat API** — SSE-streamed POST /chat with real token streaming, admin endpoints gated.
- [x] **Abuse protection** — rate limiting, message size, turn cap, origin allowlist.
- [x] **Embeddable widget** — script-tag drop-in, themeable, mobile-responsive.
- [x] **Packaging** — docker-compose, Dockerfile, .env.example, README.

## M5 — Complete

- [x] Eval variance + hardening — 3× variance stable, 29 scenarios, grounding backstop.
- [x] Turn-level logging, trace view, real Google Calendar, real Google Sheets CRM.

---

## Retrieval / RAG

- [ ] **HNSW or IVFFlat vector index** — add at 100k+ chunks.
- [ ] **Playwright-based crawler** — for JS-rendered SPAs.
- [ ] **Reranking model** — cross-encoder post-RRF.
- [ ] **Multilingual support** — tsvector config.
- [ ] **Semantic chunking** — revisit if recall drops.

## Out of scope for v1 (do not build)

- Multi-channel (email, WhatsApp, voice)
- Analytics dashboards
- Multi-tenant / billing / auth beyond admin key
- Multiple CRMs or calendars simultaneously
- Fine-tuning
- M7 self-improvement loop (needs real pilot data first)
