from armoriq_spike.redact import REDACTED, mask_identities, redact

MASK = {"a+guest@x.com": "<guest>", "a@x.com": "<admin>"}


def test_masks_emails_in_values_keys_and_sentences() -> None:
    data = {
        "user": "A+Guest@x.com",
        "a@x.com": ["approved by a@x.com", 3],
    }
    assert mask_identities(data, MASK) == {
        "user": "<guest>",
        "<admin>": ["approved by <admin>", 3],
    }


def test_longer_alias_is_not_half_replaced() -> None:
    # "bob@x.com" is a substring of "jbob@x.com"; the longer address must win.
    mask = {"bob@x.com": "<admin>", "jbob@x.com": "<guest>"}
    assert mask_identities("jbob@x.com and bob@x.com", mask) == "<guest> and <admin>"


def test_empty_mask_is_a_no_op() -> None:
    assert mask_identities({"u": "a@x.com"}, {}) == {"u": "a@x.com"}


def test_redacts_credential_keys_at_any_depth() -> None:
    data = {
        "apiKey": "ak_live_x",
        "org": {"name": "acme", "jwt_token": "eyJ"},
        "items": [{"Authorization": "Bearer x", "tool": "issue_refund"}],
    }
    assert redact(data) == {
        "apiKey": REDACTED,
        "org": {"name": "acme", "jwt_token": REDACTED},
        "items": [{"Authorization": REDACTED, "tool": "issue_refund"}],
    }


def test_leaves_plain_values_alone() -> None:
    assert redact({"plan_id": "p1", "count": 2}) == {"plan_id": "p1", "count": 2}
    assert redact("text") == "text"
