from __future__ import annotations

import json

from app.planner.intent_model import INTENT_CONTRACT_INVALID, parse_intent_decision


def test_schema_valid_propose_intent_parses():
    decision = parse_intent_decision(
        json.dumps(
            {
                "kind": "propose",
                "actionId": "account.balance.adjust",
                "payloadDraft": {"accountId": "acc_1", "amount": "35.00"},
            }
        )
    )

    assert decision.kind == "propose"
    assert decision.action_id == "account.balance.adjust"


def test_schema_invalid_intent_is_mechanical_contract_failure():
    decision = parse_intent_decision(
        json.dumps(
            {
                "kind": "propose",
                "actionId": "account.balance.adjust",
                "payloadDraft": {},
                "extra": "not allowed",
            }
        )
    )

    assert decision.kind == "failure"
    assert decision.reason_code == INTENT_CONTRACT_INVALID
    assert "schema validation" in decision.message


def test_well_formed_unknown_action_is_not_a_schema_failure():
    decision = parse_intent_decision(
        json.dumps(
            {
                "kind": "propose",
                "actionId": "not.in.policy",
                "payloadDraft": {"id": "x"},
            }
        )
    )

    assert decision.kind == "propose"
    assert decision.reason_code == ""
