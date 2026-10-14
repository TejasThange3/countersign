# Countersign

**A voice agent that can't be talked into anything.** It's a real-time voice front desk for a
boutique hotel that takes real actions (bookings, refunds, credits). ArmorIQ checks every action
before it runs, and an automated caller attacks and tests the agent by voice.

> Status: Day 1 skeleton. Sections below are filled in as the build progresses
> (see [countersign-hackathon-scope.md](countersign-hackathon-scope.md) for the full plan).

## Problem and pitch
_TODO_

## Architecture
_TODO: diagram and how the agent works (see docs/architecture.md)._

## How ArmorIQ is used
_TODO: bridge lifecycle, identity mapping, policy table, approval flow._

## Results
_TODO: with vs without ArmorIQ, latency per stage, decision accuracy, and how to reproduce._

## Proof of ArmorIQ
_TODO: screenshots from docs/proof/._

## Setup
```bash
cp .env.example .env        # fill in keys
docker compose -f infra/docker-compose.yml up -d
python scripts/check.py     # lint + unit tests for every project
```
_TODO: accounts, ArmorIQ console steps, full `docker compose up`._

## Sandbox note
All guests, bookings and payments are synthetic seed data. Refunds and credits are database
rows; no payment provider is called. No real customer data is used.

## Disclosure
_TODO: AI coding assistants used (Claude Code, Codex), main third-party libraries, and the
statement on pre-existing code._

## What broke and how we fixed it
_TODO_

## Links
_TODO: demo video, public results view._
