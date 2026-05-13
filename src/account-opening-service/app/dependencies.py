from __future__ import annotations

from fastapi import Request

from app.repository import ApplicationRepository
from app.state_machine import ApplicationStateMachine


async def get_repository(request: Request) -> ApplicationRepository:
    return request.app.state.repository


async def get_redis_client(request: Request):
    return request.app.state.redis


async def get_blob_service_client(request: Request):
    return request.app.state.blob_service_client


async def get_state_machine(request: Request) -> ApplicationStateMachine:
    return request.app.state.state_machine
