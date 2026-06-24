"""Tool registry: JSON schema declarations (OpenAI format), input models, and dispatcher.

Each tool produces a structured, validated result — never free text.

Guardrails enforced here (not only in the prompt):
  - book_meeting: slot_id must be in session.offered_slot_ids (calendar slot guardrail).
  - search_knowledge: returns grounded=false when KB has no relevant results; the model
    is instructed to call escalate_to_human in that case.

ToolSession is created once per AgentLoop (one conversation) and carries state
across all turns: offered slot IDs, escalation IDs logged so far.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel

from domain.chunk import RetrievedChunk
from domain.lead import EscalationRecord, LeadCapture, LeadCreateResult, TimeSlot
from integrations.calendar_adapter import CalendarAdapter
from integrations.crm_adapter import CRMAdapter
from rag.retriever import search_knowledge as _search_kb

logger = structlog.get_logger(__name__)


# ── Input schemas ─────────────────────────────────────────────────────────────


class SearchKnowledgeInput(BaseModel):
    query: str


class CheckAvailabilityInput(BaseModel):
    date_range: str


class BookMeetingInput(BaseModel):
    slot_id: str
    contact_name: str
    contact_email: str


class CaptureLeadInput(BaseModel):
    name: str
    email: str
    phone: str | None = None
    company: str | None = None
    use_case: str | None = None
    budget_range: str | None = None
    timeline: str | None = None


class EscalateInput(BaseModel):
    reason: str
    context: str


# ── Session state (per conversation — lives on AgentLoop, spans all turns) ───


@dataclass
class ToolSession:
    """Per-conversation state. Created once in AgentLoop.__init__; reused across turns.

    offered_slot_ids: slot IDs returned by check_availability this conversation.
      book_meeting is rejected unless the slot_id is here (the slot guardrail).
    escalations: escalation IDs logged this conversation.
    tool_calls: ordered log of every tool call and its result (for evals / observability).
    pending_grounding_escalation: set by dispatch when search_knowledge returns grounded=false;
      cleared when escalate_to_human is called. Loop checks this before returning text and
      forces escalation if still set (code backstop for grounding failures).
    """

    calendar: CalendarAdapter
    crm: CRMAdapter
    offered_slot_ids: set[str] = field(default_factory=set)
    escalations: list[str] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    pending_grounding_escalation: bool = False


# ── OpenAI-format tool declarations ──────────────────────────────────────────

TOOL_SPEC: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": (
                "Search the company knowledge base for information about services, pricing, "
                "processes, or any topic a prospect might ask about. "
                "Always call this before answering factual questions. "
                "If it returns grounded=false, call escalate_to_human instead of guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query — be specific",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": (
                "Check available meeting slots for a given date range. "
                "Always call this before offering times to the prospect."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_range": {
                        "type": "string",
                        "description": (
                            "Natural-language date range, e.g. 'next week', "
                            "'June 24-28', 'tomorrow', 'this Thursday'"
                        ),
                    }
                },
                "required": ["date_range"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_meeting",
            "description": (
                "Book a meeting for the prospect. "
                "Only call this with a slot_id that was returned by check_availability "
                "in this conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_id": {
                        "type": "string",
                        "description": "The slot_id from a previous check_availability result",
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "The prospect's full name",
                    },
                    "contact_email": {
                        "type": "string",
                        "description": "The prospect's email address",
                    },
                },
                "required": ["slot_id", "contact_name", "contact_email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "capture_lead",
            "description": (
                "Record a qualified prospect's contact and qualification information. "
                "Call this once you have their name and email and know their use case. "
                "Call it before book_meeting when possible."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Prospect's full name",
                    },
                    "email": {
                        "type": "string",
                        "description": "Prospect's email address",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Phone number (optional)",
                    },
                    "company": {
                        "type": "string",
                        "description": "Company name (optional)",
                    },
                    "use_case": {
                        "type": "string",
                        "description": "What they need the service for",
                    },
                    "budget_range": {
                        "type": "string",
                        "description": "Budget range if mentioned (optional)",
                    },
                    "timeline": {
                        "type": "string",
                        "description": "Timeline if mentioned (optional)",
                    },
                },
                "required": ["name", "email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_human",
            "description": (
                "Hand off to a human agent. Use when: "
                "(1) search_knowledge returns grounded=false and the prospect needs an answer; "
                "(2) a pricing, contractual, or commitment question isn't in the knowledge base; "
                "(3) the prospect explicitly requests a human; "
                "(4) any complex or sensitive question you cannot confidently answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Short reason code: 'no_grounding', 'pricing_question', "
                            "'customer_request', 'complex_technical', 'commitment_question'"
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Brief summary of the conversation so far and the unanswered question, "
                            "to hand off to the human taking over"
                        ),
                    },
                },
                "required": ["reason", "context"],
            },
        },
    },
]


# ── Dispatcher ────────────────────────────────────────────────────────────────


async def dispatch(
    name: str,
    args: dict[str, Any],
    session: ToolSession,
) -> dict[str, Any]:
    """Execute a named tool, record the call in session.tool_calls, and return the result.

    Side-effects on session state beyond tool_calls:
      - search_knowledge returning grounded=false sets session.pending_grounding_escalation.
      - escalate_to_human clears session.pending_grounding_escalation.
    The loop checks pending_grounding_escalation before returning a text response and forces
    an escalation if set (code backstop — mirrors the booking slot guardrail).
    """
    result = await _execute(name, args, session)
    session.tool_calls.append({"name": name, "args": args, "result": result})

    if name == "search_knowledge" and result.get("grounded") is False:
        session.pending_grounding_escalation = True
    elif name == "escalate_to_human":
        session.pending_grounding_escalation = False

    return result


async def _execute(
    name: str,
    args: dict[str, Any],
    session: ToolSession,
) -> dict[str, Any]:
    """Inner dispatch — returns result without recording. Called only by dispatch()."""

    if name == "search_knowledge":
        import os as _os
        inp = SearchKnowledgeInput(**args)
        chunks: list[RetrievedChunk] = await _search_kb(inp.query, top_k=5)
        threshold = float(_os.environ.get("GROUNDING_COSINE_THRESHOLD", "0.0"))
        top_cosine = max((c.cosine_score for c in chunks), default=0.0)
        grounded = len(chunks) > 0 and (threshold == 0.0 or top_cosine >= threshold)
        result: dict[str, Any] = {
            "chunks": [
                {
                    "content": c.content,
                    "source_url": c.source_url,
                    "rrf_score": round(c.rrf_score, 4),
                    "cosine_score": round(c.cosine_score, 4),
                }
                for c in chunks
            ],
            "sources": list(dict.fromkeys(c.source_url for c in chunks)),
            "count": len(chunks),
            "top_cosine_score": round(top_cosine, 4),
            "grounded": grounded,
        }
        if not grounded:
            result["grounding_note"] = (
                "No relevant information found in the knowledge base. "
                "Do NOT answer from general knowledge. "
                "Call escalate_to_human with reason='no_grounding'."
            )
        logger.info(
            "tool_search_knowledge",
            query=inp.query,
            chunks=len(chunks),
            top_cosine=round(top_cosine, 4),
            grounded=grounded,
        )
        return result

    if name == "check_availability":
        inp = CheckAvailabilityInput(**args)
        slots = await session.calendar.get_availability(inp.date_range)
        for slot in slots:
            session.offered_slot_ids.add(slot.slot_id)
        result = {
            "slots": [s.model_dump() for s in slots],
            "count": len(slots),
        }
        logger.info(
            "tool_check_availability",
            date_range=inp.date_range,
            slots=len(slots),
            offered_total=len(session.offered_slot_ids),
        )
        return result

    if name == "book_meeting":
        inp = BookMeetingInput(**args)
        if inp.slot_id not in session.offered_slot_ids:
            logger.warning(
                "guardrail_slot_not_offered",
                slot_id=inp.slot_id,
                offered=list(session.offered_slot_ids),
            )
            return {
                "error": (
                    "Cannot book: this slot was not returned by check_availability "
                    "in this conversation. Call check_availability first."
                ),
                "offered_slot_ids": list(session.offered_slot_ids),
            }
        booking = await session.calendar.book_slot(
            inp.slot_id, inp.contact_name, inp.contact_email
        )
        result = booking.model_dump()
        logger.info(
            "tool_book_meeting",
            booking_id=booking.booking_id,
            slot_id=inp.slot_id,
            contact=inp.contact_email,
        )
        return result

    if name == "capture_lead":
        inp = CaptureLeadInput(**args)
        lead = LeadCapture(
            name=inp.name,
            email=inp.email,
            phone=inp.phone,
            company=inp.company,
            use_case=inp.use_case,
            budget_range=inp.budget_range,
            timeline=inp.timeline,
        )
        lead_result: LeadCreateResult = await session.crm.create_lead(lead)
        logger.info("tool_capture_lead", lead_id=lead_result.lead_id, email=inp.email)
        return lead_result.model_dump()

    if name == "escalate_to_human":
        inp = EscalateInput(**args)
        escalation_id = f"esc-{uuid.uuid4().hex[:8]}"
        EscalationRecord(
            escalation_id=escalation_id,
            reason=inp.reason,
            context=inp.context,
            created_at=datetime.now(timezone.utc),
        )
        session.escalations.append(escalation_id)
        logger.info("tool_escalate_to_human", escalation_id=escalation_id, reason=inp.reason)
        return {
            "escalation_id": escalation_id,
            "user_message": (
                "Thank you for your patience. A member of our team will be "
                "in touch with you shortly to assist with your question."
            ),
            "recorded": True,
        }

    logger.error("unknown_tool", name=name, args=args)
    return {"error": f"Unknown tool: {name!r}"}
