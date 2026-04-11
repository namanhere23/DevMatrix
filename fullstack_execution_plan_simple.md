# DevMatrix Full-Stack Execution Plan (Simple Version)

## 1) Goal

Turn the current multi-agent project into a usable full-stack product with:

1. Agent orchestration + AI logic
2. Backend APIs
3. Frontend web app

This plan also includes:

1. Moving orchestration to LangGraph + LangChain
2. Removing Telegram HITL
3. Replacing HITL with user decisions inside the app:

- Retry
- Accept current output
- Stop run

---

## 2) What “Done” Looks Like

At the end, a user can:

1. Submit a goal from the web UI
2. Watch agent progress live
3. See Critic feedback when a task fails
4. Choose Retry / Accept current output / Stop
5. Get final or partial output with artifacts

Engineering success means:

1. Core paths work end-to-end
2. Legacy fallback still works
3. Important tests pass

---

## 3) Team Setup (3 Teams)

## Team A: Orchestration + AI Logic

Responsible for:

1. LangGraph flow and node logic
2. LangChain model integration
3. Guardian placement as first step
4. Retry loop and critic decision routing
5. Removing Telegram and adding in-app decision handling

## Team B: Backend

Responsible for:

1. Run lifecycle APIs
2. Events API (for live UI)
3. Decision API (retry/accept/stop)
4. Artifact retrieval API
5. Health and readiness APIs

## Team C: Frontend

Responsible for:

1. Goal submission screen
2. Live run monitor screen
3. Decision modal for failures
4. Final/partial output screen
5. Error states and responsive behavior

---

## 4) Important Rules Before Building

1. Freeze API contracts first (status values, decision values, error shape).
2. Keep behavior same as current system first, improve later.
3. Keep Guardian as first gate before Scout.
4. Log every important state change as an event.
5. Keep retries bounded and deterministic.
6. Keep a fallback switch:

- ORCHESTRATOR_ENGINE=legacy|langgraph

7. Remove Telegram from runtime path fully.
8. Keep existing tests green while adding new tests.

---

## 5) Proposed API Contracts (Simple)

## Status values

1. queued
2. guarding
3. decomposing
4. executing
5. awaiting_decision
6. completed
7. stopped
8. failed

## Decision values

1. retry
2. accept_current
3. stop

## Core endpoints

1. POST /api/v1/runs
2. GET /api/v1/runs/{id}
3. GET /api/v1/runs/{id}/events
4. POST /api/v1/runs/{id}/decision
5. GET /api/v1/runs/{id}/artifacts
6. GET /api/v1/health/live
7. GET /api/v1/health/ready

---

## 6) Build Plan by Phase

## Phase 0: Pre-Flight (1-2 hours)

1. Freeze contracts and enums.
2. Assign owners for each module.
3. Create working branches per team.
4. Define integration checkpoints.
5. Confirm rollback path to legacy orchestrator.

Output of phase:

- One shared contract doc
- One shared “definition of done” checklist

---

## Phase 1: Skeletons (2-3 hours)

## Team A

1. Create LangGraph state object.
2. Add nodes:

- guardian
- scout
- architect
- fixer
- critic
- decision
- summary

3. Connect basic node flow with placeholders.

## Team B

1. Create API project structure.
2. Add all core endpoints with mock responses.
3. Add run storage abstraction (file or sqlite).

## Team C

1. Create 3 main screens + routing.
2. Add API service layer.
3. Add placeholder states for run data.

Output of phase:

- All parts compile/run with placeholder behavior

---

## Phase 2: Core Logic (3-4 hours)

## Team A

1. Wrap current agents inside LangGraph nodes.
2. Implement critic routing:

- approve -> next task
- reject + retries left -> retry architect with feedback
- reject + retries exhausted -> decision state

3. Keep memory/context handoff working.

## Team B

1. Connect API endpoints to orchestrator service.
2. Persist run status transitions.
3. Implement events feed with cursor/offset.

## Team C

1. Submit run from UI.
2. Poll run + events and render timeline.
3. Show current task, attempts, and score.

Output of phase:

- End-to-end path works without user decision branch

---

## Phase 3: Telegram Removal + Decision Replacement (2-3 hours)

## Team A

1. Remove Telegram usage from runtime orchestration path.
2. Replace escalation with decision wait state.
3. Support 3 actions:

- retry: continue one more attempt path
- accept_current: finish with current best output
- stop: end run immediately

## Team B

1. Implement POST decision endpoint logic.
2. Add decision timeout policy (recommended default: stop).
3. Log decision audit event (who, when, action, reason).

## Team C

1. Add decision modal UI.
2. Explain action consequences clearly.
3. Send decision to backend and reflect new state.

Output of phase:

- Reject flow is fully controllable by user in-app

---

## Phase 4: LangChain Integration + Hardening (2-3 hours)

## Team A

1. Put LangChain adapter in front of model calls.
2. Preserve provider preference/fallback behavior.
3. Keep mock mode behavior available.

## Team B

1. Add robust error responses and idempotency guards.
2. Add artifact listing and safe file access.

## Team C

1. Add final and partial output views.
2. Add resilient loading and retry states.
3. Validate mobile behavior.

Output of phase:

- Production-like user flow with stable behavior

---

## 7) Test Plan (Must Run)

## Existing tests

1. Keep existing suite passing.

## New critical tests

1. approve-complete path
2. reject-retry-approve path
3. reject-accept_current path
4. reject-stop path
5. guardian gate runs before decomposition
6. decision endpoint rejects invalid action values

## Manual checks

1. Submit a normal coding goal.
2. Force a critic rejection.
3. Test all 3 decisions from UI.
4. Confirm events and artifacts are visible.
5. Switch to legacy engine and verify fallback works.

---

## 8) Go / No-Go Gates

## Gate 1

User can submit goal and see live events.

## Gate 2

Rejection triggers decision modal.

## Gate 3

All 4 critical paths pass.

## Gate 4

Fallback to legacy engine is proven.

If any gate fails:

1. Fix P0/P1 only.
2. Defer non-critical UI polish.
3. Keep fallback enabled.

---

## 9) Risks and Simple Mitigations

1. Risk: LangGraph migration changes behavior.

- Mitigation: keep legacy path behind feature flag and compare outputs.

2. Risk: Decision flow causes deadlock.

- Mitigation: decision timeout with default stop.

3. Risk: Frontend and backend contract mismatch.

- Mitigation: freeze enums and response schema before coding.

4. Risk: Team coordination delays.

- Mitigation: fixed integration checkpoints and one owner per module.

---

## 10) Definition of Done Checklist

1. LangGraph orchestration path is running.
2. LangChain model path is integrated.
3. Telegram runtime dependency is removed.
4. In-app decision flow (retry/accept/stop) is working.
5. Backend APIs are stable and documented.
6. Frontend screens are complete and usable.
7. Critical tests and manual flows pass.
8. Legacy fallback path works.

---

## 11) Suggested Delivery Order (Fastest Path)

1. Contracts first
2. End-to-end skeleton second
3. Telegram replacement third
4. LangChain adapter fourth
5. Hardening and polish last

This order gives the highest chance of shipping a working full-stack version quickly and safely.
