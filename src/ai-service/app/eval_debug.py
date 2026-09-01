"""Interactive Foundry evaluation debugger for in-cluster iteration."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
from dataclasses import dataclass, field
from typing import Any

from azure.identity import DefaultAzureCredential

DEFAULT_FOUNDRY_EVAL_TIMEOUT_SECONDS = 180.0
DEFAULT_FOUNDRY_EVAL_POLL_SECONDS = 5.0
DEFAULT_AGENT_RUN_TIMEOUT_SECONDS = 60.0
DEFAULT_EVAL_HARD_TIMEOUT_SECONDS = 240.0
DEFAULT_PROGRESS_INTERVAL_SECONDS = 10.0
DEFAULT_EVALUATORS = ["coherence", "fluency", "relevance"]
DEFAULT_SYSTEM_PROMPT = (
    "You are a transaction risk reviewer. Return a concise, factual summary "
    "with risk score drivers."
)
DEFAULT_TRANSACTION = {
    "amount": 2500.0,
    "type": "TRANSFER",
    "description": "Wire transfer to external beneficiary",
    "category": "Transfer",
    "accountId": "acct-1234567890",
}


@dataclass
class EvalDebugState:
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    transaction: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_TRANSACTION))
    evaluators: list[str] = field(default_factory=lambda: list(DEFAULT_EVALUATORS))
    eval_name: str = "Eval Debug Run"
    eval_timeout_seconds: float = DEFAULT_FOUNDRY_EVAL_TIMEOUT_SECONDS
    poll_seconds: float = DEFAULT_FOUNDRY_EVAL_POLL_SECONDS
    agent_run_timeout_seconds: float = DEFAULT_AGENT_RUN_TIMEOUT_SECONDS
    eval_hard_timeout_seconds: float = DEFAULT_EVAL_HARD_TIMEOUT_SECONDS
    last_eval_id: str | None = None
    last_run_id: str | None = None


def _resolve_positive_float_env(var_name: str, default_value: float) -> float:
    raw = os.getenv(var_name)
    if not raw:
        return default_value
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default_value
    return parsed if parsed > 0 else default_value


def _parse_positive_float(raw: str, field_name: str) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return value


def _parse_transaction_json(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("transaction JSON must be an object")
    return parsed


def _parse_evaluators(raw: str) -> list[str]:
    evaluators = [item.strip() for item in raw.split(",") if item.strip()]
    if not evaluators:
        raise ValueError("at least one evaluator is required")
    return evaluators


def _build_eval_prompt(transaction: dict[str, Any]) -> str:
    account_id = str(transaction.get("accountId", "") or "")
    account_suffix = account_id[-4:] if account_id else "N/A"
    account_display = f"****{account_suffix}" if account_suffix != "N/A" else "N/A"
    try:
        amount = float(transaction.get("amount", 0) or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return (
        "Assess this transaction:\n"
        f"- Amount: ${amount:,.2f}\n"
        f"- Type: {transaction.get('type', 'Unknown')}\n"
        f"- Description: {transaction.get('description', 'N/A')}\n"
        f"- Category: {transaction.get('category', 'N/A')}\n"
        f"- Account: {account_display}"
    )


def _read_multiline_input(prompt: str) -> str:
    print(prompt)
    print("Finish input with EOF on its own line.")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "EOF":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _print_state(state: EvalDebugState, endpoint: str, model: str) -> None:
    print("\nCurrent configuration")
    print("---------------------")
    print(f"Endpoint: {endpoint}")
    print(f"Model: {model}")
    print(f"Eval name: {state.eval_name}")
    print(f"Evaluators: {', '.join(state.evaluators)}")
    print(f"Eval timeout seconds: {state.eval_timeout_seconds}")
    print(f"Poll seconds: {state.poll_seconds}")
    print(f"Agent run timeout seconds: {state.agent_run_timeout_seconds}")
    print(f"Hard timeout seconds: {state.eval_hard_timeout_seconds}")
    print("System prompt:")
    print(state.system_prompt)
    print("Transaction JSON:")
    print(json.dumps(state.transaction, indent=2))
    print()


async def _await_with_progress(
    coro: Any,
    label: str,
    timeout_seconds: float,
    interval_seconds: float = DEFAULT_PROGRESS_INTERVAL_SECONDS,
) -> Any:
    start = asyncio.get_running_loop().time()
    deadline = start + timeout_seconds
    task = asyncio.create_task(coro)

    try:
        while True:
            now = asyncio.get_running_loop().time()
            remaining = deadline - now
            if remaining <= 0:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise TimeoutError(f"{label} timed out after {timeout_seconds:.0f}s")

            step = min(interval_seconds, remaining)
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=step)
            except asyncio.TimeoutError:
                elapsed = asyncio.get_running_loop().time() - start
                print(f"{label} in progress... {elapsed:.0f}s elapsed")
    finally:
        if task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _print_timeouts(state: EvalDebugState) -> None:
    print("\nTimeouts")
    print("--------")
    print(f"eval_timeout_seconds: {state.eval_timeout_seconds}")
    print(f"poll_seconds: {state.poll_seconds}")
    print(f"agent_run_timeout_seconds: {state.agent_run_timeout_seconds}")
    print(f"eval_hard_timeout_seconds: {state.eval_hard_timeout_seconds}")
    print()


def _model_to_dict(obj: Any) -> Any:
    """Best-effort conversion of an OpenAI/pydantic SDK object to a plain dict."""
    if obj is None:
        return None
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # noqa: BLE001
                continue
    if isinstance(obj, (list, tuple)):
        return [_model_to_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _model_to_dict(v) for k, v in obj.items()}
    return obj


def _pretty_dump_model(obj: Any) -> None:
    try:
        data = _model_to_dict(obj)
        print(json.dumps(data, indent=2, default=str))
    except Exception as exc:  # noqa: BLE001
        print(f"<could not serialize: {exc}>")
        print(repr(obj))


async def _with_foundry_client(endpoint: str, model: str, fn: Any) -> Any:
    """Open a FoundryChatClient, run an async fn with it, then close credentials."""
    from agent_framework_foundry import FoundryChatClient

    credential = DefaultAzureCredential()
    try:
        client = FoundryChatClient(
            project_endpoint=endpoint,
            model=model,
            credential=credential,
        )
        return await fn(client)
    finally:
        close_credential = getattr(credential, "close", None)
        if callable(close_credential):
            close_credential()


async def _list_evals(endpoint: str, model: str, limit: int = 20) -> None:
    print(f"\nListing recent evals from project endpoint (limit={limit})...")

    async def _do(client):
        page = await client.client.evals.list(limit=limit, order="desc")
        rows = []
        async for item in page:
            rows.append(item)
        if not rows:
            print("No evals found.")
            return
        print(f"\n{'EVAL_ID':<46}  {'CREATED':<25}  NAME")
        for ev in rows:
            ev_id = getattr(ev, "id", "?")
            created = getattr(ev, "created_at", "?")
            name = getattr(ev, "name", "?")
            print(f"{ev_id:<46}  {str(created):<25}  {name}")

    await _with_foundry_client(endpoint, model, _do)


async def _list_runs(endpoint: str, model: str, eval_id: str, limit: int = 20) -> None:
    print(f"\nListing runs for eval {eval_id} (limit={limit})...")

    async def _do(client):
        page = await client.client.evals.runs.list(eval_id=eval_id, limit=limit, order="desc")
        rows = []
        async for item in page:
            rows.append(item)
        if not rows:
            print("No runs found.")
            return
        print(f"\n{'RUN_ID':<46}  {'STATUS':<14}  {'CREATED':<25}  NAME")
        for r in rows:
            run_id = getattr(r, "id", "?")
            status = getattr(r, "status", "?")
            created = getattr(r, "created_at", "?")
            name = getattr(r, "name", "?")
            print(f"{run_id:<46}  {status:<14}  {str(created):<25}  {name}")

    await _with_foundry_client(endpoint, model, _do)


async def _inspect_eval(endpoint: str, model: str, eval_id: str) -> None:
    print(f"\nFetching eval {eval_id}...")

    async def _do(client):
        ev = await client.client.evals.retrieve(eval_id=eval_id)
        _pretty_dump_model(ev)

    await _with_foundry_client(endpoint, model, _do)


async def _inspect_run(endpoint: str, model: str, eval_id: str, run_id: str) -> None:
    print(f"\nFetching run {run_id} (eval {eval_id})...")

    async def _do(client):
        run = await client.client.evals.runs.retrieve(run_id=run_id, eval_id=eval_id)
        _pretty_dump_model(run)
        # Also try to list output_items so we see if any were produced.
        try:
            print("\nOutput items:")
            page = await client.client.evals.runs.output_items.list(
                run_id=run_id, eval_id=eval_id
            )
            count = 0
            async for oi in page:
                count += 1
                _pretty_dump_model(oi)
            if count == 0:
                print("(none)")
        except Exception as exc:  # noqa: BLE001
            print(f"(could not list output_items: {exc})")

    await _with_foundry_client(endpoint, model, _do)


async def _watch_run(
    endpoint: str,
    model: str,
    eval_id: str,
    run_id: str,
    poll_seconds: float,
    max_seconds: float,
) -> None:
    print(
        f"\nWatching run {run_id} every {poll_seconds:.0f}s "
        f"for up to {max_seconds:.0f}s. Ctrl+C to stop."
    )
    print(f"{'ELAPSED':>8}  STATUS         RESULT_COUNTS")

    async def _do(client):
        loop = asyncio.get_running_loop()
        start = loop.time()
        last_status = None
        while True:
            elapsed = loop.time() - start
            if elapsed > max_seconds:
                print(f"\n⏱️  Stopped after {elapsed:.0f}s without terminal status.")
                return
            try:
                run = await client.client.evals.runs.retrieve(
                    run_id=run_id, eval_id=eval_id
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  (retrieve failed: {exc})")
                await asyncio.sleep(poll_seconds)
                continue
            status = getattr(run, "status", "?")
            counts = getattr(run, "result_counts", None)
            counts_str = json.dumps(_model_to_dict(counts), default=str) if counts else "—"
            marker = "*" if status != last_status else " "
            print(f"{elapsed:>7.0f}s {marker} {status:<13} {counts_str}")
            last_status = status
            if status in ("completed", "failed", "canceled"):
                err = getattr(run, "error", None)
                if err:
                    print(f"\nFinal error: {_model_to_dict(err)}")
                report_url = getattr(run, "report_url", None)
                if report_url:
                    print(f"Report URL: {report_url}")
                return
            await asyncio.sleep(poll_seconds)

    await _with_foundry_client(endpoint, model, _do)


def _print_payload(state: EvalDebugState, model: str) -> None:
    """Print the EXACT data_source.content payload that would be sent to Foundry."""
    from agent_framework import Message
    from agent_framework._evaluation import (
        AgentEvalConverter,
        ConversationSplit,
        EvalItem,
    )

    user_prompt = _build_eval_prompt(state.transaction)
    item = EvalItem(
        conversation=[
            Message("system", [state.system_prompt]),
            Message("user", [user_prompt]),
            Message("assistant", ["(would be filled in from agent.run)"]),
        ]
    )
    split = ConversationSplit.LAST_TURN
    query_msgs, response_msgs = item.split_messages(split)
    query_text = " ".join(m.text for m in query_msgs if m.role == "user" and m.text).strip()
    response_text = " ".join(
        m.text for m in response_msgs if m.role == "assistant" and m.text
    ).strip()
    payload = {
        "query": query_text,
        "response": response_text,
        "query_messages": AgentEvalConverter.convert_messages(query_msgs),
        "response_messages": AgentEvalConverter.convert_messages(response_msgs),
    }
    print(f"\nPayload (one EvalItem dict, model={model}):")
    print(json.dumps(payload, indent=2, default=str))


def _print_help() -> None:
    print(
        "\nCommands:\n"
        "  show              - print current configuration\n"
        "  prompt            - edit system prompt (multi-line, end with EOF)\n"
        "  tx                - edit transaction JSON (multi-line, end with EOF)\n"
        "  evals             - set evaluators (comma-separated)\n"
        "  name              - set eval run name\n"
        "  timeouts          - inspect/update timeouts\n"
        "  payload           - dump the JSONL payload that would be sent\n"
        "  run               - execute one Foundry eval and dump live state\n"
        "  list-evals        - list recent evals from the project endpoint\n"
        "  list-runs [id]    - list runs for an eval (default: last eval)\n"
        "  eval [id]         - dump raw eval definition (default: last)\n"
        "  inspect [eid rid] - dump raw run + output_items (default: last run)\n"
        "  watch [eid rid]   - poll a run continuously, log status changes\n"
        "  last              - show last eval_id/run_id captured this session\n"
        "  help              - this menu\n"
        "  quit              - exit\n"
    )


def _update_timeouts_interactive(state: EvalDebugState) -> None:
    _print_timeouts(state)
    eval_timeout_raw = input(
        f"Eval timeout seconds [{state.eval_timeout_seconds}]: "
    ).strip()
    poll_raw = input(f"Poll seconds [{state.poll_seconds}]: ").strip()
    agent_timeout_raw = input(
        f"Agent run timeout seconds [{state.agent_run_timeout_seconds}]: "
    ).strip()
    hard_timeout_raw = input(
        f"Hard timeout seconds [{state.eval_hard_timeout_seconds}]: "
    ).strip()

    try:
        if eval_timeout_raw:
            state.eval_timeout_seconds = _parse_positive_float(
                eval_timeout_raw, "eval timeout seconds"
            )
        if poll_raw:
            state.poll_seconds = _parse_positive_float(poll_raw, "poll seconds")
        if agent_timeout_raw:
            state.agent_run_timeout_seconds = _parse_positive_float(
                agent_timeout_raw, "agent run timeout seconds"
            )
        if hard_timeout_raw:
            state.eval_hard_timeout_seconds = _parse_positive_float(
                hard_timeout_raw, "hard timeout seconds"
            )
    except ValueError as exc:
        print(f"Invalid timeout value: {exc}")
        return

    print("Timeouts updated.")
    _print_timeouts(state)


async def _run_eval_once(
    state: EvalDebugState,
    endpoint: str,
    model: str,
) -> None:
    """Run a single LLM-as-judge evaluation locally (issue #145 workaround).

    Mirrors the `/api/admin/evaluate` server-side path: candidate agent
    produces the assistant response, judge agent scores the conversation,
    parsed JSON scores are printed. No Foundry-native evals (raisvc) — those
    don't work in managed VNet.
    """
    from agent_framework_foundry import FoundryAgent

    # Import judge helpers from the route module so prod and debug use the
    # exact same prompt + parser.
    from app.routes.api import (
        _build_judge_instructions,
        _build_judge_user_prompt,
        _parse_judge_scores,
        _with_system_prompt,
    )

    credential = DefaultAzureCredential()
    try:
        candidate_agent = FoundryAgent(
            project_endpoint=endpoint,
            credential=credential,
            agent_name="risk-assessor",
            agent_version=None,  # newest version — provisioned by init_agents
            default_options={"extra_body": {"model": model}},
        )
        judge_instructions = _build_judge_instructions(state.evaluators)
        judge_agent = FoundryAgent(
            project_endpoint=endpoint,
            credential=credential,
            agent_name="risk-assessor",
            agent_version=None,  # newest version — provisioned by init_agents
            default_options={"extra_body": {"model": model}},
        )

        user_prompt = _build_eval_prompt(state.transaction)
        candidate_session = candidate_agent.create_session()
        print(
            f"\nCalling candidate agent (timeout {state.agent_run_timeout_seconds:.0f}s)..."
        )
        candidate_response = await _await_with_progress(
            candidate_agent.run(
                _with_system_prompt(state.system_prompt, user_prompt),
                session=candidate_session,
            ),
            "Candidate call",
            timeout_seconds=state.agent_run_timeout_seconds,
        )
        if candidate_response is None:
            print(
                "\n⚠️  candidate response is None — using sentinel text."
            )
            assistant_text = "(no response)"
        else:
            assistant_text = getattr(candidate_response, "text", None) or "(no response)"

        judge_prompt = _build_judge_user_prompt(
            system_prompt=state.system_prompt,
            user_prompt=user_prompt,
            assistant_text=assistant_text,
            evaluators=state.evaluators,
        )
        judge_session = judge_agent.create_session()
        print(
            f"Calling judge agent (timeout {state.agent_run_timeout_seconds:.0f}s)..."
        )
        judge_response = await _await_with_progress(
            judge_agent.run(
                _with_system_prompt(judge_instructions, judge_prompt),
                session=judge_session,
            ),
            "Judge call",
            timeout_seconds=state.agent_run_timeout_seconds,
        )
        judge_text = (
            getattr(judge_response, "text", None) if judge_response else ""
        ) or ""
        scores = _parse_judge_scores(judge_text, state.evaluators)

        print("\nEvaluation run complete (LLM-as-judge)")
        print("--------------------------------------")
        total = len(state.evaluators)
        passed_count = sum(1 for ev in state.evaluators if scores.get(ev, {}).get("passed"))
        failed_count = total - passed_count
        print(f"Status: completed")
        print(f"Evaluators: {total}")
        print(f"Passed: {passed_count}")
        print(f"Failed: {failed_count}")

        print("\nModel response")
        print("--------------")
        print(assistant_text)

        print("\nEvaluator scores")
        print("----------------")
        for ev in state.evaluators:
            score_obj = scores.get(ev)
            if score_obj is None:
                print(f"- {ev}: (no score returned by judge)")
                continue
            print(
                f"- {ev}: score={score_obj.get('score')}, passed={score_obj.get('passed')}"
            )
            reason = score_obj.get("reason")
            if reason:
                print(f"  reason: {reason}")

        if not scores:
            print("\nRaw judge output (could not parse JSON):")
            print(judge_text or "(empty)")
    finally:
        close_credential = getattr(credential, "close", None)
        if callable(close_credential):
            close_credential()


async def _run_repl(
    state: EvalDebugState,
    endpoint: str,
    model: str,
) -> None:
    print("Eval debug REPL — type `help` for commands.")
    while True:
        try:
            raw = input("eval-debug> ").strip()
        except EOFError:
            print()
            return
        if not raw:
            continue
        parts = raw.split()
        command = parts[0].lower()
        args = parts[1:]

        if command in {"quit", "exit"}:
            return
        if command == "help":
            _print_help()
            continue
        if command == "show":
            _print_state(state, endpoint, model)
            continue
        if command == "prompt":
            updated_prompt = _read_multiline_input("Enter system prompt:")
            if updated_prompt:
                state.system_prompt = updated_prompt
                print("System prompt updated.")
            else:
                print("System prompt unchanged.")
            continue
        if command == "tx":
            raw_tx = _read_multiline_input("Enter transaction JSON object:")
            if not raw_tx:
                print("Transaction unchanged.")
                continue
            try:
                state.transaction = _parse_transaction_json(raw_tx)
                print("Transaction updated.")
            except ValueError as exc:
                print(f"Invalid transaction JSON: {exc}")
            continue
        if command == "evals":
            raw_evals = input("Evaluators (comma-separated): ").strip()
            try:
                state.evaluators = _parse_evaluators(raw_evals)
                print("Evaluators updated.")
            except ValueError as exc:
                print(f"Invalid evaluators: {exc}")
            continue
        if command == "name":
            name = input("Eval name: ").strip()
            if name:
                state.eval_name = name
                print("Eval name updated.")
            else:
                print("Eval name unchanged.")
            continue
        if command == "timeouts":
            _update_timeouts_interactive(state)
            continue
        if command == "payload":
            _print_payload(state, model)
            continue
        if command == "run":
            try:
                await _run_eval_once(state, endpoint, model)
            except Exception as exc:  # noqa: BLE001
                print(f"\nEvaluation failed: {exc}")
                traceback.print_exc()
            continue
        if command == "list-evals":
            try:
                await _list_evals(endpoint, model)
            except Exception as exc:  # noqa: BLE001
                print(f"\nlist-evals failed: {exc}")
                traceback.print_exc()
            continue
        if command == "list-runs":
            eval_id = args[0] if args else state.last_eval_id
            if not eval_id:
                print("Provide an eval_id or run `run` first.")
                continue
            try:
                await _list_runs(endpoint, model, eval_id)
            except Exception as exc:  # noqa: BLE001
                print(f"\nlist-runs failed: {exc}")
                traceback.print_exc()
            continue
        if command == "eval":
            eval_id = args[0] if args else state.last_eval_id
            if not eval_id:
                print("Provide an eval_id or run `run` first.")
                continue
            try:
                await _inspect_eval(endpoint, model, eval_id)
            except Exception as exc:  # noqa: BLE001
                print(f"\neval failed: {exc}")
                traceback.print_exc()
            continue
        if command == "inspect":
            if len(args) >= 2:
                eval_id, run_id = args[0], args[1]
            else:
                eval_id, run_id = state.last_eval_id, state.last_run_id
            if not eval_id or not run_id:
                print("Provide eval_id and run_id, or run `run` first.")
                continue
            try:
                await _inspect_run(endpoint, model, eval_id, run_id)
            except Exception as exc:  # noqa: BLE001
                print(f"\ninspect failed: {exc}")
                traceback.print_exc()
            continue
        if command == "watch":
            if len(args) >= 2:
                eval_id, run_id = args[0], args[1]
            else:
                eval_id, run_id = state.last_eval_id, state.last_run_id
            if not eval_id or not run_id:
                print("Provide eval_id and run_id, or run `run` first.")
                continue
            try:
                await _watch_run(
                    endpoint,
                    model,
                    eval_id,
                    run_id,
                    poll_seconds=max(state.poll_seconds, 5.0),
                    max_seconds=state.eval_hard_timeout_seconds,
                )
            except KeyboardInterrupt:
                print("\nWatch interrupted.")
            except Exception as exc:  # noqa: BLE001
                print(f"\nwatch failed: {exc}")
                traceback.print_exc()
            continue
        if command == "last":
            print(f"last_eval_id = {state.last_eval_id}")
            print(f"last_run_id  = {state.last_run_id}")
            continue

        print(f"Unknown command: {command!r}. Type `help`.")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive Foundry evaluation debugger for in-cluster use."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one evaluation with current config and exit.",
    )
    parser.add_argument(
        "--eval-timeout-seconds",
        type=float,
        help="Override Foundry eval SDK timeout for this invocation.",
    )
    parser.add_argument(
        "--eval-poll-seconds",
        type=float,
        help="Override Foundry eval poll interval for this invocation.",
    )
    parser.add_argument(
        "--agent-run-timeout-seconds",
        type=float,
        help="Override timeout for the initial agent.run call.",
    )
    parser.add_argument(
        "--hard-timeout-seconds",
        type=float,
        help="Override overall hard timeout for the eval wait loop.",
    )
    return parser


def _resolve_cli_or_env_positive_float(
    cli_value: float | None,
    env_name: str,
    default_value: float,
) -> float:
    if cli_value is None:
        return _resolve_positive_float_env(env_name, default_value)
    return cli_value if cli_value > 0 else default_value


async def _run() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        raise RuntimeError(
            "FOUNDRY_PROJECT_ENDPOINT (or AZURE_OPENAI_ENDPOINT fallback) must be set."
        )

    model = os.getenv("FOUNDRY_MODEL", "gpt-5.4-mini")
    state = EvalDebugState(
        eval_timeout_seconds=_resolve_cli_or_env_positive_float(
            args.eval_timeout_seconds,
            "FOUNDRY_EVAL_TIMEOUT_SECONDS",
            DEFAULT_FOUNDRY_EVAL_TIMEOUT_SECONDS,
        ),
        poll_seconds=_resolve_cli_or_env_positive_float(
            args.eval_poll_seconds,
            "FOUNDRY_EVAL_POLL_SECONDS",
            DEFAULT_FOUNDRY_EVAL_POLL_SECONDS,
        ),
        agent_run_timeout_seconds=_resolve_cli_or_env_positive_float(
            args.agent_run_timeout_seconds,
            "EVAL_DEBUG_AGENT_RUN_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUN_TIMEOUT_SECONDS,
        ),
        eval_hard_timeout_seconds=_resolve_cli_or_env_positive_float(
            args.hard_timeout_seconds,
            "EVAL_DEBUG_HARD_TIMEOUT_SECONDS",
            DEFAULT_EVAL_HARD_TIMEOUT_SECONDS,
        ),
    )

    if args.once:
        await _run_eval_once(state, endpoint, model)
        return 0

    _print_state(state, endpoint, model)
    await _run_repl(state, endpoint, model)
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
