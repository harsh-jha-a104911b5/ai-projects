"""LLM-as-judge for qualitative eval criteria.

Scores four dimensions on a 1-5 scale using DeepSeek as the judge model.
Strict rubric-based prompts; responses parsed to structured scores.

Dimensions:
  groundedness   — claims only from retrieved KB content (1=hallucinated, 5=fully grounded)
  tone           — warm, natural, consultative (1=robotic/pushy, 5=excellent)
  qualifying     — proactively learns prospect's needs (1=no discovery, 5=thorough)
  escalation     — escalates at the right time (1=wrong timing, 5=perfect)
"""

from __future__ import annotations

import json
import os

import structlog

logger = structlog.get_logger(__name__)

_JUDGE_PROMPT = """\
You are evaluating an AI customer-service agent conversation. Score each dimension carefully.

## Conversation transcript
{conversation}

## Scenario being tested
{description}

## Evaluation rubric
{rubric}

## Scoring instructions
Score each dimension 1–5 (integers only, no halves):
- groundedness: Did the agent state facts ONLY from retrieved knowledge? (1=fabricated facts, 5=only KB content)
- tone: Was the conversation warm, natural, helpful? (1=cold/robotic/pushy, 5=excellent consultative tone)
- qualifying: Did the agent ask good discovery questions before booking? (1=none, 5=thorough and natural)
- escalation: Did the agent escalate at exactly the right time? (1=wrong timing or missing, 5=perfect)

Return ONLY valid JSON. No explanation outside the JSON block:
{{"groundedness": N, "tone": N, "qualifying": N, "escalation": N, "notes": "one sentence"}}
"""


async def judge_conversation(
    *,
    description: str,
    turns: list[tuple[str, str]],
    rubric: str,
    model: str | None = None,
) -> dict[str, int | str]:
    """Score a conversation on four dimensions. Returns a dict with integer scores + notes."""
    from openai import AsyncOpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")

    judge_model = model or os.environ.get("EVAL_JUDGE_MODEL", "deepseek-chat")

    conversation_text = "\n".join(
        f"User: {u}\nAgent: {a}" for u, a in turns
    )
    prompt = _JUDGE_PROMPT.format(
        conversation=conversation_text,
        description=description,
        rubric=rubric.strip(),
    )

    client = AsyncOpenAI(base_url="https://api.deepseek.com", api_key=api_key)
    response = await client.chat.completions.create(
        model=judge_model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
    )

    raw = (response.choices[0].message.content or "").strip()
    # Extract the JSON block (model may wrap it in markdown)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"Judge returned unparseable response: {raw[:200]}")
    scores = json.loads(raw[start:end])

    logger.info(
        "judge_scored",
        groundedness=scores.get("groundedness"),
        tone=scores.get("tone"),
        qualifying=scores.get("qualifying"),
        escalation=scores.get("escalation"),
    )
    return scores
