# Frontend Context

Working notes for UI work on the BURT++ chat frontend. Scope is `frontend/`, with the
backend contract included because every UI state is driven by it.

## 1. Stack And Layout

- React 18 + TypeScript, built by Vite 5, tested with Vitest + Testing Library (jsdom).
- No router, no state library, no component library, no CSS framework. One global
  stylesheet at `src/app/styles.css` drives the entire look.
- Served in production by nginx (`frontend/nginx/default.conf`) as a static SPA. Browser
  calls go to `/api/...`, which nginx proxies to `api:3000` inside the Compose network.
  `VITE_API_BASE_PATH` (default `/api`) sets the prefix.
- nginx allows a 300s proxy read timeout, so slow agent turns are a UI problem, not a
  gateway problem.

```
src/
  main.tsx                                 React root, imports the global stylesheet
  app/App.tsx                              Shell: HeaderBar / ChatTranscript / Composer
  app/styles.css                           All styling (~410 lines, hand-written)
  app/App.test.tsx                         Integration tests driving the whole shell
  features/chat/
    hooks/useChatSession.ts                All app state, all API orchestration
    components/HeaderBar.tsx               Brand mark + bug selector
    components/ChatTranscript.tsx          Message list + scroll-to-bottom effect
    components/MessageBubble.tsx           Dispatches on message.kind
    components/Composer.tsx                Textarea + Send button
    components/ThinkingBubble.tsx          Three animated dots
    components/FinalReportCard.tsx         Report display + raw-JSON edit modal
    types/{chat,api,opening}.ts            Message union, API DTOs, greeting copy
  features/reporting-target/
    components/BugSelector.tsx             <select> of active bug ids
  services/api/sessionApi.ts               fetch wrappers + ApiError
  services/storage/chatStorage.ts          localStorage persistence
```

## 2. State Model

`useChatSession` is the single source of truth. There is no context provider; `App` calls
the hook once and threads props down.

Persisted shape (localStorage key `burt-chat-state`):

```ts
{ selectedBugId: number | null,
  conversations: Record<bugIdAsString, { sessionId, status, messages }> }
```

One conversation per bug id, all kept in localStorage and rewritten on every state change.
There is no schema version field, so any change to the message union silently breaks
returning users' stored transcripts.

Message union (`types/chat.ts`): `agent | user | thinking | final_report | error`.
The `thinking` placeholder is pushed on submit and replaced in place by
`replaceThinkingMessage` when the response lands.

Conversation status: `idle | awaiting_user | submitting | completed | error`.
The composer is disabled when bug discovery is not `ready`, no bug is selected, or the
status is `submitting` or `completed`.

## 3. Backend Contract

Routes live in `backend/app/api/routes/sessions.py`; payloads in
`backend/app/schemas/sessions.py`.

| Endpoint | Used by frontend | Notes |
| --- | --- | --- |
| `GET /healthz` | no | reports Redis reachability |
| `GET /bugs/active` | yes, on mount | `{ bug_ids: number[] }` from loadable graph contexts |
| `POST /sessions` | yes, first message | creates session, runs first graph step |
| `GET /sessions/{id}` | **no** | returns last persisted turn; would enable recovery |
| `POST /sessions/{id}/messages` | yes, subsequent messages | 404 missing, 409 completed/locked |
| `POST /sessions/{id}/report` | yes, on report save | persists a user-edited report |

Every turn response is the same shape:

```ts
{ session_id, status: "awaiting_user" | "completed",
  question: string | null, final_report: object | null }
```

So the UI only ever knows "here is the next question" or "here is the finished report".
There is no streaming, no intermediate progress, and no cancel path.

Final report keys observed in logs: `title`, `observed_behavior`, `expected_behavior`,
`steps_to_reproduce` (a single newline-joined string, each line suffixed with a
`<transition-id>` that `FinalReportCard.sanitizeReportForDisplay` strips before display).

## 4. What The Logs Say About Real Usage

Source: 29 logs in `backend/logs/bugscribe_mutli-candidate_transitions_and_screen_descriptions/`,
22 of them completed API sessions (the `bug*_LC_LP`-style files are older CLI runs).

- **Turn latency is long.** Median 15.2s per turn, p90 32.4s, max 42.8s. The only feedback
  during that window is three pulsing dots.
- **Most sessions are short, but the tail is brutal.** Median 1 turn; the worst session
  (`f09ea09d`) took 10 turns, 9 follow-up questions, and 822s of wall-clock time.
- **The agent repeats itself when it is stuck.** In `f09ea09d` the same question ("which
  option did you tap after long-pressing the time entry") was re-asked in six consecutive
  turns with slightly different wording. The user answered "I dont know" and "Yes" out of
  fatigue. Nothing in the UI shows what the agent still needs or how close it is to done.
- **Follow-up text contains Markdown.** Turn 8 of `f09ea09d` asks about `**Edit Time**`,
  `**Delete Time**`, `**Move Time**`. `MessageBubble` renders raw text, so users see the
  literal asterisks.
- **The JSON editor destroys data.** `f09ea09d` has two `modified_report` records. The
  first edit left a dangling `"6."` and dropped steps 7 through 9; the second edit dropped
  step 6 entirely. The user was hand-editing a JSON string with `\n` escapes in a plain
  textarea and lost content both times.

Backend observation worth flagging separately: API-mode logs write `"turn": 1` on every
turn record (each HTTP request builds a fresh `TurnLogger`), while CLI logs increment
0..N correctly. `conversation_summary.total_conversation_turns` is still right.

## 5. Gaps Worth Addressing In The UI

Ordered roughly by user impact. None of these are decided yet — this is the candidate list.

**Waiting experience**
1. `ThinkingBubble` gives no stage, no elapsed time, and no cancel across a 15–40s wait.
   The backend already names its stages (`information_element_extraction`, `clarity_check`,
   `extract_and_update`, `evaluate`, `follow_up`) but none of that reaches the browser.
2. No optimistic timeout handling. If a turn exceeds nginx's 300s the fetch just rejects
   into a generic error bubble.

**Report review and editing**
3. ~~Editing is a raw JSON textarea.~~ **Done.** The editor is now a per-field form that
   mirrors the card's labels, with auto-growing fields and no nested scrollbar. List-valued
   fields edit one item per line; number, boolean, and nested-object types round-trip.
4. Saving an edit appends a *second* report card instead of replacing the first, so the
   transcript accumulates near-identical cards, each with its own Edit button.
5. No copy-to-clipboard, no export, no diff between the draft and the edited version.

**Conversation legibility**
6. Agent messages render as plain text, so Markdown emphasis in follow-ups leaks through.
7. No message timestamps, no visible turn count, no sense of progress toward a report.
8. `aria-live="polite"` sits on the whole transcript container, so assistive tech
   re-announces the full list on every change instead of just the new message.

**Session handling**
9. `GET /sessions/{id}` is never called. Recovery relies entirely on localStorage, so a
   cleared browser or a different device loses an in-flight session that the server still
   holds.
10. Changing the bug in the selector silently wipes that bug's transcript
    (`resetConversationForBug`) with no confirmation. `App.test.tsx` asserts this as
    intended behavior, so changing it means updating that test.
11. Stored state has no version field or migration path.
12. Error bubbles offer no retry button; the draft is restored but the user has to find
    and press Send again.

**Input ergonomics**
13. ~~The composer textarea is `rows={1}` with no auto-grow.~~ **Done.** It starts at one
    row and grows with the draft, capped at 40% of the viewport before it scrolls.
14. ~~Enter inserts a newline; there is no Enter-to-send handling.~~ **Done.** Enter sends
    the draft, Shift+Enter inserts a newline, and Enter is ignored while the composer is
    disabled or the draft is blank.

**Visual system**
15. Every color, radius, and shadow is a hard-coded literal in `styles.css`. No custom
    properties, no tokens, no dark mode, no `prefers-reduced-motion` handling for the
    pulsing dots.
16. The bug selector shows only `Bug 10` — no app name or bug title, though the backend
    context payload holds `application_name`.

## 6. Working Notes

- Run the UI alone: `cd frontend && npm run dev`. `vite.config.ts` proxies `/api` to
  `http://localhost:3000` (the Compose nginx), so the rest of the stack must be up or every
  call fails. Without that proxy `/api/...` hits the SPA index fallback and returns HTML,
  which surfaces as "could not reach the server" in the bug selector.
- Run the full stack: `docker compose up --build`, UI at `http://localhost:3000`.
- Tests: `cd frontend && npm test`. `npm run build` runs `tsc --noEmit` on both tsconfigs
  before `vite build`, so type errors fail the build.
- `App.test.tsx` covers bug discovery, stored-session restore, thinking-bubble swap,
  bug-change wipe, error bubble, completed-report composer lock, and the edit-and-save
  flow. Any UI restructuring will touch these tests — they query by accessible name
  (`Message BURT`, `Select bug to report on`, `Bug report JSON`), so keep those labels
  stable or update the tests deliberately.
