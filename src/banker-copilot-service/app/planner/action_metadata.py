"""Model-facing descriptions of the actions authority already permits.

Read tools reach the intent model with prose and a full JSON Schema. Actions reached it as
names only — an id, a display name, a rung, three lists of field NAMES — so the model had
to bridge "Refund a $35 overdraft fee" to the four words "Post a balance adjustment"
unaided, and had to guess that `direction` takes `credit` or `debit`.

When it could not bridge that, it did not say it was unsure. It reported its guess as a
fact about the bank: "no proposable action supports posting or refunding a fee directly in
this harness." Measured at 4 failures in 12 live runs of one prompt, catalogue present
every time.

**This module describes; it never permits.** Nothing here can add an action, make one
proposable, change a rung, or alter what a signature covers. The catalogue fetched from
authority-service remains the sole authority on the action SET, and the lookup is by id
into a dict — an id present here that authority does not offer is inert, and an id
authority offers that is absent here reaches the model without prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import structlog
import yaml

logger = structlog.get_logger(__name__)

SUPPORTED_API_VERSION = "copilot-actions/v1"


class ActionMetadataError(RuntimeError):
    """Raised at startup when the file is missing or malformed. Never swallowed.

    A missing file is a hard error rather than a quiet fall back to names-only, because
    names-only is not a degraded mode that someone notices — it is a model telling a banker
    the bank cannot do something it can, about one time in three, with nothing in the logs.
    That failure is invisible from the outside, so it must be impossible at startup.
    """


@dataclass(frozen=True)
class ActionMetadata:
    """Descriptions keyed by action id. Empty is a legitimate value only for tests."""

    descriptions: Mapping[str, Mapping[str, Any]]

    def for_action(self, action_id: str) -> Mapping[str, Any]:
        """Whatever we can say about this id, or nothing. Never raises, never invents."""
        entry = self.descriptions.get(action_id)
        return entry if isinstance(entry, Mapping) else {}

    def missing_from(self, action_ids: set[str]) -> list[str]:
        """Which of these ids we have nothing to say about.

        Called against the LIVE catalogue rather than against a static list, because the
        drift worth catching is exactly the one no static check can see: risk-operations
        adding an action to the policy file, and this file not following.
        """
        return sorted(action_ids - set(self.descriptions))


EMPTY = ActionMetadata(descriptions={})


def load_action_metadata(path: str | Path) -> ActionMetadata:
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ActionMetadataError(
            f"action metadata file not found at {source}. Without it the intent model sees "
            "actions as names only, which it reports to bankers as the bank being unable to "
            "act. Set COPILOT_ACTION_METADATA_PATH or mount the file."
        ) from exc
    except yaml.YAMLError as exc:
        raise ActionMetadataError(f"action metadata at {source} is not valid YAML: {exc}") from exc

    if not isinstance(raw, Mapping):
        raise ActionMetadataError(f"action metadata at {source} is not a mapping")

    api_version = raw.get("apiVersion")
    if api_version != SUPPORTED_API_VERSION:
        raise ActionMetadataError(
            f"action metadata at {source} declares apiVersion {api_version!r}, "
            f"expected {SUPPORTED_API_VERSION!r}"
        )

    actions = raw.get("actions")
    if not isinstance(actions, Mapping) or not actions:
        raise ActionMetadataError(f"action metadata at {source} declares no actions")

    descriptions: dict[str, dict[str, Any]] = {}
    for action_id, entry in actions.items():
        if not isinstance(entry, Mapping):
            raise ActionMetadataError(f"action metadata for {action_id!r} is not a mapping")
        described: dict[str, Any] = {}
        description = entry.get("description")
        if description is not None:
            described["description"] = str(description).strip()
        fields = entry.get("fields")
        if fields is not None:
            if not isinstance(fields, Mapping):
                raise ActionMetadataError(f"action metadata `fields` for {action_id!r} is not a mapping")
            described["fields"] = {
                str(name): _field(spec, action_id=str(action_id), field_name=str(name))
                for name, spec in fields.items()
            }
        descriptions[str(action_id)] = described

    logger.info("Action metadata loaded", path=str(source), actions=len(descriptions))
    return ActionMetadata(descriptions=descriptions)


def _field(spec: Any, *, action_id: str, field_name: str) -> dict[str, Any]:
    if not isinstance(spec, Mapping):
        raise ActionMetadataError(f"action metadata field {action_id}.{field_name} is not a mapping")
    described: dict[str, Any] = {}
    for key in ("type", "description"):
        value = spec.get(key)
        if value is not None:
            described[key] = str(value).strip()
    allowed = spec.get("allowedValues")
    if allowed is not None:
        if not isinstance(allowed, (list, tuple)):
            raise ActionMetadataError(
                f"action metadata field {action_id}.{field_name} has a non-list allowedValues"
            )
        described["allowedValues"] = [str(item) for item in allowed]
    return described


__all__ = [
    "ActionMetadata",
    "ActionMetadataError",
    "EMPTY",
    "SUPPORTED_API_VERSION",
    "load_action_metadata",
]
