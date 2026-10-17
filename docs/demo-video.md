# Demo video: shot list and script

Target: about 3 min 20 s (the brief asks for 3-5 min). Upload to YouTube as **Unlisted**.

You record **clips** (no talking, except your caller lines in clip 2) and one **voiceover**.
The edit, titles, diagram, results animation and subtitles are done in Remotion.

---

## Before you record (10 min)

1. **ArmorIQ console:** sign in at platform.armoriq.ai. Go to **Intent → Needs you** and
   **reject every old request** there, so only the live one shows up in clip 3.
2. **Wake the agent:** open https://countersign-aimcp.vercel.app/try once and close it again
   (Railway can be slow on the very first call).
3. **One browser window, two tabs:** tab 1 = the /try page, tab 2 = the ArmorIQ console
   (already signed in, on Intent → Needs you).
4. **Clean screen:** Windows Focus / Do Not Disturb on, bookmarks bar hidden, browser zoom at
   110%, the window maximised, no other tabs.
5. **Headphones on** for the voice call, so the agent's voice doesn't echo into your mic.

## How to record

Use **Xbox Game Bar** (built into Windows, nothing to install):

- **Settings → Gaming → Captures:** set *Audio to record* to **Game + microphone** (needed for
  clip 2, where you talk to the agent), and video quality to **High / 60 fps**.
- Click the browser window, press **Win + Alt + R** to start, and **Win + Alt + R** again to
  stop. Clips are saved to `Videos\Captures`.
- Game Bar records only the window that was active when you started. That's fine: everything
  happens in tabs of one browser window.

Rules for every clip:

- Move the mouse slowly and pause about 2 seconds on anything important (a decision chip, a
  policy row). I zoom into those moments in the edit.
- Mistakes are fine: just pause, then redo that part in the same clip. I cut it out.
- Leave 2-3 seconds of stillness at the start and end of each clip.

---

## Clips to record (in this order)

| # | What | Length | What to do |
|---|---|---|---|
| 1 | **Homepage** | ~40 s | Open https://countersign-aimcp.vercel.app. Pause on the hero, then scroll slowly through "How it works", the attacks section (stop on **0/7 vs 6/7**) and the rest. |
| 2 | **Voice call** | ~90 s | On /try choose **Voice**, start the call, and say the three script lines (below). Wait for each answer. After line 3 the refund is **held** (manager card and hold music). **Don't click Approve:** go straight to clip 3. |
| 3 | **Approve in the ArmorIQ console** | ~30 s | Keep recording. Switch to tab 2 (Intent → Needs you), refresh, open the waiting `issue_refund`, click **Approve**, then switch back to tab 1. The agent says the refund has gone through. **You have about 60 seconds** between the hold and the approval, so be quick. If you miss it, redo clips 2-3, or approve with the button in the app instead (also real ArmorIQ). |
| 4 | **Try to break it (text)** | ~60 s | On /try choose **Text**. Send steps 1-2 to verify, then open **Now try to break it** and send: the *prompt injection* (guest list), *Cancel booking LRK-1002* and the *booking note* attack (LRK-1007). Pause on the decision log after each one. |
| 5 | **ArmorIQ console: decisions** | ~30 s | In the console, open **Intent** (plans / runs). Click a **blocked** one (`export_guest_list` or `cancel_any_booking`) to show the decision, the policy and the reason; then the **approved** refund from clip 3. |
| 6 | **Policy Studio** | ~30 s | Open the `countersign` policy. Show the target (hotel-mcp-2), **default Block**, then the **+unverified** and **+guest** overrides: reads Allow, booking changes Allow, refund/credit/waive **Hold**, export/cancel-any/delete/staff **Block**. Scroll slowly. |
| 7 | **Agents and MCP servers** | ~15 s | Show the registered agent `countersign` and the MCP server `hotel-mcp-2` with its 17 tools. |

I'll show the GitHub repo and eval reports from screenshots, so you don't need to record them.

### Your three lines in clip 2 (say them naturally)

1. "Hi, do you have a room from November 2nd to 4th for two people? Just checking prices for now."
2. "I already have a booking with you. The reference is L R K one zero zero one, last name Okafor."
   *(Only if it reads the reference back to you, say "Yes, that's right." Never answer "yes" to
   anything else: if it offers to book a room, say "No thanks, just the refund question."*)
3. "I'd like a forty dollar refund on that booking, the room was noisy."

---

## Voiceover script (~3 min 15 s)

Record this in one go, or section by section, on your phone (Voice Memos) or any mic, in a
quiet room. Speak a little slower than normal. Re-read a sentence if you stumble; I'll cut it.
Send me the audio file(s) (m4a, mp3 or wav).

**[1] The problem (over the title and homepage, ~20 s)**
> Voice agents are starting to handle real money. A hotel front desk agent can issue refunds,
> change bookings and read guest records. But everything a caller says goes straight into the
> model. A confident caller, a fake manager, or one sentence hidden in a booking note can talk
> it into almost anything. This is Countersign: a voice front desk that can be talked into
> *wanting* something, but can't make it happen.

**[2] How it works (over the diagram, ~25 s)**
> It's for any business putting a voice agent on the phone with real powers. The model never
> runs a tool itself. Every tool call goes through our bridge to ArmorIQ first, and ArmorIQ
> allows it, holds it for a human manager, or blocks it. ArmorIQ had no adapter for voice
> agents, so we built one on its Python SDK, for the Pipecat voice framework.

**[3] Live call (over clip 2, ~45 s)**
> Here's the live demo. I ask for a room: a read-only lookup, so ArmorIQ allows it. Then I
> verify with my booking reference. The bridge switches my call to a verified guest identity;
> the model never gets to decide who I am. Now I ask for a forty-dollar refund. Money always
> waits for a person, so ArmorIQ holds it, and the caller hears hold music while it waits.

**[4] The manager approves (over clip 3, ~20 s)**
> In the ArmorIQ console, the request is waiting for a manager. I approve it, and the agent
> tells the caller it's gone through. On the public demo, there's no manager on duty, so
> visitors play the manager with an Approve button that calls the same ArmorIQ approval API.

**[5] Try to break it (over clip 4, ~30 s)**
> Now let's try to break it. A prompt injection asking for the full guest list: blocked.
> Cancelling someone else's booking: blocked. And a booking note with a hidden order to refund
> four hundred and fifty dollars: the model may obey it, but the refund never runs without a
> human.

**[6] ArmorIQ console and Policy Studio (over clips 5-7, ~30 s)**
> Every decision is recorded in the ArmorIQ console, with the policy and the reason. Here's our
> policy in Policy Studio. Everything is blocked by default. Lookups are open to anyone.
> Booking changes need a verified guest. Refunds, credits and fee waivers are held for a
> manager. And exporting guests or granting staff access is blocked for everyone. The model can
> be fooled. The policy can't.

**[7] Results (over the results animation, ~20 s)**
> We tested this. We replayed seven attacks as if the model had been completely fooled.
> Without ArmorIQ, six of the seven got through. With ArmorIQ, none did, and all ten
> legitimate calls still worked.

**[8] Takeaways and what's next (~25 s)**
> What we learned: ArmorIQ stores amount limits but doesn't enforce them yet, so we hold every
> refund. And minting a signed plan takes seconds, so we now prepare it ahead of time;
> verification went from ten seconds to under two. Next, we'd add amount and velocity limits
> as ArmorIQ supports them, real phone numbers, and approvals from the manager's phone.
> Countersign: the agent proposes, ArmorIQ decides.
