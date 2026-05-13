import json
from datetime import datetime, timezone

import redis.asyncio as redis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import UserContext, require_admin, verify_jwt
from app.config import AGENT_FRAMEWORK_AVAILABLE
from app.models import (
    AdminStats,
    DetectRequest,
    EvalRequest,
    FlaggedTransaction,
    ReviewRequest,
    RiskAssessment,
    ScoredTransaction,
)
from app.services import anomaly_service

logger = structlog.get_logger("ai-service")
router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/healthz")
async def healthz():
    return {
        "status": "healthy",
        "service": "ai-service",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/readyz")
async def ready():
    checks = {"redis": False, "analyzer_pipeline": False}

    if anomaly_service._redis_client:
        try:
            await anomaly_service._redis_client.ping()
            checks["redis"] = True
        except redis.RedisError:
            pass

    if anomaly_service._analyzer_pipeline and any(a.enabled for a in anomaly_service._analyzer_pipeline.analyzers):
        checks["analyzer_pipeline"] = True

    all_ready = all(checks.values())
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks}


@router.post("/detect", response_model=RiskAssessment)
async def detect(body: DetectRequest, user: UserContext = Depends(verify_jwt)):
    """Score a single transaction synchronously (for on-demand assessment)."""
    if not anomaly_service._analyzer_pipeline:
        raise HTTPException(status_code=503, detail="Analyzer pipeline not initialized")
    return await anomaly_service._analyzer_pipeline.assess(body.model_dump())


@router.get("/api/admin/foundry-status")
async def foundry_status(user: UserContext = Depends(require_admin)):
    """Validate Foundry connectivity for transaction-categorizer and risk-assessor agents."""
    agents_status = {}

    async def _check_agent(label: str, agent_obj) -> dict:
        """Run a minimal test call against a FoundryAgent to verify connectivity."""
        if agent_obj is None or not agent_obj._ready:
            return {"status": "error", "error": "Agent not initialized"}
        try:
            session = agent_obj._agent.create_session()
            response = await agent_obj._agent.run("ping", session=session)
            if response is not None:
                return {"status": "ok"}
            return {"status": "error", "error": "Agent returned empty response"}
        except Exception as e:
            return {"status": "error", "error": f"Connectivity check failed: {str(e)[:200]}"}

    # Find the risk analyzer and categorizer from the pipeline
    risk_analyzer = None
    categorizer = None
    if anomaly_service._analyzer_pipeline:
        for a in anomaly_service._analyzer_pipeline.analyzers:
            if a.name == "foundry-risk":
                risk_analyzer = a
                break
        for c in anomaly_service._analyzer_pipeline.categorizers:
            if c.name == "foundry-categorizer":
                categorizer = c
                break

    agents_status["transaction-categorizer"] = await _check_agent("transaction-categorizer", categorizer)
    agents_status["risk-assessor"] = await _check_agent("risk-assessor", risk_analyzer)

    statuses = [v["status"] for v in agents_status.values()]
    if all(s == "ok" for s in statuses):
        overall = "ok"
    elif any(s == "ok" for s in statuses):
        overall = "degraded"
    else:
        overall = "error"

    return {"status": overall, "agents": agents_status}


@router.get("/api/admin/stats", response_model=AdminStats)
async def get_admin_stats(user: UserContext = Depends(require_admin)):
    """Return aggregated admin statistics."""
    if not anomaly_service._redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    total_scored = await anomaly_service._redis_client.zcard(anomaly_service.SCORED_TRANSACTIONS_KEY)
    total_flagged = await anomaly_service._redis_client.zcard(anomaly_service.FLAGGED_TRANSACTIONS_KEY)

    pending = 0
    reviewed = 0
    cleared = 0
    for _, v in (await anomaly_service._redis_client.zrange(anomaly_service.FLAGGED_TRANSACTIONS_KEY, 0, -1, withscores=True)):
        pass  # just to keep the dict shape

    flagged_ids = await anomaly_service._redis_client.zrange(anomaly_service.FLAGGED_TRANSACTIONS_KEY, 0, -1)
    for tx_id in flagged_ids:
        raw = await anomaly_service._redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
        if not raw:
            continue
        tx = json.loads(raw)
        status = tx.get("status", "pending")
        if status == "pending":
            pending += 1
        elif status == "reviewed":
            reviewed += 1
        elif status == "cleared":
            cleared += 1

    scores = await anomaly_service._redis_client.zrange(anomaly_service.SCORED_TRANSACTIONS_KEY, 0, -1, withscores=True)
    avg_risk = sum(score for _, score in scores) / len(scores) if scores else 0
    high_risk = len([score for _, score in scores if score >= anomaly_service.FLAGGING_THRESHOLD])

    return AdminStats(
        totalFlagged=total_flagged,
        pendingReview=pending,
        reviewed=reviewed,
        cleared=cleared,
        avgRiskScore=avg_risk,
        totalScored=total_scored,
        highRiskCount=high_risk,
        aiCallsToday=anomaly_service._ai_calls_today,
    )


@router.get("/api/admin/transactions", response_model=list[ScoredTransaction])
async def list_scored_transactions(
    user: UserContext = Depends(require_admin),
    limit: int = Query(50, ge=1, le=500),
):
    """List all scored transactions (most recent/highest risk)."""
    if not anomaly_service._redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    scored_ids = await anomaly_service._redis_client.zrevrange(anomaly_service.SCORED_TRANSACTIONS_KEY, 0, limit - 1)
    results = []
    for tx_id in scored_ids:
        raw = await anomaly_service._redis_client.get(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}")
        if raw:
            results.append(ScoredTransaction.parse_raw(raw))
    return results


@router.get("/api/admin/flagged-transactions", response_model=list[FlaggedTransaction])
async def list_flagged_transactions(user: UserContext = Depends(require_admin)):
    """List all flagged transactions."""
    if not anomaly_service._redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    flagged_ids = await anomaly_service._redis_client.zrevrange(anomaly_service.FLAGGED_TRANSACTIONS_KEY, 0, -1)
    results = []
    for tx_id in flagged_ids:
        raw = await anomaly_service._redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
        if raw:
            results.append(FlaggedTransaction.parse_raw(raw))
    return results


@router.get("/api/admin/flagged-transactions/{tx_id}", response_model=FlaggedTransaction)
async def get_flagged_transaction(tx_id: str, user: UserContext = Depends(require_admin)):
    if not anomaly_service._redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await anomaly_service._redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Flagged transaction not found")
    return FlaggedTransaction.parse_raw(raw)


@router.get("/api/admin/scored-transactions/{tx_id}", response_model=ScoredTransaction)
async def get_scored_transaction(tx_id: str, user: UserContext = Depends(require_admin)):
    if not anomaly_service._redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await anomaly_service._redis_client.get(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Scored transaction not found")
    return ScoredTransaction.parse_raw(raw)


@router.post("/api/admin/scored-transactions/{tx_id}/rescore", response_model=ScoredTransaction)
async def rescore_transaction(tx_id: str, user: UserContext = Depends(require_admin)):
    if not anomaly_service._redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await anomaly_service._redis_client.get(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Scored transaction not found")

    original = json.loads(raw)
    transaction = {
        "transactionId": original.get("transactionId"),
        "accountId": original.get("accountId"),
        "userId": original.get("userId"),
        "amount": original.get("amount"),
        "type": original.get("type"),
        "description": original.get("description"),
        "category": original.get("category", ""),
    }

    scored_tx = await anomaly_service.score_and_store_transaction(transaction)
    return scored_tx


@router.put("/api/admin/flagged-transactions/{tx_id}/review", response_model=FlaggedTransaction)
async def review_flagged_transaction(tx_id: str, review: ReviewRequest, user: UserContext = Depends(require_admin)):
    if not anomaly_service._redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await anomaly_service._redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Flagged transaction not found")

    flagged = json.loads(raw)
    flagged["status"] = review.status
    flagged["notes"] = review.notes

    await anomaly_service._redis_client.set(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}", json.dumps(flagged))
    return FlaggedTransaction.parse_obj(flagged)


@router.get("/api/admin/prompts")
async def get_active_prompts(user: UserContext = Depends(require_admin)):
    """List the active prompt templates (names/types only)."""
    if not anomaly_service._analyzer_pipeline:
        raise HTTPException(status_code=503, detail="Analyzer pipeline not initialized")

    prompts = []
    for analyzer in anomaly_service._analyzer_pipeline.analyzers:
        if getattr(analyzer, "SYSTEM_PROMPT", None):
            prompts.append({
                "name": analyzer.name,
                "type": "risk-scoring",
                "enabled": analyzer.enabled,
            })

    for categorizer in anomaly_service._analyzer_pipeline.categorizers:
        if getattr(categorizer, "SYSTEM_PROMPT", None):
            prompts.append({
                "name": categorizer.name,
                "type": "categorization",
                "enabled": categorizer.enabled,
            })

    return prompts


@router.post("/api/admin/evaluate")
async def run_foundry_evaluation(request: EvalRequest, user: UserContext = Depends(require_admin)):
    """Run a Foundry evaluation using the Agent Framework's FoundryEvals.

    For each transaction, first gets the model's response using the provided
    system prompt, then evaluates the full conversation (system→user→assistant).
    """
    if not AGENT_FRAMEWORK_AVAILABLE:
        raise HTTPException(status_code=503, detail="Agent Framework not available")
    if not anomaly_service._foundry_endpoint or not anomaly_service._foundry_credential:
        raise HTTPException(status_code=503, detail="Foundry not configured")

    from agent_framework_foundry import FoundryEvals, FoundryChatClient, FoundryAgent
    from agent_framework._evaluation import EvalItem
    from agent_framework import Message

    client = FoundryChatClient(
        project_endpoint=anomaly_service._foundry_endpoint,
        model=anomaly_service._foundry_model or "gpt-5.4-mini",
        credential=anomaly_service._foundry_credential,
    )

    # Create a temporary agent with the prompt being evaluated
    eval_agent = FoundryAgent(
        project_endpoint=anomaly_service._foundry_endpoint,
        credential=anomaly_service._foundry_credential,
        agent_name="risk-assessor",
        agent_version="1",
        instructions=request.system_prompt,
    )

    eval_items = []
    for tx in request.transactions:
        prompt = (
            f"Assess this transaction:\n"
            f"- Amount: ${tx.get('amount', 0):,.2f}\n"
            f"- Type: {tx.get('type', 'Unknown')}\n"
            f"- Description: {tx.get('description', 'N/A')}\n"
            f"- Category: {tx.get('category', 'N/A')}\n"
            f"- Account: ****{str(tx.get('accountId', '')[-4:])}"
        )
        eval_items.append(
            EvalItem(
                input=[
                    Message.system(request.system_prompt),
                    Message.user(prompt),
                ],
                output="",
            )
        )

    evals = FoundryEvals(client=client, evaluators=request.evaluators)
    results = await evals.evaluate(eval_items)
    return {
        "status": "ok",
        "eval_name": request.eval_name,
        "results": results,
    }
