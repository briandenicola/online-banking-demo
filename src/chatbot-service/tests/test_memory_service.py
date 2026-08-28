import asyncio
import os

from app.services.memory_service import ChatMemoryService, MemorySettings, sanitize_memory_text


class FakeMemoryClient:
    def __init__(self) -> None:
        self.calls = []
        self.processed = []
        self.reconciled = []

    async def get_user_summary(self, user_id):
        self.calls.append(("get_user_summary", user_id))
        return {"content": "User is working toward a $500 emergency fund.", "confidence": 0.95}

    async def get_thread_summary(self, user_id, thread_id, recent_k):
        self.calls.append(("get_thread_summary", user_id, thread_id, recent_k))
        return [{"content": "Discussed monthly grocery spending.", "confidence": 0.9}]

    async def search_cosmos(self, **kwargs):
        self.calls.append(("search_cosmos", kwargs))
        return [
            {"content": "User prefers concise budgeting advice.", "confidence": 0.91},
            {"content": "User shared account 1234567890123456.", "confidence": 0.99},
        ]

    async def get_thread(self, **kwargs):
        self.calls.append(("get_thread", kwargs))
        return [
            {"role": "user", "content": "Remember I prefer weekly summaries."},
            {"role": "assistant", "content": "I will keep advice weekly and concise."},
        ]

    async def upsert_memory(self, **kwargs):
        self.calls.append(("upsert_memory", kwargs))
        return f"memory-{len(self.calls)}"

    async def get_memories(self, **kwargs):
        self.calls.append(("get_memories", kwargs))
        return [
            {"role": "user", "content": "How can I save?", "created_at": "2026-08-28T00:00:00Z"},
            {"role": "assistant", "content": "Review subscriptions.", "created_at": "2026-08-28T00:00:01Z"},
        ]

    async def process_now(self, *, user_id, thread_id):
        self.processed.append((user_id, thread_id))

    async def reconcile(self, *, user_id):
        self.reconciled.append(user_id)

    async def close(self):
        self.calls.append(("close",))


def test_memory_settings_are_disabled_by_default(monkeypatch):
    monkeypatch.delenv("CHAT_MEMORY_ENABLED", raising=False)
    settings = MemorySettings.from_env()

    assert settings.enabled is False
    assert settings.database == "BankingDemo"
    assert settings.container == "AgentMemories"
    assert settings.counter_container == "AgentMemoryCounters"


def test_sanitize_memory_text_redacts_sensitive_values():
    text = "Email me@example.com, call 555-123-4567, ssn 123-45-6789, password=letmein, card 4111111111111111"

    sanitized = sanitize_memory_text(text)

    assert "me@example.com" not in sanitized
    assert "555-123-4567" not in sanitized
    assert "123-45-6789" not in sanitized
    assert "letmein" not in sanitized
    assert "4111111111111111" not in sanitized
    assert "[EMAIL]" in sanitized
    assert "[PHONE]" in sanitized
    assert "[SSN]" in sanitized
    assert "[SECRET]" in sanitized
    assert "[ACCOUNT_OR_CARD]" in sanitized


def test_build_context_uses_only_authenticated_user_and_bounds_prompt():
    async def run():
        settings = MemorySettings(
            enabled=True,
            required=False,
            database="BankingDemo",
            container="AgentMemories",
            turns_container="AgentMemoryTurns",
            summaries_container="AgentMemorySummaries",
            counter_container="AgentMemoryCounters",
            lease_container="AgentMemoryLeases",
            max_context_turns=2,
            max_facts=2,
            max_prompt_chars=350,
            min_confidence=0.7,
            process_every_n_turns=2,
            reconcile_every_n_turns=8,
            embedding_deployment="text-embedding-ada-002",
            chat_deployment="gpt-5.4-mini",
            thread_prefix="chat",
        )
        client = FakeMemoryClient()
        service = ChatMemoryService(client, settings)

        context = await service.build_context(user_id="usr-authenticated", thread_id="thread-1", message="budget")

        assert "Prior memory context follows" in context
        assert len(context) <= 350
        assert "1234567890123456" not in context
        search_call = next(call for call in client.calls if call[0] == "search_cosmos")
        assert search_call[1]["user_id"] == "usr-authenticated"
        assert search_call[1]["min_confidence"] == 0.7

    asyncio.run(run())


def test_record_exchange_writes_turns_and_processes_memory():
    async def run():
        settings = MemorySettings(
            enabled=True,
            required=False,
            database="BankingDemo",
            container="AgentMemories",
            turns_container="AgentMemoryTurns",
            summaries_container="AgentMemorySummaries",
            counter_container="AgentMemoryCounters",
            lease_container="AgentMemoryLeases",
            max_context_turns=8,
            max_facts=5,
            max_prompt_chars=4000,
            min_confidence=0.7,
            process_every_n_turns=2,
            reconcile_every_n_turns=2,
            embedding_deployment="text-embedding-ada-002",
            chat_deployment="gpt-5.4-mini",
            thread_prefix="chat",
        )
        client = FakeMemoryClient()
        service = ChatMemoryService(client, settings)

        await service.record_exchange(
            user_id="usr-1",
            thread_id="thread-1",
            user_message="My token=secret should not be saved",
            assistant_message="I can help with savings.",
        )
        await asyncio.sleep(0)

        writes = [call[1] for call in client.calls if call[0] == "upsert_memory"]
        assert len(writes) == 2
        assert {write["role"] for write in writes} == {"user", "assistant"}
        assert all(write["user_id"] == "usr-1" for write in writes)
        assert all(write["thread_id"] == "thread-1" for write in writes)
        assert "secret" not in writes[0]["content"]
        assert client.processed == [("usr-1", "thread-1")]
        assert client.reconciled == ["usr-1"]

    asyncio.run(run())


def test_create_returns_none_when_disabled():
    async def run():
        settings = MemorySettings.from_env()
        service = await ChatMemoryService.create(
            settings=settings,
            cosmos_endpoint=None,
            ai_foundry_endpoint=None,
            credential=object(),
        )
        assert service is None

    os.environ["CHAT_MEMORY_ENABLED"] = "false"
    asyncio.run(run())
