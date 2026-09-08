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


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
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

    json.dump({"actions": actions, "tools": tools}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
