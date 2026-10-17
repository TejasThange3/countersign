# Countersign: submission description

**What it is.** Countersign is a real-time voice front desk for a boutique hotel that takes real
actions (bookings, refunds, credits) on a real database, and can't be talked into the wrong
ones. Every tool call the agent makes goes through ArmorIQ first, which allows it, holds it for
a human manager, or blocks it. Live at https://countersign-aimcp.vercel.app/try: call it by
voice or text, follow the script, then try to break it.

**How the agent works.** A Pipecat pipeline: Silero voice detection, Groq Whisper speech to text
(ElevenLabs Scribe as fallback), gpt-oss-120b on Groq with tool calling, and ElevenLabs Flash
text to speech. The tools live in our own FastMCP server (17 hotel tools over Postgres, all
synthetic data). The model only proposes tool calls; it never runs them and never chooses whose
data they touch.

**How ArmorIQ is used.** There is no ArmorIQ adapter for voice frameworks, so we built a small
ArmorIQ-to-Pipecat bridge on the core Python SDK, following the official Strands adapter's
lifecycle: a session per identity, a signed plan, a check before every call, run, then report.
The bridge owns identity: each call starts as an unverified member and switches to a verified
guest member only after `verify_guest` passes, injecting the guest id itself. Policy Studio
decides everything else: reads are open, booking changes need verification, every refund and
credit is held, and guest exports or other guests' bookings are blocked. Holds go through
ArmorIQ's delegation API; on the demo, the visitor plays the manager and their Approve or Reject
is sent to ArmorIQ and recorded in its audit log. Attacks covered: authority claims, spoken and
indirect prompt injection, cross-guest access, tool swapping, refund splitting and verification
brute force.

**Other tools.** Groq, ElevenLabs, Pipecat, FastAPI, FastMCP, Postgres, Next.js; hosted on
Railway (agent, MCP server, database) and Vercel (website). Built with Claude Code, reviewed
with Codex.

**Links.** Repo: https://github.com/TejasThange3/countersign. Demo video: _link_.
