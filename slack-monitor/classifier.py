"""Claude-based urgency classifier for Slack messages."""

import os
import anthropic

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


_SYSTEM = """You are an urgency classifier for Max Alderman, founder of Skyro Digital — a Klaviyo email and SMS marketing agency doing ~$75K MRR with a team of 14 international contractors.

Your job: decide whether a Slack message requires Max's PERSONAL attention right now, or whether it can be handled by his team without him.

URGENT — notify Max when:
- A client is unhappy, escalating, or threatening to leave
- Someone is blocked on a decision only Max can make (hiring, budget, strategy, partnerships)
- A financial issue or significant revenue risk is raised
- A new sales lead or prospect is reaching out
- Something time-sensitive will get worse without Max's input today
- A legal, compliance, or serious operational issue

NOT_URGENT — do NOT notify Max when:
- Status updates or FYIs that don't need a response
- Routine task updates, completions, or check-ins
- Questions an account manager or team member could answer
- General team conversation, scheduling, or logistics
- Positive news that doesn't require action

Reply with exactly two lines:
Line 1: URGENT or NOT_URGENT
Line 2: One sentence explaining why (be specific about the message content)."""


def classify(
    message_text: str,
    sender_name: str,
    thread_context: list[str],
    is_vip: bool = False,
) -> tuple[str, str]:
    """
    Returns ("URGENT", "reason") or ("NOT_URGENT", "reason").
    thread_context is up to 3 prior messages in the same thread, oldest first.
    """
    vip_note = (
        f"\nNote: {sender_name} is one of Max's key team members (VIP contact). "
        "Weight this context when assessing whether it needs his attention."
        if is_vip
        else ""
    )

    context_block = ""
    if thread_context:
        context_block = "\n\nThread context (prior messages, oldest first):\n" + "\n".join(
            f"- {m}" for m in thread_context
        )

    user_content = (
        f"Sender: {sender_name}{vip_note}"
        f"{context_block}"
        f"\n\nMessage:\n{message_text}"
    )

    response = _get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = response.content[0].text.strip()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    verdict = "NOT_URGENT"
    reason = "No reason provided"

    if lines:
        first = lines[0].upper()
        if "URGENT" in first and "NOT" not in first:
            verdict = "URGENT"
        reason = lines[1] if len(lines) > 1 else lines[0]

    return verdict, reason
