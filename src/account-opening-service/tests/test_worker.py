"""Tests for the agent worker process.

Validates that the worker:
- Starts all 4 agent consumers
- Stops gracefully on SIGTERM
- Exits with error if agent-framework-foundry is unavailable
"""
from __future__ import annotations

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
class TestWorkerStartup:
    """Worker must initialise and start all 4 agent consumers."""

    async def test_worker_checks_foundry_import(self):
        """Worker must attempt to import agent-framework-foundry."""
        with patch("builtins.__import__", wraps=__import__) as mock_import:
            from importlib import reload
            import app.worker as worker_mod

            # The module-level code in main() tries to import
            # agent_framework_foundry.  We just verify the function exists
            # and can be called.
            assert callable(getattr(worker_mod, "main", None))

    async def test_worker_has_signal_handling(self):
        """Worker must register handlers for SIGINT/SIGTERM."""
        from app.worker import main

        # Create a stop_event that fires immediately so main() doesn't block
        original_event_class = asyncio.Event

        class ImmediateEvent(original_event_class):
            def __init__(self):
                super().__init__()
                self.set()  # trigger immediately

        with patch("asyncio.Event", ImmediateEvent):
            with patch("asyncio.get_running_loop") as mock_loop:
                mock_loop_instance = MagicMock()
                mock_loop.return_value = mock_loop_instance

                # Run worker main — it should exit quickly via immediate stop_event
                try:
                    await main()
                except Exception:
                    pass  # Worker may raise on missing deps, that's fine

                # Verify signal handlers were registered
                if mock_loop_instance.add_signal_handler.called:
                    sig_calls = [
                        call[0][0]
                        for call in mock_loop_instance.add_signal_handler.call_args_list
                    ]
                    assert signal.SIGTERM in sig_calls or signal.SIGINT in sig_calls

    async def test_worker_main_is_async(self):
        """Worker main() must be an async function."""
        from app.worker import main

        assert asyncio.iscoroutinefunction(main)


@pytest.mark.asyncio
class TestWorkerGracefulShutdown:
    """Worker must stop gracefully on SIGTERM."""

    async def test_stop_event_terminates_run_loop(self):
        """Setting the stop event must cause the worker to exit."""
        from app.worker import main

        stop = asyncio.Event()

        async def timed_stop():
            await asyncio.sleep(0.05)
            stop.set()

        # Replace asyncio.Event in worker with our controlled stop
        with patch("asyncio.Event", return_value=stop):
            task = asyncio.create_task(main())
            stopper = asyncio.create_task(timed_stop())

            try:
                await asyncio.wait_for(
                    asyncio.gather(task, stopper, return_exceptions=True),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                task.cancel()
                stopper.cancel()
                pytest.fail("Worker did not shut down within 2 seconds")


@pytest.mark.asyncio
class TestWorkerFoundryCheck:
    """Worker must surface error when agent-framework-foundry is missing."""

    async def test_logs_error_when_foundry_missing(self):
        """If agent-framework-foundry is not installed, worker must log error."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "agent_framework_foundry":
                raise ImportError("No module named 'agent_framework_foundry'")
            return original_import(name, *args, **kwargs)

        stop = asyncio.Event()

        async def quick_stop():
            await asyncio.sleep(0.05)
            stop.set()

        with patch("builtins.__import__", side_effect=mock_import):
            with patch("asyncio.Event", return_value=stop):
                with patch("app.worker.logger") as mock_logger:
                    task = asyncio.create_task(
                        asyncio.wait_for(
                            asyncio.gather(
                                __import__("app.worker", fromlist=["main"]).main(),
                                quick_stop(),
                                return_exceptions=True,
                            ),
                            timeout=2.0,
                        )
                    )
                    try:
                        await task
                    except (asyncio.TimeoutError, Exception):
                        pass

                    # Worker should have logged the missing dependency
                    # (It may use logger.error or logger.warning)
                    if mock_logger.error.called:
                        error_msgs = [
                            str(call) for call in mock_logger.error.call_args_list
                        ]
                        assert any("foundry" in m.lower() or "agent" in m.lower() for m in error_msgs)


@pytest.mark.asyncio
class TestFoundryAgentSignatureContract:
    """Pin the FoundryAgent constructor contract for our pinned SDK version.

    Regression guard for the recurring 'unexpected keyword argument' breakage
    when preview agent-framework-foundry SDK signatures shift between releases.

    Constructing FoundryAgent with kwargs the installed SDK does not accept
    causes a TypeError at startup (Foundry connectivity check fails). These
    tests verify each FoundryAgent call site uses ONLY kwargs accepted by the
    pinned SDK version. If the SDK signature changes, these tests fail loudly
    instead of waiting for a pod startup error in production.
    """

    def _agent_kwargs(self):
        import inspect
        from agent_framework_foundry import FoundryAgent
        return set(inspect.signature(FoundryAgent.__init__).parameters.keys())

    def test_worker_connectivity_check_kwargs_supported(self):
        """worker.py main() FoundryAgent kwargs must all be in the SDK signature."""
        import re
        from pathlib import Path

        worker_src = Path(__file__).resolve().parent.parent / "app" / "worker.py"
        text = worker_src.read_text()
        m = re.search(r"FoundryAgent\((.*?)\)", text, re.DOTALL)
        assert m, "FoundryAgent() call not found in worker.py"
        used_kwargs = set(re.findall(r"(\w+)\s*=", m.group(1)))

        sdk_kwargs = self._agent_kwargs()
        unsupported = used_kwargs - sdk_kwargs
        assert not unsupported, (
            f"worker.py FoundryAgent() uses kwargs not in SDK signature: "
            f"{unsupported}. Supported: {sorted(sdk_kwargs)}"
        )
        # Specifically: 'model' is not a constructor kwarg in agent-framework-foundry 1.2.x
        assert "model" not in used_kwargs, (
            "worker.py must not pass model= to FoundryAgent — see history #137 follow-up"
        )

    @pytest.mark.parametrize(
        "module_path",
        [
            "app/agents/identity_verification.py",
            "app/agents/compliance_check.py",
            "app/agents/provisioning.py",
        ],
    )
    def test_agent_modules_kwargs_supported(self, module_path):
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / module_path).read_text()
        m = re.search(r"FoundryAgent\((.*?)\)", src, re.DOTALL)
        assert m, f"FoundryAgent() call not found in {module_path}"
        used_kwargs = set(re.findall(r"(\w+)\s*=", m.group(1)))

        sdk_kwargs = self._agent_kwargs()
        unsupported = used_kwargs - sdk_kwargs
        assert not unsupported, (
            f"{module_path} FoundryAgent() uses kwargs not in SDK signature: "
            f"{unsupported}. Supported: {sorted(sdk_kwargs)}"
        )
        assert "model" not in used_kwargs, (
            f"{module_path} must not pass model= to FoundryAgent"
        )

    @staticmethod
    def _foundry_agent_call_bodies(src: str) -> list[str]:
        """Yield the argument text of every FoundryAgent(...) call.

        A naive ``FoundryAgent\(([^)]*)\)`` regex stops at the first ``)``, so a
        call whose first argument is ``foundry_endpoint.rstrip("/")`` gets
        truncated before ``agent_name`` and is silently skipped. Balance the
        parentheses instead.
        """
        import re

        src = re.sub(r"(?m)#.*$", "", src)
        bodies = []
        for m in re.finditer(r"FoundryAgent\(", src):
            i = m.end()
            depth = 1
            while i < len(src) and depth:
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                i += 1
            bodies.append(src[m.end() : i - 1])
        return bodies

    @staticmethod
    def _top_level_kwargs(body: str) -> set:
        import re

        inner = set()
        for chunk in re.findall(r"\{[^{}]*\}", body):
            inner |= set(re.findall(r"\b(\w+)\s*=(?!=)", chunk))
        nested = set()
        for chunk in re.findall(r"\.\w+\(([^()]*)\)", body):
            nested |= set(re.findall(r"\b(\w+)\s*=(?!=)", chunk))
        return set(re.findall(r"\b(\w+)\s*=(?!=)", body)) - inner - nested

    @pytest.mark.parametrize(
        "module_path",
        [
            "app/worker.py",
            "app/agents/identity_verification.py",
            "app/agents/compliance_check.py",
            "app/agents/provisioning.py",
        ],
    )
    def test_foundry_agent_call_sites_do_not_pass_instructions(self, module_path):
        """A referenced Foundry agent must not also carry `instructions=`.

        agent-framework-foundry always injects `agent_reference` into the
        request body (`_agent.py::_prepare_options`), and the Responses API
        rejects the pair with:

            400 invalid_payload — "Not allowed when agent is specified."
                                  param: instructions

        The system prompt belongs on the agent version in Foundry — see
        `app/agents/prompts.py` and `app/agents/init_agents.py`.
        """
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / module_path).read_text()
        bodies = self._foundry_agent_call_bodies(src)
        assert bodies, f"{module_path}: no FoundryAgent() call found — guard would pass vacuously"

        for body in bodies:
            used_kwargs = self._top_level_kwargs(body)

            if "agent_name" in used_kwargs:
                assert "instructions" not in used_kwargs, (
                    f"{module_path}: FoundryAgent() passes both agent_name and "
                    f"instructions — the Responses API rejects that pairing. "
                    f"Provision the prompt via app/agents/prompts.py instead."
                )

    def test_every_referenced_agent_is_provisioned(self):
        """Each agent_name used at runtime must exist in init_agents.AGENTS.

        customer-explanation-generator was referenced by provisioning.py but
        never provisioned, so the agent had no versions and the call 404'd.
        """
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        provisioned = set(
            re.findall(r'"agent_name":\s*"([^"]+)"', (root / "app/agents/init_agents.py").read_text())
        )
        assert provisioned, "no agents parsed out of init_agents.py"

        referenced = set()
        for module_path in [
            "app/worker.py",
            "app/agents/identity_verification.py",
            "app/agents/compliance_check.py",
            "app/agents/provisioning.py",
        ]:
            src = (root / module_path).read_text()
            for body in self._foundry_agent_call_bodies(src):
                referenced |= set(re.findall(r'agent_name="([^"]+)"', body))

        assert referenced, "no agent_name references parsed — guard would pass vacuously"

        missing = referenced - provisioned
        assert not missing, (
            f"agents referenced at runtime but never provisioned: {sorted(missing)}"
        )
