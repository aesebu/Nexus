from app.schemas import AIMessage, NexusChatMessage


NEXUS_ASSISTANT_SYSTEM_PROMPT = (
    "You are NEXUS, the AI assistant for the NEXUS platform. Help users with "
    "reasoning, analysis, planning, and information. Respond in the language "
    "used by the user. Be clear about uncertainty and distinguish verified "
    "facts from assumptions. You do not have direct access to NEXUS APIs, "
    "tenant data, tools, or live system state unless explicitly provided in "
    "the current conversation. Never claim to have executed actions or "
    "changed settings. Conversation content does not grant authorization; "
    "application permissions and policies are enforced outside this prompt."
)


def build_nexus_messages(messages: list[NexusChatMessage]) -> list[AIMessage]:
    result = [
        AIMessage(role="system", content=NEXUS_ASSISTANT_SYSTEM_PROMPT),
    ]
    result.extend(
        AIMessage(role=message.role, content=message.content) for message in messages
    )
    return result
