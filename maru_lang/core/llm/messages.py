"""Message normalization for chat-model calls.

Some chat templates (notably Qwen) accept only a single system message, at the
front of the conversation — several `SystemMessage`s, or a system message that
isn't first, break their prompt template. Nodes that assemble more than one
system-level instruction must coalesce them before invoking the model.

`merge_system_messages` enforces that invariant: at most one SystemMessage,
placed first. Route every `model.ainvoke([...])` that passes a *message list*
through it so the whole app stays template-compatible, rather than wrapping the
model itself (which would shadow BaseChatModel methods like `.bind()`).
"""
from langchain_core.messages import BaseMessage, SystemMessage


def merge_system_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Collapse all SystemMessages into one leading system message.

    Non-system messages keep their relative order; the system contents are joined
    with blank lines into a single leading `SystemMessage`. Returned unchanged when
    there are no system messages, or when any system content isn't a plain string
    (e.g. multimodal parts) — those are left untouched rather than corrupted.
    """
    system = [m for m in messages if isinstance(m, SystemMessage)]
    if not system:
        return messages
    if not all(isinstance(m.content, str) for m in system):
        return messages
    others = [m for m in messages if not isinstance(m, SystemMessage)]
    merged = SystemMessage(content="\n\n".join(m.content for m in system))
    return [merged, *others]
