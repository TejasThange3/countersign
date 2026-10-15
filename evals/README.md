# countersign-evals

Evaluation harness (scope section 5): scenarios, automated approver, metrics, text-mode runner.
Audio simulation (caller voices, noise, barge-in) is Day 3 and lives in `simulator/`.

- `scenarios/legit/L01..L10`, `scenarios/adversarial/A1..A7`: YAML, schema in
  `src/countersign_evals/scenario.py`. Dates are written `today+N` (the seed is anchored on
  today). Money steps use `expect: threshold`, derived from the one constant `MONEY_HOLD_ABOVE`.
- `src/countersign_evals/approver/`: delegation API approve/reject, role and limit from
  `/delegation/my-role`, paced under the rate limit. Local `.env` only; refuses to run in CI.
- `src/countersign_evals/metrics/`: DB diff, decision accuracy, who-stopped-it attribution,
  attack success, false positives, pass^k, ArmorIQ overhead vs approval wait, WER/latency stubs.
- `src/countersign_evals/runner/`: reset, drive, probe, score, report.
- `reports/`: `<timestamp>-<mode>.json` + `.md`. A `-FAKE` suffix means a test fake: never a result.

## Run

```
docker compose -f infra/docker-compose.yml up -d
uv run --project evals countersign-evals list
uv run --project evals countersign-evals run                     # ArmorIQ live, automated approver
uv run --project evals countersign-evals run --baseline          # DISABLE_ARMORIQ=1
uv run --project evals countersign-evals run --scenario L05 A3 --repeat 3
uv run --project evals countersign-evals run --supervised        # approve holds in the console
```

The scripted driver (default) replays each scenario's tool calls through the `GatewayFactory`
named by `GATEWAY_FACTORY` (default `countersign_agent.bridge:factory`). It tests policy
decisions only. Headline numbers come from `--driver conversation` once the voice lane's text
endpoint is merged.
