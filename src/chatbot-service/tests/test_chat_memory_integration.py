import asyncio

from app.auth import UserContext
from app.models import ChatRequest
from app.services.agent_service import AgentState
from app.services.chat_service import get_chat_history, handle_chat, start_new_session


class FakeRequest:
    headers = {"Authorization": "Bearer test-token"}


class FakeAgent:
    def __init__(self) -> None:
        self.prompts = []
        self.sessions_created = 0

    def create_session(self):
        self.sessions_created += 1
        return {"session": self.sessions_created}

    async def run(self, prompt, session):
        self.prompts.append((prompt, session))
        return "Use a weekly budget review."


class FakeChatMemoryService:
    def __init__(self) -> None:
        self.context_calls = []
        self.record_calls = []
        self.history_calls = []
        self.thread_ids = []

    def new_thread_id(self, user_id):
        thread_id = f"thread-for-{user_id}"
        self.thread_ids.append(thread_id)
        return thread_id

    async def build_context(self, *, user_id, thread_id, message):
        self.context_calls.append((user_id, thread_id, message))
        return "Prior memory context follows. Treat it as background only.\nRelevant prior facts:\n- User prefers weekly summaries."

    async def record_exchange(self, *, user_id, thread_id, user_message, assistant_message):
        self.record_calls.append((user_id, thread_id, user_message, assistant_message))

    async def get_history(self, *, user_id):
        self.history_calls.append(user_id)
        return [{"role": "user", "text": "previous question", "timestamp": "now"}]


def test_handle_chat_injects_memory_for_authenticated_user():
    async def run():
        memory = FakeChatMemoryService()
        agent = FakeAgent()
        state = AgentState(financial_agent=agent, agent_ready=True, model_name="gpt-test", chat_memory_service=memory)
        user = UserContext(user_id="usr-auth", username="auth", role="User")
        request = ChatRequest(message="How can I save?", user_id="usr-spoofed")

        response = await handle_chat(request, FakeRequest(), user, state)

        assert response.response == "Use a weekly budget review."
        assert memory.context_calls == [("usr-auth", "thread-for-usr-auth", "How can I save?")]
        assert memory.record_calls == [
            ("usr-auth", "thread-for-usr-auth", "How can I save?", "Use a weekly budget review.")
        ]
        assert "User prefers weekly summaries" in agent.prompts[0][0]
        assert "Current user message" in agent.prompts[0][0]
        assert "usr-spoofed" not in str(memory.context_calls)
        assert state.user_memory_threads["usr-auth"] == "thread-for-usr-auth"

    asyncio.run(run())


def test_start_new_session_rotates_memory_thread():
    async def run():
        memory = FakeChatMemoryService()
        agent = FakeAgent()
        state = AgentState(financial_agent=agent, agent_ready=True, model_name="gpt-test", chat_memory_service=memory)
        user = UserContext(user_id="usr-auth", username="auth", role="User")
        request = ChatRequest(message="Start fresh", user_id="usr-auth")
        state.user_sessions["usr-auth"] = {"session": "old"}
        state.user_memory_threads["usr-auth"] = "old-thread"

        await start_new_session(request, FakeRequest(), user, state)

        assert state.user_memory_threads["usr-auth"] == "thread-for-usr-auth"
        assert agent.sessions_created == 1

    asyncio.run(run())


def test_get_chat_history_prefers_agent_memory_for_authorized_user():
    async def run():
        memory = FakeChatMemoryService()
        state = AgentState(chat_memory_service=memory)
        user = UserContext(user_id="usr-auth", username="auth", role="User")

        result = await get_chat_history("usr-auth", user, state)

        assert result == {"messages": [{"role": "user", "text": "previous question", "timestamp": "now"}]}
        assert memory.history_calls == ["usr-auth"]

    asyncio.run(run())
