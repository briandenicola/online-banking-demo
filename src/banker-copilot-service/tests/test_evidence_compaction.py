from app.planner.evidence_compaction import compact_evidence


def test_compaction_preserves_every_evidence_id_and_marks_truncation():
    evidence = {
        "account": {"status": "open"},
        "transactions": [{"id": index, "memo": "payment"} for index in range(30)],
    }

    compacted, record = compact_evidence(evidence, budget_tokens=20)

    assert set(compacted) == set(evidence)
    assert record.compacted_ids == ("transactions",)
    assert isinstance(compacted["transactions"], dict)
    assert compacted["transactions"]["truncated"] == {"originalCount": 30, "shown": 0}
    assert compacted["transactions"]["items"] == []
    assert compacted["transactions"] != evidence["transactions"]


def test_compaction_is_structurally_unchanged_under_budget():
    evidence = {"account": {"status": "open"}, "transactions": [{"id": 1}]}

    compacted, record = compact_evidence(evidence, budget_tokens=1000)

    assert compacted == evidence
    assert record.compacted_ids == ()


def test_scalar_evidence_is_never_truncated():
    evidence = {"memo": "x" * 1000}

    compacted, record = compact_evidence(evidence, budget_tokens=1)

    assert compacted == evidence
    assert record.compacted_ids == ()


def test_truncation_marker_is_not_an_evidence_item():
    evidence = {
        "transactions": [
            {"id": index, "truncated": "customer text, not the compaction marker"}
            for index in range(12)
        ]
    }

    compacted, _ = compact_evidence(evidence, budget_tokens=30)

    assert isinstance(compacted["transactions"], dict)
    assert isinstance(compacted["transactions"]["items"], list)
    assert isinstance(compacted["transactions"]["truncated"], dict)
    assert compacted["transactions"]["truncated"]["originalCount"] == 12
