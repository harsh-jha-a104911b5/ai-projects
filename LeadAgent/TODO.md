# TODO.md — Deferred Work

Items explicitly out of scope for the current milestone, tracked here so they aren't
forgotten. Pick up in the appropriate milestone.

---

## Retrieval / RAG

- [ ] **HNSW or IVFFlat vector index** — add when corpus exceeds 100k chunks. HNSW
  preferred for ongoing inserts. IVFFlat requires post-load creation and list tuning.
  See DECISIONS.md 2026-06-15.
- [ ] **Playwright-based crawler** — for JavaScript-rendered SPA sites where trafilatura
  returns empty content. Add as an optional crawler backend (`--renderer=playwright`).
- [ ] **Reranking model** — cross-encoder reranker (e.g. Cohere Rerank, BGE-Reranker)
  as a post-RRF step. Improves precision at the cost of latency and API cost. M4+ if
  evals show precision problems.
- [ ] **Multilingual support** — change tsvector config from `'english'` to `'simple'`
  or language-detected config if client site is multilingual.
- [ ] **Semantic chunking** — revisit if M4 evals show poor retrieval recall on
  fixed-window chunks.
- [ ] **Chunk metadata enrichment** — extract page title, section headings, structured
  data (FAQs, pricing tables) as additional metadata fields on chunks.

## Agent (M2+)

- [ ] **Agent loop** — tool-calling conversation loop with search_knowledge,
  check_availability, book_meeting.
- [ ] **Guardrails** — grounded-or-escalate enforcement, structured commitment validation.
- [ ] **capture_lead tool** — write qualified lead to CRM.
- [ ] **escalate_to_human tool** — flag for human handoff.
- [ ] **System prompt assembly** — inject business context, retrieved chunks, conversation
  history into a well-structured system prompt.

## Integrations (M2/M5)

- [ ] **Mock calendar adapter** — `check_availability` and `book_meeting` using in-memory
  state. Implement in M2.
- [ ] **Real calendar adapter** — Cal.com or Google Calendar behind the existing interface.
  Implement in M5.
- [ ] **Mock CRM adapter** — `capture_lead` writing to Postgres. Implement in M3.
- [ ] **Real CRM adapter** — GHL or HubSpot. Implement in M5.

## Evals (M4)

- [ ] **Eval dataset** — 10–15 representative conversations (JSONL fixtures).
- [ ] **LLM-as-judge grader** — groundedness, no-hallucinated-commitment,
  books-when-it-should, escalates-when-it-should.
- [ ] **CI integration** — `make eval` exits 1 on regression.

## Observability (M5)

- [ ] **Turn-level logging** — every turn: user input, retrieved chunks, tool calls,
  output, latency, token counts → Postgres `traces` table.
- [ ] **Trace view** — simple FastAPI admin route to browse traces by conversation.

## Infrastructure (M6)

- [ ] **Embeddable widget** — React chat widget, script-tag drop-in, minimal CSS.
- [ ] **docker-compose full-stack** — add API + widget services alongside postgres.
- [ ] **README** — complete setup guide with demo walkthrough.
- [ ] **CI pipeline** — GitHub Actions: lint + typecheck + test on PR.

## Out of scope for v1 (do not build)

- Multi-channel (email, WhatsApp, voice)
- Analytics dashboards
- Multi-tenant / billing / auth beyond a basic admin key
- Multiple CRMs or calendars simultaneously
- Fine-tuning
- Reranking models (revisit in M4 only if evals demand it)
