# calienne UI — Adaptive Multi-Model Reasoning Orchestrator

A multi-agent reasoning interface for a FastAPI backend exposing `POST /api/query`.
React 18 + Vite + Tailwind + Framer Motion + Zustand. No backend code is included —
this is the frontend only, built against the schema you provided.

## Setup

```bash
npm install
cp .env.example .env        # set VITE_API_BASE_URL if your FastAPI server isn't on :8000
npm run dev                 # http://localhost:5173
```

Your FastAPI server must enable CORS for this origin, e.g.:

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])
```

Without this, every request will fail with an opaque network error and the UI's error
state will fire — that's a backend config issue, not a frontend bug, but it's the most
likely first failure you'll hit, so fix it before filing anything.

Verified: `npm install` and `npm run build` both run clean against this exact code (not
just "should work" — I ran them). One dev-only advisory: esbuild's dev server has a
known CORS-related disclosure issue (GHSA-67mh-4wv8-2f99) that only affects `npm run dev`,
not your production build. Fixing it means jumping to Vite 8, a breaking change I didn't
make unilaterally on your behalf — your call.

## What you asked for vs. what your spec actually supports

You asked for several things the given backend contract cannot honestly deliver. I built
the UI to look and behave as specified, but I'm not going to pretend the gaps don't exist
— that's how teams ship demos that fall apart against a real backend.

1. **"Real-time" pipeline status is not real.** `POST /api/query` is one synchronous
   request that returns a final JSON blob. There is no stage-by-stage event stream in
   your spec — no SSE, no WebSocket. So `[Breaker] → [Agents] → [Judge] → [Done]` is
   driven by a **client-side timer heuristic** (`usePipelineStages.js`) that estimates how
   long each stage probably takes and advances the UI accordingly, then snaps to "Done"
   the instant the real response lands (or holds on "Judge", pulsing, if the backend is
   slower than the heuristic). This looks convincing. It is not telemetry. If you want
   actual real-time staging, the backend needs to emit real events — for example, an SSE
   endpoint emitting `{ "stage": "breaker" | "agents" | "judge" | "done", "ts": ... }` as
   each phase completes. Wire that in and `usePipelineStages` is the only file that needs
   to change.

2. **Provider health dots are mocked.** Your spec has no `/api/health` (or equivalent)
   endpoint, so "Groq / OpenRouter status" has no real signal to read. `App.jsx` randomizes
   plausible-looking statuses every 9s, explicitly commented as a mock. Either accept this
   is decorative until a real health endpoint exists, or add one — `ProviderStatusBar`
   already expects `{ name, status }[]` and needs nothing else changed.

3. **Telemetry is partially fabricated by omission, not by lying.** `latencyMs` is real —
   measured client-side via `performance.now()` around the actual fetch. `confidence_score`
   and `bias_risk` are real, pulled straight from your response schema. **`provider` and
   `cost` are `null`** because your schema doesn't return them. I did not invent placeholder
   values for these — the drawer renders `—` rather than a fake number, because a fake
   number that looks like real telemetry is worse than an honest blank. If you want cost
   tracking, the backend has to return it; no frontend trick recovers data the server never
   sent.

4. **Chat history persistence is client-only.** Your spec has no endpoint for saving or
   listing past conversations, so the sidebar persists to `localStorage`
   (`store/useChatStore.js`). This means history is per-browser, not per-account, and is
   gone if the user clears site data or switches devices. If you need durable, cross-device
   history, you need a backend resource for it (e.g. `GET/POST /api/conversations`) — this
   is not something the frontend can fix on its own.

5. **No auth, no rate limiting, on a publicly-reachable POST endpoint.** Not a frontend
   concern to fix, but worth saying plainly: as specified, `/api/query` has no stated auth
   layer. Anyone who finds the URL can drive arbitrary cost against whatever LLM providers
   sit behind it. That's a backend decision, but design the frontend's error states (already
   built) to surface 401/403/429 cleanly once you add it — `useSendQuery.js`'s
   `deriveErrorMessage` is the place to extend.

## Architecture decisions (and the reasoning behind them, since you'll want to defend or
challenge them)

- **API logic is isolated in `api/client.js`.** One function, one job: post a query, time
  it, return the result. Nothing else touches `axios` directly. If you swap REST for
  gRPC-web or add auth headers, this is the only file that changes.

- **Pipeline staging is a hook, not a component.** `usePipelineStages` knows nothing about
  rendering. `PipelineStatus.jsx` knows nothing about timers or network state. This is the
  difference between "a component that happens to manage state" and a properly separated
  concern — testable independently, replaceable independently.

- **Race condition handling is not optional polish.** If a user submits a second query
  before the first response lands, a naive implementation lets whichever request resolves
  last silently overwrite the UI — including a stale answer overwriting a newer one if the
  first request happens to be slow. `usePipelineStages.run` aborts the previous
  `AbortController` on every new call specifically to kill this class of bug. I disabled the
  input while a request is pending as the simpler UX choice, but the abort logic stays in
  as defensive correctness (unmounts, fast double-submits, etc.) — removing it to "simplify"
  would be removing a correctness guarantee, not dead code.

- **No `dangerouslySetInnerHTML` anywhere.** `message.response.answer` is rendered as plain
  text (`whitespace-pre-wrap`), not parsed as HTML or Markdown. Your schema returns a plain
  string with no stated format. If you later want Markdown rendering, that's a deliberate
  addition requiring `react-markdown` + `DOMPurify` (or equivalent sanitization) — rendering
  arbitrary backend-sourced strings as raw HTML in a chat UI is the single most common XSS
  vector in this category of app, and I'm not introducing it by default just because
  Markdown looks nicer.

- **Zustand over Context.** You listed both as options. Context re-renders every consumer on
  every state change unless you split providers manually; Zustand gives selector-based
  subscriptions for free, which matters here because `telemetry` updates shouldn't
  re-render `Sidebar`. For an app this size either would "work" — Zustand is just less
  code to get the same isolation.

## File map

```
src/
  api/client.js              single fetch wrapper, latency timing
  store/useChatStore.js      conversations, telemetry, provider health (Zustand)
  hooks/usePipelineStages.js heuristic stage timing + AbortController-based cancellation
  hooks/useSendQuery.js      glues store + pipeline hook into one send() call
  components/
    Sidebar.jsx              chat history (localStorage-backed)
    ProviderStatusBar.jsx    top bar, mocked health dots, telemetry toggle
    ChatWindow.jsx           message list + autoscroll + empty state
    MessageBubble.jsx        user/assistant rendering, all status branches
    PipelineStatus.jsx       animated [Breaker]→[Agents]→[Judge]→[Done]
    ReasoningPanel.jsx       Logician / Creative / Judge expandable detail
    ConfidenceBadge.jsx      color-coded by score
    BiasRiskBadge.jsx        low/medium/high styling
    TelemetryDrawer.jsx      slide-in panel, real + honestly-blank metrics
    EmptyState.jsx           suggested prompts
    InputBox.jsx             auto-growing textarea, Enter to send
    TriadMark.jsx            the one signature visual element — two agent
                              nodes converging on a judge node, reused in the
                              sidebar mark and empty state rather than a
                              generic logo, because that convergence is
                              literally what the product does
```

## What I'd push back on if this were a real handoff

Your spec calls this "real-time" in three separate places while defining a backend that
cannot be real-time without changes. That's not a frontend problem I can paper over with
better animation — I built the best honest approximation of it, said so directly in the
code comments, and I'd rather you know that now than discover it when a stakeholder asks
"wait, is this actually streaming?" during a demo.
