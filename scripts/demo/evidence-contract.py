#!/usr/bin/env python3
"""Emit the evidence contract as JSON, derived from the two config files that define it.

The contract lives across a seam that has no test on either side, and that is exactly how the two
files ended up mutually unsatisfiable (see tests/verification/README.md, "Gate B"):

  config/authority-policy.yaml   evidence:  <toolId>: requiredFields: [...]
  config/copilot-tools.yaml      tools:     <toolId>: target.path / target.method

Nothing here restates either file. Everything is read out of them, so when one moves the probe
moves with it. Output shape:

  {
    "actions": {"<actionId>": {"baseRung": "L1", "evidence": ["get_account", ...]}, ...},
    "tools":   {"<toolId>":   {"method": "GET", "path": "/api/...", "requiredFields": [...]}, ...}
  }

A tool named by the policy but absent from the manifest is reported with a null path rather than
skipped — a missing tool is a finding, not a blank.

**`--samples` mode** extends the same idea to the recorded evidence samples in
`tests/fixtures/evidence-samples/`. It reports, per contract tool, whether a sample exists and
whether a projection is declared, and it *regenerates* each sample's `projected` block by running
the REAL manifest loader and the REAL projection engine from `banker-copilot-service`. Nothing is
restated: the projection is read out of `copilot-tools.yaml` and applied by the shipped code, so a
`projected` block cannot be hand-edited into agreement with a policy it does not actually satisfy.

    scripts/demo/evidence-contract.py .            # the contract
    scripts/demo/evidence-contract.py . --samples  # the sample manifest
    scripts/demo/evidence-contract.py . --samples --write   # regenerate `projected`

The C# seam test (`authority-service.UnitTests/EvidenceContractSeamTests`) consumes those samples
and runs the REAL `PolicyEvaluator` over them. Two tests, each running one real component, joined
by one checked-in artifact — and neither re-implements the other.
"""
import json
import os
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, not a logic problem
    sys.stderr.write("PyYAML is required to read the evidence contract.\n")
    sys.exit(2)


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _samples_dir(root):
    return os.path.join(root, "tests", "fixtures", "evidence-samples")


def _load_engine(root):
    """Import the SHIPPED manifest loader and projection engine.

    Imported rather than reimplemented: a second copy of the grammar in this script would be the
    exact drift this whole seam exists to prevent.
    """
    service = os.path.join(root, "src", "banker-copilot-service")
    if service not in sys.path:
        sys.path.insert(0, service)

    from app.tools.manifest import load_manifest  # noqa: E402
    from app.tools.projection import project  # noqa: E402

    manifest = load_manifest(os.path.join(root, "config", "copilot-tools.yaml"))
    return {tool.tool_id: tool for tool in manifest.tools}, project


def samples(root, contract_tools, write):
    tools, project = _load_engine(root)
    directory = _samples_dir(root)
    report = {}

    for tool_id in sorted(contract_tools):
        tool = tools.get(tool_id)
        path = os.path.join(directory, f"{tool_id}.json")
        entry = {
            "sampleFile": os.path.relpath(path, root) if os.path.exists(path) else None,
            "declaredProjection": [
                {"key": rule.key, "verb": rule.verb, "operand": rule.operand}
                for rule in (tool.evidence_projection if tool else ())
            ],
            "requiredFields": contract_tools[tool_id]["requiredFields"],
        }

        if entry["sampleFile"] is None:
            # A missing sample is a finding, not a blank — same rule as a missing tool.
            entry["status"] = "no-sample"
            report[tool_id] = entry
            continue

        with open(path, "r", encoding="utf-8") as handle:
            sample = json.load(handle)

        if tool is None:
            entry["status"] = "no-tool-in-manifest"
            report[tool_id] = entry
            continue

        projected = project(
            sample["response"], tool.evidence_projection, sample.get("arguments") or {}
        )
        entry["status"] = "ok"
        entry["projectedKeys"] = sorted(projected.keys()) if isinstance(projected, dict) else None
        entry["stale"] = sample.get("projected") != projected

        if write and entry["stale"]:
            sample["projected"] = projected
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle, indent=2)
                handle.write("\n")
            entry["rewritten"] = True

        report[tool_id] = entry

    return report


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    root = args[0] if args else os.getcwd()
    policy = load(os.path.join(root, "config", "authority-policy.yaml"))
    manifest = load(os.path.join(root, "config", "copilot-tools.yaml"))

    evidence = policy.get("evidence") or {}
    targets = {}
    for tool in manifest.get("tools") or []:
        target = tool.get("target") or {}
        targets[tool["toolId"]] = {
            "method": target.get("method", "GET"),
            "path": target.get("path"),
        }

    tools = {}
    for tool_id, spec in evidence.items():
        entry = dict(targets.get(tool_id, {"method": "GET", "path": None}))
        entry["requiredFields"] = list((spec or {}).get("requiredFields") or [])
        tools[tool_id] = entry

    actions = {}
    for action_id, spec in (policy.get("actionTypes") or {}).items():
        spec = spec or {}
        actions[action_id] = {
            "baseRung": spec.get("baseRung"),
            "agentMayPropose": bool(spec.get("agentMayPropose")),
            "evidence": list(spec.get("requiredEvidence") or []),
        }

    if "--samples" in flags:
        json.dump(
            samples(root, tools, write="--write" in flags),
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
        return

    json.dump({"actions": actions, "tools": tools}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
