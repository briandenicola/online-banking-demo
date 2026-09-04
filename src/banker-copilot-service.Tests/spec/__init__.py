"""Spec-derived reference model for the Banker Copilot harness (epic #332, Phase 2).

This package is an EXECUTABLE ORACLE for the specification, not a copy of
``src/banker-copilot-service/``. It exists for the same reason the Phase 1
``Spec/`` directory existed: most of this suite is written before, or in
parallel with, the code it describes, and pseudocode in a test plan cannot be
run.

Read the honest limitation in ``docs/design/banker-copilot-phase2-test-plan.md``
§1.1 before drawing conclusions from a green run here: a passing oracle test
proves the SPECIFICATION is coherent. It says nothing about Turk's service.
Tests that can fail because of somebody else's code live in ``tests/production``
and ``tests/repo`` and run against real repository artefacts.
"""
