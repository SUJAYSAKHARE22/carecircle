# Devpost submission kit

Deadline: confirm the exact cut-off on the Devpost page (listings showed **23 October 2026, 12:00 PM PT**).
Judges may stop watching at 3:00, so lead with the best material.

## Entry

* **Primary track:** Alexa+ (self-hosted MCP server, Streamable HTTP)
* **Mini challenge:** Open Source (MIT-licensed public repo). AWS Builder is *not* claimed: no AWS services are used.
* **Existing project?** CareCircle was created for this hackathon. *(Confirm this is true for you; if not, describe
  what you built or changed during the window.)*

## Project description (paste into Devpost, edit freely)

**CareCircle: a voice-first family check-in server for Alexa+.**

Millions of families have a parent living alone while their children study or work in another city. Calling daily
is hard, smart-home alerts are noisy and impersonal, and apps are a barrier for older users. Voice is the
interface they already accept.

CareCircle is an MCP server (Streamable HTTP) that gives Alexa+ a memory and a conscience for family care. An
elder simply talks: "good morning", "I took my tablet", "tell my son to call me". CareCircle records the check-in,
confirms routines, relays family messages, and notices what matters: a fall, chest pain, dizziness, a missed
check-in, a missed dose. The right caregiver is alerted immediately on Telegram, and receives a plain-language
summary each evening.

**How it works.** Thirteen MCP tools (plus a timeline resource and a conversation prompt) sit on a framework-free
care engine backed by SQLite. A multilingual, negation-aware safety classifier (English, Hindi, Marathi) runs
offline in milliseconds; an optional LLM can only *raise* severity, never lower it. A scheduler escalates in
stages: a gentle nudge, then one alert per missed check-in, with de-duplication so families are never spammed but
a more severe event always gets through. Tools return structured `needs_clarification` results instead of errors,
so the assistant naturally asks "which tablet?".

**Why it can be trusted.** 238 automated tests cover real MCP client sessions, escalation timing, auth, CSRF, host
validation and a strict CSP. It is conservative about claims: a family notification aid, never medical advice, never
audio storage.

**Built with:** Python, MCP SDK (protocol 2026-07-28), Starlette/uvicorn, SQLite, Telegram Bot API, vanilla JS.
Free to run end to end.

## Requirements checklist (from the rules)

- [ ] Text description (above)
- [ ] Public GitHub repo with `LICENSE` (MIT) **or** private repo shared with `testing@devpost.com` and the Amazon
      reviewers. Copy the reviewer list from the official Devpost rules at submission time, and re-send invitations
      if any expired (they lapse after 7 days)
- [ ] Repo actually calls the track technology in code: `src/carecircle/server.py` builds the MCP server;
      `src/carecircle/app.py` serves it over Streamable HTTP
- [ ] Demo video < 3 min, public on YouTube/Vimeo, in English, **showing the MCP server working**; no third-party
      trademarks or copyrighted music
- [ ] Product feedback on **every** Amazon tool/API/SDK you used (see `FRICTION_LOG.md`, section B)
- [ ] Tracks and mini challenge selected: Alexa+ and Open Source
- [ ] Open Source extras: repo URL, your GitHub username, short description of what you did, how it works, why it matters
- [ ] Optional: feature requests (critical / important / nice-to-have) and the friction log (up to +10%)

## 3-minute demo script

| Time | On screen | Say |
|---|---|---|
| 0:00 to 0:20 | Photo-free title card, then the simulator + dashboard side by side | "My mother lives alone. I can't call every day, and she won't use an app. So I built CareCircle." |
| 0:20 to 1:00 | Simulator, Hindi. Click/say "सुप्रभात, मैं ठीक हूँ", then "मैंने दवाई ले ली" | "She just talks. Alexa+ calls CareCircle's MCP tools: you can see each call on the right." Point at `log_checkin` and `confirm_reminder` |
| 1:00 to 1:25 | "tell my son to bring milk" | "Messages go to family, who see them on Telegram." |
| 1:25 to 2:05 | "मैं गिर गई" (I fell) | "Now the important part." Caregiver phone buzzes; dashboard turns red; point at `concern_level: urgent` and the guidance the assistant follows |
| 2:05 to 2:30 | Dashboard demo bar: **+10 h**, run monitor | "If she is silent, it escalates: one nudge, then one alert. No spam, no missed day." |
| 2:30 to 2:50 | Terminal: `python scripts/mcp_client_demo.py` | "Any MCP client works over Streamable HTTP, with bearer auth." |
| 2:50 to 3:00 | Repo page | "Open source, MIT, free to run. CareCircle." |

Rehearse once with `python -m carecircle serve --demo`. Record the screen in a quiet room; Chrome gives the best
speech recognition. If the mic misbehaves, the suggestion chips send the same phrases.

## Product feedback template (one block per Amazon tool you used)

* **Tool / API / SDK:**
* **What I used it for:**
* **What worked well:**
* **What needs work:**
* **Onboarding experience:**
* **Would I build with it again, and why:**

## Feature request template (optional)

* **Request:** · **Why it matters:** · **Urgency:** critical / important / nice-to-have
