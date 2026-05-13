from fastapi import APIRouter, Depends, Request

from app.auth import UserContext, require_admin, verify_jwt
from app.models import ChatRequest, ChatResponse
from app.services.agent_service import AgentState, get_agent_state
from app.services.chat_service import (
    foundry_status,
    get_chat_history,
    handle_chat,
    start_new_session,
)

router = APIRouter()


@router.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    http_request: Request,
    user: UserContext = Depends(verify_jwt),
    agent_state: AgentState = Depends(get_agent_state),
):
    return await handle_chat(request, http_request, user, agent_state)


@router.post("/api/chat/new", response_model=ChatResponse)
async def chat_new_session(
    request: ChatRequest,
    http_request: Request,
    user: UserContext = Depends(verify_jwt),
    agent_state: AgentState = Depends(get_agent_state),
):
    return await start_new_session(request, http_request, user, agent_state)


@router.get("/api/chat/history/{user_id}")
async def history(
    user_id: str,
    user: UserContext = Depends(verify_jwt),
    agent_state: AgentState = Depends(get_agent_state),
):
    return await get_chat_history(user_id, user, agent_state)


@router.get("/api/chat/admin/foundry-status")
async def foundry_status_admin(
    user: UserContext = Depends(require_admin),
    agent_state: AgentState = Depends(get_agent_state),
):
    return await foundry_status(agent_state)
