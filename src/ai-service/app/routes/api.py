import json
import os
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
    ScoreOverrideRequest,
)
from app.services import anomaly_service
from app.services.anomaly_service import AnomalyState, get_anomaly_state

logger = structlog.get_logger("ai-service")
router = APIRouter()

DEFAULT_FOUNDRY_EVAL_TIMEOUT_SECONDS = 540.0
DEFAULT_FOUNDRY_EVAL_POLL_SECONDS = 5.0
DEFAULT_FOUNDRY_EVAL_RECOVERY_TIMEOUT_SECONDS = 420.0


def _resolve_positive_float_env(var_name: str, default_value: float) -> float:
    """Parse a positive float env var with safe fallback."""
    raw = os.getenv(var_name)
    if not raw:
        return default_value
    try:
        parsed = float(raw)
        return parsed if parsed > 0 else default_value
    except (TypeError, ValueError):
        return default_value


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
async def ready(state: AnomalyState = Depends(get_anomaly_state)):
    checks = {"redis": False, "analyzer_pipeline": False}

    if state.redis_client:
        try:
            await state.redis_client.ping()
            checks["redis"] = True
        except redis.RedisError:
            pass

    if state.analyzer_pipeline and any(a.enabled for a in state.analyzer_pipeline.analyzers):
        checks["analyzer_pipeline"] = True

    all_ready = all(checks.values())
    status = "ready" if all_ready else "degraded"
    return {"status": status, "checks": checks}


@router.post("/detect", response_model=RiskAssessment)
async def detect(
    body: DetectRequest,
    user: UserContext = Depends(verify_jwt),
    state: AnomalyState = Depends(get_anomaly_state),
):
    """Score a single transaction synchronously (for on-demand assessment)."""
    if not state.analyzer_pipeline:
        raise HTTPException(status_code=503, detail="Analyzer pipeline not initialized")
    return await state.analyzer_pipeline.assess(body.model_dump(), state.redis_client)


@router.get("/api/admin/foundry-status")
async def foundry_status(
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
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
    if state.analyzer_pipeline:
        for a in state.analyzer_pipeline.analyzers:
            if a.name == "foundry-risk":
                risk_analyzer = a
                break
        for c in state.analyzer_pipeline.categorizers:
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
async def get_admin_stats(
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    """Return aggregated admin statistics."""
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    total_scored = await state.redis_client.zcard(anomaly_service.SCORED_TRANSACTIONS_KEY)
    total_flagged = await state.redis_client.zcard(anomaly_service.FLAGGED_TRANSACTIONS_KEY)

    pending = 0
    reviewed = 0
    cleared = 0
    for _, v in (await state.redis_client.zrange(anomaly_service.FLAGGED_TRANSACTIONS_KEY, 0, -1, withscores=True)):
        pass  # just to keep the dict shape

    flagged_ids = await state.redis_client.zrange(anomaly_service.FLAGGED_TRANSACTIONS_KEY, 0, -1)
    for tx_id in flagged_ids:
        raw = await state.redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
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

    scores = await state.redis_client.zrange(anomaly_service.SCORED_TRANSACTIONS_KEY, 0, -1, withscores=True)
    avg_risk = sum(score for _, score in scores) / len(scores) if scores else 0
    high_risk = len([score for _, score in scores if score >= anomaly_service.FLAGGING_THRESHOLD])

    # Get AI usage today from Redis
    ai_tokens = await anomaly_service.get_ai_tokens_today_from_redis(state.redis_client)
    ai_calls = await anomaly_service.get_ai_calls_today_from_redis(state.redis_client)
    if ai_tokens == 0 and ai_calls > 0:
        # Backward-compatible fallback for periods before token tracking was available.
        ai_tokens = ai_calls

    return AdminStats(
        totalFlagged=total_flagged,
        pendingReview=pending,
        reviewed=reviewed,
        cleared=cleared,
        avgRiskScore=avg_risk,
        totalScored=total_scored,
        highRiskCount=high_risk,
        aiTokensToday=ai_tokens,
        aiCallsToday=ai_calls,
    )


@router.get("/api/admin/transactions", response_model=list[ScoredTransaction])
async def list_scored_transactions(
    user: UserContext = Depends(require_admin),
    limit: int = Query(50, ge=1, le=500),
    state: AnomalyState = Depends(get_anomaly_state),
):
    """List all scored transactions (most recent/highest risk)."""
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    scored_ids = await state.redis_client.zrevrange(anomaly_service.SCORED_TRANSACTIONS_KEY, 0, limit - 1)
    results = []
    for tx_id in scored_ids:
        raw = await state.redis_client.get(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}")
        if raw:
            results.append(ScoredTransaction.parse_raw(raw))
    return results


@router.get("/api/admin/flagged-transactions", response_model=list[FlaggedTransaction])
async def list_flagged_transactions(
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    """List all flagged transactions."""
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")

    flagged_ids = await state.redis_client.zrevrange(anomaly_service.FLAGGED_TRANSACTIONS_KEY, 0, -1)
    results = []
    for tx_id in flagged_ids:
        raw = await state.redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
        if raw:
            results.append(FlaggedTransaction.parse_raw(raw))
    return results


@router.get("/api/admin/flagged-transactions/{tx_id}", response_model=FlaggedTransaction)
async def get_flagged_transaction(
    tx_id: str,
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await state.redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Flagged transaction not found")
    return FlaggedTransaction.parse_raw(raw)


@router.get("/api/admin/scored-transactions/{tx_id}", response_model=ScoredTransaction)
async def get_scored_transaction(
    tx_id: str,
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await state.redis_client.get(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Scored transaction not found")
    return ScoredTransaction.parse_raw(raw)


@router.post("/api/admin/scored-transactions/{tx_id}/rescore", response_model=ScoredTransaction)
async def rescore_transaction(
    tx_id: str,
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await state.redis_client.get(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}")
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

    scored_tx = await anomaly_service.score_and_store_transaction(
        transaction,
        state.analyzer_pipeline,
        state.redis_client,
    )
    return scored_tx


@router.put("/api/admin/flagged-transactions/{tx_id}/review", response_model=FlaggedTransaction)
async def review_flagged_transaction(
    tx_id: str,
    review: ReviewRequest,
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await state.redis_client.get(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Flagged transaction not found")

    flagged = json.loads(raw)
    outcome = review.outcome or review.status
    if not outcome:
        raise HTTPException(status_code=422, detail="Either outcome or status is required")
    if outcome == "escalated" and not review.escalateTo:
        raise HTTPException(status_code=422, detail="escalateTo is required when outcome is escalated")

    now = datetime.now(timezone.utc).isoformat()
    flagged["status"] = outcome
    flagged["outcome"] = outcome
    flagged["notes"] = review.notes or review.rationaleText or f"Marked as {outcome} by admin"
    flagged["reviewedBy"] = user.user_id
    flagged["reviewedByUsername"] = user.username
    flagged["reviewedAt"] = now
    flagged["adminConfidence"] = review.adminConfidence
    flagged["adminOverrideScore"] = review.overrideScore
    flagged["rationaleCategory"] = review.rationaleCategory
    flagged["rationaleText"] = review.rationaleText
    flagged["escalatedTo"] = review.escalateTo

    await state.redis_client.set(f"{anomaly_service.FLAGGED_TRANSACTION_PREFIX}{tx_id}", json.dumps(flagged))
    return FlaggedTransaction.parse_obj(flagged)


@router.put("/api/admin/scored-transactions/{tx_id}/override", response_model=ScoredTransaction)
async def override_scored_transaction(
    tx_id: str,
    override: ScoreOverrideRequest,
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    """Record an admin decision about a scored transaction."""
    if not state.redis_client:
        raise HTTPException(status_code=503, detail="Redis not available")
    raw = await state.redis_client.get(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Scored transaction not found")

    scored = json.loads(raw)
    scored["adminOverride"] = {
        "decision": override.decision,
        "correctedScore": override.correctedScore,
        "rationale": override.rationale,
        "reviewedBy": user.user_id,
        "reviewedByUsername": user.username,
        "reviewedAt": datetime.now(timezone.utc).isoformat(),
    }
    await state.redis_client.set(f"{anomaly_service.SCORED_TRANSACTION_PREFIX}{tx_id}", json.dumps(scored))
    return ScoredTransaction.parse_obj(scored)


@router.get("/api/admin/prompts")
async def get_active_prompts(
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    """List the active prompt templates (names/types only)."""
    if not state.analyzer_pipeline:
        raise HTTPException(status_code=503, detail="Analyzer pipeline not initialized")

    prompts = []
    for analyzer in state.analyzer_pipeline.analyzers:
        system_prompt = getattr(analyzer, "SYSTEM_PROMPT", None)
        if system_prompt:
            prompts.append({
                "name": analyzer.name,
                "type": "risk-scoring",
                "enabled": analyzer.enabled,
                "systemPrompt": system_prompt,
            })

    for categorizer in state.analyzer_pipeline.categorizers:
        system_prompt = getattr(categorizer, "SYSTEM_PROMPT", None)
        if system_prompt:
            prompts.append({
                "name": categorizer.name,
                "type": "categorization",
                "enabled": categorizer.enabled,
                "systemPrompt": system_prompt,
            })

    return prompts


@router.post("/api/admin/evaluate")
async def run_foundry_evaluation(
    request: EvalRequest,
    user: UserContext = Depends(require_admin),
    state: AnomalyState = Depends(get_anomaly_state),
):
    """Run an LLM-as-judge evaluation against the prompt under test.

    For each transaction:
      1. Invoke the prompt-under-test agent to get the assistant response.
      2. Invoke a separate judge agent that scores the conversation against
         each requested evaluator (coherence, fluency, relevance, etc.) on a
         1-5 scale, returning JSON. A score of >=3 counts as passed.

    This bypasses Foundry's raisvc evaluator pipeline, which does not work
    when the Foundry account is deployed in a managed VNet — the raisvc
    workers cannot write the inline JSONL dataset to private-endpoint blob
    storage. See `.squad/skills/foundry-eval-debugging/SKILL.md` rung -1 and
    issue #145.

    The response shape matches what prompt-eval-service and the admin UI
    expect from the previous FoundryEvals path so callers do not change.
    """
    if not AGENT_FRAMEWORK_AVAILABLE:
        raise HTTPException(status_code=503, detail="Agent Framework not available")
    if not state.foundry_endpoint or not state.foundry_credential:
        raise HTTPException(status_code=503, detail="Foundry not configured")

    from agent_framework_foundry import FoundryAgent

    import uuid as _uuid

    eval_model = state.foundry_model or "gpt-5.4-mini"
    request_id = _uuid.uuid4().hex
    eval_log = logger.bind(
        component="run_llm_judge_evaluation",
        request_id=request_id,
        eval_name=request.eval_name,
        eval_deployment=eval_model,
        evaluators=request.evaluators,
        n_test_inputs=len(request.transactions),
        foundry_endpoint=state.foundry_endpoint,
        foundry_model=state.foundry_model,
        principal_user_id=getattr(user, "user_id", None),
    )

    # Agent under test — gets the assistant response using the prompt being
    # evaluated. Same Foundry agent setup the FoundryEvals path used.
    candidate_agent = FoundryAgent(
        project_endpoint=state.foundry_endpoint,
        credential=state.foundry_credential,
        agent_name="risk-assessor",
        agent_version="1",
        instructions=request.system_prompt,
        default_options={"extra_body": {"model": eval_model}},
    )

    judge_instructions = _build_judge_instructions(request.evaluators)
    judge_agent = FoundryAgent(
        project_endpoint=state.foundry_endpoint,
        credential=state.foundry_credential,
        agent_name="risk-assessor",
        agent_version="1",
        instructions=judge_instructions,
        default_options={"extra_body": {"model": eval_model}},
    )

    eval_log.info("llm_judge.invoke.start")

    items: list[dict] = []
    per_evaluator_passed: dict[str, int] = {ev: 0 for ev in request.evaluators}
    per_evaluator_failed: dict[str, int] = {ev: 0 for ev in request.evaluators}
    total_passed = 0
    total_failed = 0

    for tx in request.transactions:
        user_prompt = (
            f"Assess this transaction:\n"
            f"- Amount: ${tx.get('amount', 0):,.2f}\n"
            f"- Type: {tx.get('type', 'Unknown')}\n"
            f"- Description: {tx.get('description', 'N/A')}\n"
            f"- Category: {tx.get('category', 'N/A')}\n"
            f"- Account: ****{str(tx.get('accountId', '')[-4:])}"
        )

        candidate_session = candidate_agent.create_session()
        try:
            candidate_response = await candidate_agent.run(user_prompt, session=candidate_session)
        except Exception as exc:  # noqa: BLE001
            import traceback
            from app.telemetry import extract_openai_error_fields
            diag = extract_openai_error_fields(exc)
            eval_log.error(
                "llm_judge.candidate.failed",
                traceback=traceback.format_exc(),
                **diag,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Candidate agent failed: {exc}",
            )

        assistant_text = (
            getattr(candidate_response, "text", None) or "(no response)"
        )

        judge_prompt = _build_judge_user_prompt(
            system_prompt=request.system_prompt,
            user_prompt=user_prompt,
            assistant_text=assistant_text,
            evaluators=request.evaluators,
        )
        judge_session = judge_agent.create_session()
        try:
            judge_response = await judge_agent.run(judge_prompt, session=judge_session)
        except Exception as exc:  # noqa: BLE001
            import traceback
            from app.telemetry import extract_openai_error_fields
            diag = extract_openai_error_fields(exc)
            eval_log.error(
                "llm_judge.judge.failed",
                traceback=traceback.format_exc(),
                **diag,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Judge agent failed: {exc}",
            )

        judge_text = getattr(judge_response, "text", None) or ""
        scores = _parse_judge_scores(judge_text, request.evaluators)

        item_all_passed = True
        item_scores_out: dict[str, dict] = {}
        for evaluator in request.evaluators:
            score_obj = scores.get(evaluator) or {
                "score": 0,
                "passed": False,
                "reason": "Judge did not return this evaluator",
            }
            passed = bool(score_obj.get("passed", False))
            if passed:
                per_evaluator_passed[evaluator] += 1
            else:
                per_evaluator_failed[evaluator] += 1
                item_all_passed = False
            item_scores_out[evaluator] = {
                "score": score_obj.get("score"),
                "passed": passed,
                "reason": score_obj.get("reason"),
            }

        if item_all_passed:
            total_passed += 1
        else:
            total_failed += 1

        items.append(
            {
                "query": user_prompt,
                "response": assistant_text,
                "status": "completed",
                "query_messages": [
                    {"role": "system", "content": request.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_messages": [
                    {"role": "assistant", "content": assistant_text},
                ],
                "scores": item_scores_out,
                "transactionId": tx.get("id") or tx.get("transactionId"),
            }
        )

    per_evaluator = {
        ev: {"passed": per_evaluator_passed[ev], "failed": per_evaluator_failed[ev]}
        for ev in request.evaluators
    }
    total = len(items)
    all_passed = total_failed == 0 and total > 0

    eval_log.info(
        "llm_judge.invoke.ok",
        total=total,
        passed=total_passed,
        failed=total_failed,
    )

    return {
        "total": total,
        "passed": total_passed,
        "failed": total_failed,
        "all_passed": all_passed,
        "per_evaluator": per_evaluator,
        "eval_id": f"local-llm-judge-{request_id}",
        "run_id": f"local-llm-judge-run-{request_id}",
        "status": "completed",
        "items": items,
    }


_JUDGE_SCORE_THRESHOLD = 3


def _build_judge_instructions(evaluators: list[str]) -> str:
    """System prompt for the LLM-as-judge agent."""
    criteria_lines = "\n".join(
        f"- **{ev}**: {_evaluator_description(ev)}" for ev in evaluators
    )
    return (
        "You are an impartial evaluator scoring an AI assistant's response "
        "against specific quality criteria.\n\n"
        "## Criteria\n"
        f"{criteria_lines}\n\n"
        "## Scoring scale (1-5)\n"
        "- 1: Very poor — fails the criterion entirely\n"
        "- 2: Poor — significant gaps\n"
        "- 3: Acceptable — meets the criterion (passing threshold)\n"
        "- 4: Good — clearly meets the criterion\n"
        "- 5: Excellent — exemplary on this criterion\n\n"
        f"A score of {_JUDGE_SCORE_THRESHOLD} or higher counts as `passed: true`.\n\n"
        "## Output\n"
        "Return ONLY a single JSON object with one key per criterion. "
        "Each value is an object: "
        '`{"score": <1-5 integer>, "passed": <boolean>, "reason": "<one sentence>"}`. '
        "No markdown, no prose outside the JSON, no code fences."
    )


def _evaluator_description(name: str) -> str:
    """Short description for a built-in evaluator name."""
    descriptions = {
        "coherence": "Is the response internally consistent and logically structured?",
        "fluency": "Is the response well-written, grammatically correct, and natural?",
        "relevance": "Does the response directly address the user's prompt?",
        "groundedness": "Is the response factually consistent with the input context?",
        "task_adherence": "Does the response follow the system prompt's instructions?",
        "task_completion": "Does the response fully complete the requested task?",
        "intent_resolution": "Does the response address the user's underlying intent?",
        "response_completeness": "Is the response complete with no critical missing parts?",
        "similarity": "Is the response similar in style/intent to expected output?",
    }
    return descriptions.get(
        name.removeprefix("builtin."),
        "Score the response on this dimension on a 1-5 scale.",
    )


def _build_judge_user_prompt(
    *,
    system_prompt: str,
    user_prompt: str,
    assistant_text: str,
    evaluators: list[str],
) -> str:
    """User prompt that gives the judge the conversation to grade."""
    keys = ", ".join(f'"{ev}"' for ev in evaluators)
    return (
        "Grade the following conversation. Return JSON with keys: "
        f"{keys}.\n\n"
        f"### System prompt under evaluation\n{system_prompt}\n\n"
        f"### User message\n{user_prompt}\n\n"
        f"### Assistant response\n{assistant_text}\n"
    )


def _parse_judge_scores(
    judge_text: str, evaluators: list[str]
) -> dict[str, dict]:
    """Parse the judge's JSON output. Tolerant of markdown fences/prose."""
    if not judge_text:
        return {}
    candidate = judge_text.strip()
    # Strip markdown code fences if present.
    if candidate.startswith("```"):
        candidate = candidate.split("```", 2)
        candidate = candidate[1] if len(candidate) >= 2 else ""
        if candidate.startswith("json"):
            candidate = candidate[4:]
    # Find the first balanced JSON object.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    snippet = candidate[start : end + 1]
    try:
        parsed = json.loads(snippet)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}

    out: dict[str, dict] = {}
    for ev in evaluators:
        raw = parsed.get(ev) or parsed.get(ev.removeprefix("builtin."))
        if not isinstance(raw, dict):
            continue
        score_val = raw.get("score")
        try:
            score_num = float(score_val) if score_val is not None else None
        except (TypeError, ValueError):
            score_num = None
        passed_field = raw.get("passed")
        if isinstance(passed_field, bool):
            passed = passed_field
        elif score_num is not None:
            passed = score_num >= _JUDGE_SCORE_THRESHOLD
        else:
            passed = False
        reason = raw.get("reason")
        if reason is not None and not isinstance(reason, str):
            reason = str(reason)
        out[ev] = {
            "score": score_num,
            "passed": passed,
            "reason": reason,
        }
    return out
