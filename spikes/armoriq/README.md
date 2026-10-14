# armoriq-spike

Day 1 ArmorIQ smoke test (lane `armoriq-smoke`, see `tasks/armoriq-smoke.md`).
The call sequence it proves, and every finding, is in `docs/research/armoriq-call-sequence.md`.

```
uv run --project spikes/armoriq pytest -q                                   # unit tests, fakes only
uv run --project spikes/armoriq python -m armoriq_spike.toy_server          # toy hotel-mcp on :8765
uv run --project spikes/armoriq python spikes/armoriq/smoke.py preflight    # key, bootstrap, identities
uv run --project spikes/armoriq python spikes/armoriq/smoke.py run          # ALLOW, HOLD (approve in console), BLOCK
uv run --project spikes/armoriq python spikes/armoriq/smoke.py probe <tool> [--as EMAIL] [--label L]
uv run --project spikes/armoriq python spikes/armoriq/smoke.py approve-test # hold, then approve over HTTP
uv run --project spikes/armoriq python spikes/armoriq/smoke.py reject <delegation_id>
```

`smoke.py` calls the live ArmorIQ service with `ARMORIQ_API_KEY` from the repo-root `.env`;
it is never run by `scripts/check.py`. Each run saves a redacted, identity-masked record to
`evidence/` with `armoriq_mode: live`.
