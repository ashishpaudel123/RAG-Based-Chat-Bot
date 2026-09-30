"""Memory module: recent history window plus an optional rolling summary (§3.10)."""

from app.config import get_settings
from app.models import Conversation, Message
from app.services.llm import ChatTurn, LLMProvider
from app.services.rag import sanitize

SUMMARY_PROMPT = """Summarise the earlier part of this customer-service conversation in at most 120 words.
Keep facts the user shared (such as order numbers, products or preferences) and the topics discussed.
Do not add new information. Output only the summary."""


def recent_history(messages: list[Message]) -> list[ChatTurn]:
    """Last N messages as model turns, excluding fallback replies that carry no information."""
    n = get_settings().history_messages
    turns = [
        ChatTurn("user" if m.role == "user" else "model", m.content)
        for m in messages[-n:]
        if not (m.role == "assistant" and m.is_fallback)
    ]
    # Gemini expects the conversation to start with a user turn.
    while turns and turns[0].role != "user":
        turns.pop(0)
    return turns


def maybe_update_summary(conversation: Conversation, messages: list[Message], llm: LLMProvider) -> None:
    """Fold messages that fall outside the history window into the rolling summary."""
    settings = get_settings()
    if len(messages) < settings.summary_trigger_messages:
        return
    cutoff = len(messages) - settings.history_messages
    if cutoff - conversation.summarized_until < settings.history_messages:
        return  # summarise in batches to limit API calls
    older = messages[conversation.summarized_until:cutoff]
    transcript = "\n".join(f"{m.role.title()}: {m.content[:600]}" for m in older)
    previous = f"Existing summary: {conversation.summary}\n\n" if conversation.summary else ""
    try:
        summary = llm.generate(SUMMARY_PROMPT, [ChatTurn("user", previous + "Conversation:\n" + sanitize(transcript))],
                               temperature=0.0, max_output_tokens=256)
    except Exception:
        return  # memory summarisation is best-effort
    conversation.summary = summary.strip()[:2000]
    conversation.summarized_until = cutoff
