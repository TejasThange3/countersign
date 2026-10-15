# ArmorIQ policy `countersign` (live, 2026-10-15)

This is the policy the bridge runs under, written down row by row, together with what the live
probes showed about how the ArmorIQ console stores and enforces it. It is set by hand in the
ArmorIQ console (Policy Studio). Nothing in the repo writes it.

## Registration

| Item | Value |
|---|---|
| MCP server | `hotel-mcp-2` (mcpId `eb4be8af-15bd-4c52-8427-133e0d1dbae0`), 17 tools, bearer auth |
| Why `-2` | The toy `hotel-mcp` from the Day 1 spike (4 tools) can't be deleted: the console delete fails. The bridge sets `ARMORIQ_MCP_NAME=hotel-mcp-2` |
| Agent | `countersign` (agentId `ee4ccec3-5bf0-467b-bc0a-a68b7b77ad95`), type Assistant, auth None, no policy at creation, scan off |
| Policy | `countersign` (policyId `facadfec-714a-4f72-bab6-65f71d4ca6b4`), target `mcp_server` = hotel-mcp-2, priority 50, default action **Block** |
| Identities | Org members (Viewer role): the `+unverified` alias (ARMORIQ_USER_UNVERIFIED) and the `+guest` alias (ARMORIQ_USER_GUEST). The org owner is the approver (ARMORIQ_ADMIN_EMAIL) |

The URL of hotel-mcp-2 is a cloudflared quick tunnel. A restarted tunnel gets a new URL, so
the registration has to be updated after every restart. Enforcement itself never calls the
MCP URL; only registration and scans do.

## The rows

Every row is set explicitly in both overrides. "Default" is never used (see finding 2).

| Tool | Tier | Base rows | `+unverified` override | `+guest` override |
|---|---|---|---|---|
| verify_guest | read | Allow | Allow | Allow |
| get_booking | read | Allow | Allow | Allow |
| check_availability | read | Allow | Allow | Allow |
| get_hotel_info | read | Allow | Allow | Allow |
| get_cancellation_policy | read | Allow | Allow | Allow |
| create_booking | write | Block | Block | Allow |
| modify_booking_dates | write | Block | Block | Allow |
| add_booking_note | write | Block | Block | Allow |
| request_housekeeping | write | Block | Block | Allow |
| cancel_own_booking | write | Block | Block | Allow |
| issue_refund | money | Block | Block | **Hold** |
| apply_comp_credit | money | Block | Block | **Hold** |
| waive_fee | money | Block | Block | **Hold** |
| export_guest_list | sensitive | Block | Block | Block |
| cancel_any_booking | sensitive | Block | Block | Block |
| delete_guest_profile | sensitive | Block | Block | Block |
| grant_staff_access | sensitive | Block | Block | Block |
| anything else | | Block (policy default) | Block | Block |

**Money: every amount holds.** The plan was to allow up to $100 and hold above it. The console
can't do that (finding 1), so the user chose to hold every money call: each refund, credit or
fee waiver needs an approver. The bridge has no amount logic of its own, because ArmorIQ must
make the decision (product rule 1). The evals lane's money threshold constant follows this
choice (main owns that change).

**Saved state as last read (2026-10-15, about 11:10 UTC).** `resolve-user` showed all 17
`+unverified` rows exactly as in the table. It showed 16 `+guest` rows that match the table
except two: `cancel_own_booking` was **block** (should be allow), and `cancel_any_booking`
had no row, so it fell to the default block. The user is correcting both. Neither tool is used
by the live proof.

## Findings from the live probes

All probes are masked and decision-only (start_plan + check, with no tool run and nothing
reported), except the live proof at the end.

1. **Parameter limits are stored but not enforced.** The console's per-row gear, "Parameter
   limits" (marked "Prototype stores these verbatim"), exists only on the base rows. With
   `issue_refund` = Allow and the limit `amount <= 100`, the owner identity (no override, so
   the base rows apply) got **ALLOW** for $40, $100 and $250 (`enforcement_passed`, no
   delegation). `resolve-user` doesn't show the limit at all. The documented ArmorPay
   `amountThreshold` fields (see `armoriq-day1-unknowns.md` Q4) aren't offered in the console.
2. **A per-member override replaces the base rows; it doesn't add to them.** With a `+guest`
   override that listed only the 5 writes, guest `get_booking` and guest `issue_refund` were
   **BLOCK** (`tool_not_in_allowlist`). "Default" in an override means the policy default
   (Block), not "inherit the base row". So each override must list every tool.
3. **Matching by policy, not by the bootstrap `toolMap`.** Bootstrap's flat `toolMap` maps
   `issue_refund`, `get_hotel_info` and `export_guest_list` to the toy `hotel-mcp`, because
   both servers have tools with those names. The bridge pins every plan step to
   `ARMORIQ_MCP_NAME` (`armoriq_setup.make_tool_name_parser`). Every check, including
   `issue_refund`, came back with `matched_policy: "countersign"` (the hotel-mcp-2 policy).
4. **Reasons ArmorIQ returns:** `enforcement_passed` (allow), `rule_action_hold` (hold),
   `tool_denied` (an explicit Block row), `tool_not_in_allowlist` (no row in the identity's
   override). The bridge passes these through unchanged in `ToolResult.reason`.
5. **Reading the policy back with the API key.** `POST /iap/sdk/resolve-user` with
   `X-API-Key` and `X-User-Email: <member>` and an empty body returns the member's applied
   policies (`allowedTools`, `deniedTools`, `toolEnforcement`, `defaultEnforcementAction`).
   This is the read-only way to check a console save. Without the header it returns 400
   "X-User-Email header (preferred) or userEmail body field is required".
   `GET /policies/profiles/active` is the separate plugin profile (tools.armoriq.ai) and is
   empty here.

## Live proof (2026-10-15)

Run with `uv run --project apps/agent pytest -m live apps/agent/tests/bridge/test_live_bridge.py -s`,
against the real hotel-mcp through the bridge. It passed in 54 s. Evidence:
`apps/agent/tests/bridge/evidence/20261015T110948Z-live-bridge.json` (masked, `armoriq_mode:
live`, SDK 0.6.10).

| Case | Decision | ArmorIQ reason | Result |
|---|---|---|---|
| Unverified caller, `issue_refund` $40 | BLOCK | `tool_denied` | not run (ArmorIQ blocked, not the bridge) |
| `verify_guest` LRK-1001 | ALLOW | `enforcement_passed` | ran; call switches to the `+guest` identity |
| Guest `issue_refund` $40 | HOLD | `rule_action_hold` | approved over the API by the owner, then ran: payment row 19 written and read back |
| Guest `issue_refund` $250 | HOLD | `rule_action_hold` | rejected over the API by the owner: not run, no new payment row |
| Guest `export_guest_list` | BLOCK | `tool_denied` | not run |

Plan ids: `49c05c4b…` for the unverified phase, and `d7c99bb4…` for the guest phase after
the identity switch. The full ids are in the evidence file.
