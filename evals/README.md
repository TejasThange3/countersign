# countersign-evals

Evaluation harness (scope section 5). Day 3 work. Skeleton only for now.

- `src/countersign_evals/simulator/`: caller client, personas, noise mixing
- `src/countersign_evals/approver/`: delegation API client for automated approvals
- `src/countersign_evals/metrics/`: DB diff, decision accuracy, latency, WER, pass^k
- `scenarios/legit/`, `scenarios/adversarial/`: YAML scenarios
- `reports/`: generated JSON and Markdown results (committed; audio is not)
