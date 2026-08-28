import uuid

import structlog
from fastapi import HTTPException, Request, status
from opentelemetry import trace

from app.auth import UserContext
from app.config import AGENT_FRAMEWORK_AVAILABLE
from app.models import ChatRequest, ChatResponse
from app.services import agent_service
from app.services.agent_service import AgentState
from app.services.agent_tools import set_current_auth_token

logger = structlog.get_logger("chatbot-service")


async def handle_chat(
    request: ChatRequest,
    http_request: Request,
    user: UserContext,
    agent_state: AgentState,
) -> ChatResponse:
    """Get financial advice from the AI agent."""
    if not agent_state.agent_ready or not agent_state.financial_agent:
        raise HTTPException(
            status_code=503,
            detail="Azure AI Foundry not configured. Set FOUNDRY_PROJECT_ENDPOINT or AZURE_OPENAI_ENDPOINT.",
        )

    # Use authenticated user_id from JWT, not from request body
    authenticated_user_id = user.user_id

    # Extract JWT from Authorization header so tools can forward it
    auth_header = http_request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
    set_current_auth_token(token)

    tracer = trace.get_tracer(__name__)

    try:
        with tracer.start_as_current_span("ai-agent.chat") as span:
            span.set_attribute("agent.name", "FinancialAdvisor")
            span.set_attribute("agent.model", agent_state.model_name)
            span.set_attribute("user.id", authenticated_user_id)
            span.set_attribute("user.message", request.message[:100])

            user_content = request.message
            if request.context:
                user_content = f"Context: {request.context}\n\nQuestion: {request.message}"

            # Get or create a session for multi-turn conversation
            async with agent_state.session_lock:
                session = agent_state.user_sessions.get(authenticated_user_id)
                if not session:
                    session = agent_state.financial_agent.create_session()
                    agent_state.user_sessions[authenticated_user_id] = session
                memory_thread_id = agent_state.user_memory_threads.get(authenticated_user_id)
                if not memory_thread_id and agent_state.chat_memory_service:
                    memory_thread_id = agent_state.chat_memory_service.new_thread_id(authenticated_user_id)
                    agent_state.user_memory_threads[authenticated_user_id] = memory_thread_id

            if agent_state.chat_memory_service and memory_thread_id:
                try:
                    memory_context = await agent_state.chat_memory_service.build_context(
                        user_id=authenticated_user_id,
                        thread_id=memory_thread_id,
                        message=request.message,
                    )
                    if memory_context:
                        user_content = f"{memory_context}\n\nCurrent user message:\n{user_content}"
                        span.set_attribute("memory.context_injected", True)
                        span.set_attribute("memory.context_length", len(memory_context))
                    else:
                        span.set_attribute("memory.context_injected", False)
                except Exception as error:
                    logger.warning("Failed to retrieve chat memory context", user_id=authenticated_user_id, error=str(error))
                    span.set_attribute("memory.context_error", True)

            result = await agent_state.financial_agent.run(user_content, session=session)
            answer = str(result) if result else "I couldn't generate a response at this time."

            # Persist both messages to Cosmos
            await agent_service.save_chat_message(agent_state, authenticated_user_id, "user", request.message)
            await agent_service.save_chat_message(agent_state, authenticated_user_id, "assistant", answer)
            if agent_state.chat_memory_service and memory_thread_id:
                try:
                    await agent_state.chat_memory_service.record_exchange(
                        user_id=authenticated_user_id,
                        thread_id=memory_thread_id,
                        user_message=request.message,
                        assistant_message=answer,
                    )
                    span.set_attribute("memory.exchange_recorded", True)
                except Exception as error:
                    logger.warning("Failed to record chat memory", user_id=authenticated_user_id, error=str(error))
                    span.set_attribute("memory.record_error", True)

            span.set_attribute("response.length", len(answer))

        suggestions = [
            "How can I save more each month?",
            "What's my spending pattern?",
            "Should I consider a budget?",
        ]

        return ChatResponse(response=answer, suggestions=suggestions)

    except HTTPException:
        raise
    except Exception as e:
        correlation_id = structlog.contextvars.get_contextvars().get("correlation_id", uuid.uuid4().hex)
        logger.error(f"Error in agent chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error. Correlation ID: {correlation_id}")


async def start_new_session(
    request: ChatRequest,
    http_request: Request,
    user: UserContext,
    agent_state: AgentState,
) -> ChatResponse:
    """Start a new chat session (clears conversation history for this user)."""
    async with agent_state.session_lock:
        agent_state.user_sessions.pop(user.user_id, None)
        agent_state.user_memory_threads.pop(user.user_id, None)
    return await handle_chat(request, http_request, user, agent_state)


async def get_chat_history(user_id: str, user: UserContext, agent_state: AgentState) -> dict:
    """Load persisted chat history for the authenticated user."""
    if user.user_id != user_id and user.role.lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another user's history")
    messages = []
    if agent_state.chat_memory_service:
        try:
            messages = await agent_state.chat_memory_service.get_history(user_id=user_id)
        except Exception as error:
            logger.warning("Failed to load Agent Memory Toolkit history", user_id=user_id, error=str(error))
    if not messages:
        messages = await agent_service.load_chat_history(agent_state, user_id)
    return {"messages": messages}


def get_health_status(agent_state: AgentState) -> dict:
    return {
        "status": "healthy",
        "agent_ready": agent_state.agent_ready,
        "model": agent_state.model_name,
        "sdk_available": AGENT_FRAMEWORK_AVAILABLE,
    }


async def foundry_status(agent_state: AgentState) -> dict:
    """Validate Foundry connectivity for the chat agent's model backend."""
    agent_name = "FinancialAdvisor"
    if not AGENT_FRAMEWORK_AVAILABLE:
        return {
            "status": "error",
            "agents": {agent_name: {"status": "error", "error": "agent-framework SDK not installed"}},
        }

    if not agent_state.agent_ready or not agent_state.financial_agent:
        return {
            "status": "error",
            "agents": {agent_name: {"status": "error", "error": "Agent not initialized — check FOUNDRY_PROJECT_ENDPOINT"}},
        }

    try:
        session = agent_state.financial_agent.create_session()
        response = await agent_state.financial_agent.run("ping", session=session)
        if response is not None:
            return {
                "status": "ok",
                "agents": {agent_name: {"status": "ok"}},
            }
        return {
            "status": "error",
            "agents": {agent_name: {"status": "error", "error": "Agent returned empty response"}},
        }
    except Exception as e:
        return {
            "status": "error",
            "agents": {agent_name: {"status": "error", "error": f"Connectivity check failed: {str(e)[:200]}"}},
        }
