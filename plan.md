# DevMatrix Full-Stack 12-Hour Execution Plan

## Objective

Deliver a working full-stack version of the current multi-agent project within 12 hours using 3 parallel teams:

1. Agent Orchestration and AI Logic Team
2. Backend Team
3. Frontend Team

This plan explicitly includes:

- LangChain + LangGraph integration
- Removal of Telegram HITL module
- Replacement of escalation behavior with direct user decision flow: Retry, Accept Current Output, or Stop

---

## Scope

### In Scope (must ship in 12 hours)

1. LangGraph-driven orchestration path for current swarm lifecycle.
2. LangChain model integration path for all agent calls.
3. Full removal of Telegram runtime HITL dependency.
4. New user decision mechanism for escalation events.
5. Backend endpoints for run lifecycle, events, decisions, and artifacts.
6. Frontend app with submit, monitor, decision modal, and output views.
7. Core regression and integration tests for critical flows.

### Out of Scope (defer)

1. Multi-tenant auth and permissions.
2. Billing/cost metering.
3. Horizontal scaling and distributed workers.
4. Enterprise deployment hardening beyond basic container/runtime readiness.

---

## Non-Negotiable Must-Dos

1. Preserve behavior parity first, optimize later.
2. Freeze API contracts before frontend integration begins.
3. Keep Guardian as first gate before decomposition.
4. Every state transition must emit an event (for observability and debugging).
5. Retry loops must be bounded and deterministic.
6. User decision is authoritative at escalation points.
7. Keep feature flags for safe fallback:
   - `ORCHESTRATOR_ENGINE=legacy|langgraph`
   - `HITL_MODE=inline|disabled`
8. Keep existing tests passing while adding migration tests.
9. If any task is blocked >30 minutes, execute contingency path.

---

## Team Structure and Ownership

### Team A: Agent Orchestration and AI Logic

Owns:

- LangGraph state machine and node transitions
- LangChain model invocation adapters
- Guardian integration in graph entry path
- Retry and critic decision semantics
- Telegram removal and inline user decision replacement

### Team B: Backend

Owns:

- API server and orchestration service wrapper
- Run lifecycle and persistence
- Event streaming/polling endpoint reliability
- Decision endpoint and idempotency
- Artifact listing/retrieval

### Team C: Frontend

Owns:

- Goal submission UI
- Live run monitoring UI
- Approval decision modal (Retry/Accept/Stop)
- Output and partial-output UX
- Error states and responsiveness

---

## 12-Hour Timeline

### Hour 0-1: Sprint Pre-Flight (All Teams)

1. Lock acceptance criteria and DoD.
2. Freeze endpoint schemas and enums.
3. Lock branch strategy:
   - `team/orchestration-langgraph`
   - `team/backend-api`
   - `team/frontend-app`
   - `integration/fullstack-12h`
4. Confirm merge checkpoints: Hour 4, Hour 8, Hour 11.
5. Confirm fallback plan to legacy engine.

### Hour 1-3: Foundations

- Team A: Define graph state + create node shells.
- Team B: Build API skeleton + DTO validation.
- Team C: Build UI skeletons and routing.

### Hour 3-4: Integration Checkpoint 1

1. Validate schema compatibility.
2. Run first smoke path end-to-end (minimal).
3. Resolve contract mismatches immediately.

### Hour 4-6: Core Build

- Team A: Implement conditional edges + retry semantics.
- Team B: Integrate orchestration service + run state persistence.
- Team C: Integrate submit + live monitor with backend.

### Hour 6-8: HITL Replacement Window

- Team A: Remove Telegram runtime path; add inline decision branch.
- Team B: Wire `/decision` endpoint and run control.
- Team C: Build decision modal and action handling.

### Hour 8: Integration Checkpoint 2

1. Validate reject -> decision flow.
2. Confirm all 3 actions work: Retry, Accept Current Output, Stop.

### Hour 8-10: Stabilization

- Team A: Complete LangChain adapter parity and graph hardening.
- Team B: Event/artifact robustness + integration tests.
- Team C: UX clarity, edge states, responsive fixes.

### Hour 10-11: Final Integration + Bug Bash

1. Merge all team branches.
2. Run full smoke suite.
3. Fix P0/P1 regressions only.

### Hour 11-12: Final Verification + Demo Readiness

1. Verify DoD paths.
2. Validate fallback switch works.
3. Freeze release branch and prep demo runbook.

---

## Team A Detailed Execution (LangGraph/LangChain + Telegram Removal)

### Phase A1 (Hour 1-3): Graph Skeleton

1. Define canonical graph state to map existing runtime fields:
   - `goal`
   - `guardian_result`
   - `sub_tasks`
   - `task_index`
   - `attempt_count`
   - `plan`
   - `fixer_result`
   - `critic_verdict`
   - `decision_action`
   - `results`
   - `memory_snapshot`
2. Build nodes:
   - `guardian_node`
   - `scout_node`
   - `architect_node`
   - `fixer_node`
   - `critic_node`
   - `decision_node`
   - `summary_node`
3. Wrap existing agent methods first; do not rewrite prompts yet.

### Phase A2 (Hour 3-5): Routing and Retry Behavior

1. Implement edge routing parity:
   - Approve -> next sub-task
   - Reject + attempts remaining -> retry Architect with feedback
   - Reject + max attempts -> user decision required
2. Keep deterministic retry caps.
3. Ensure memory constraints still feed planning node.

### Phase A3 (Hour 5-7): LangChain Adapters

1. Introduce LangChain model layer behind compatibility adapter.
2. Preserve provider preference/fallback policy from current provider layer.
3. Preserve mock mode support.
4. Keep cache semantics stable.

### Phase A4 (Hour 6-8): Remove Telegram + Replace Decision Flow

1. Remove runtime dependency and imports related to Telegram HITL.
2. Replace escalation branch with user decision contract:
   - `retry`
   - `accept_current`
   - `stop`
3. Define timeout default behavior (recommended: `stop`).
4. Emit explicit decision events for traceability.

### Phase A5 (Hour 8-10): Hardening

1. Validate Guardian still executes first.
2. Validate decision branch outcomes are correct in all cases.
3. Validate summary and artifacts for partial outputs.

### Team A Contingency

If full LangChain migration is unstable by Hour 8, ship graph engine with compatibility wrappers and keep direct provider internals behind the adapter, then complete LangChain internals post-sprint.

---

## Team B Detailed Execution (Backend)

### Phase B1 (Hour 1-3): API Contract and Server Skeleton

Implement endpoints:

1. `POST /api/v1/runs`
2. `GET /api/v1/runs/{id}`
3. `GET /api/v1/runs/{id}/events`
4. `POST /api/v1/runs/{id}/decision`
5. `GET /api/v1/runs/{id}/artifacts`
6. `GET /api/v1/health/live`
7. `GET /api/v1/health/ready`

### Phase B2 (Hour 3-5): Orchestration Service and Run Lifecycle

1. Build service layer to invoke `legacy` or `langgraph` engine by flag.
2. Persist run metadata and status transitions.
3. Normalize error schema:
   - `code`
   - `message`
   - `details`

### Phase B3 (Hour 5-7): Events and Artifacts

1. Implement event polling with cursor/offset.
2. Add artifact listing and retrieval.
3. Sanitize paths to prevent traversal.

### Phase B4 (Hour 7-9): Decision API Wiring

1. Wire decision endpoint to orchestration branch controls.
2. Enforce valid actions only.
3. Enforce idempotency and terminal-state protection.

### Phase B5 (Hour 9-11): Tests and Hardening

1. Add integration tests for:
   - approve-complete path
   - reject-retry-approve path
   - reject-accept_current path
   - reject-stop path
2. Validate health readiness behavior under mock/live provider conditions.

### Team B Contingency

If streaming becomes unstable, ship polling-only mode with reliable event continuity.

---

## Team C Detailed Execution (Frontend)

### Phase C1 (Hour 1-3): Core Screens

Build:

1. Goal submission page
2. Live run monitor
3. Decision modal
4. Result/partial-result page

### Phase C2 (Hour 3-6): API Integration

1. Hook run creation to `POST /runs`.
2. Hook status and events polling.
3. Hook decision actions to `POST /runs/{id}/decision`.

### Phase C3 (Hour 6-9): Decision UX Clarity

1. Show critic feedback and attempt count clearly.
2. Explain consequence of each action before confirmation:
   - Retry: continue next attempt
   - Accept Current Output: complete with current artifacts
   - Stop: terminate now with partial output
3. Show clear labels for run outcome state.

### Phase C4 (Hour 9-11): QA and Resilience

1. Handle network interruptions with retry UX.
2. Ensure mobile + desktop responsiveness.
3. Handle stale session and terminal-state restoration.

### Team C Contingency

If advanced visualizations block timeline, prioritize clarity and decision flow correctness over visual extras.

---

## Telegram Removal and Replacement Requirements

1. Remove Telegram module from active runtime flow entirely.
2. Escalation must produce a backend decision request.
3. Orchestrator must pause/await decision (with timeout policy).
4. Decision actions must be auditable in event log.
5. UI must be the single interaction surface for escalation decisions.

---

## Required Contracts (Freeze Early)

### Run Status Enum (example)

- `queued`
- `guarding`
- `decomposing`
- `executing`
- `awaiting_decision`
- `completed`
- `stopped`
- `failed`

### Decision Action Enum

- `retry`
- `accept_current`
- `stop`

### Event Payload Must Include

1. timestamp
2. run_id
3. agent_or_node
4. action
5. data

---

## Go/No-Go Quality Gates

### Gate 1 (Hour 4)

Can create run and get live updates.

### Gate 2 (Hour 8)

Reject path successfully reaches decision modal and processes action.

### Gate 3 (Hour 11)

All four critical paths pass:

1. approve-complete
2. reject-retry-approve
3. reject-accept_current
4. reject-stop

### Gate 4 (Hour 12)

Legacy fallback switch is proven and safe.

---

## Verification Plan

### Automated

1. Existing tests remain green.
2. New branch tests pass for decision actions.
3. End-to-end smoke for full run lifecycle passes.

### Manual

1. Submit goal and verify Guardian gate first.
2. Force critic rejection and test each decision action.
3. Verify partial output behavior for `accept_current` and `stop`.
4. Verify artifacts accessible from result view.

### Operational

1. Health endpoints report expected status.
2. Event timeline remains consistent across retries.
3. Provider fallback and mock behavior remain functional.

---

## Definition of Done

1. Full-stack flow is operational with 3-team deliverables integrated.
2. LangGraph engine executes orchestration path with behavior parity.
3. LangChain integration path is active (or adapter-compatible under flag).
4. Telegram HITL is removed from active runtime path.
5. User decision replacement flow is fully functional.
6. Critical tests and smoke checks pass.
7. Demo flow reflects updated orchestration and decision behavior.

---

## Delivery Notes for Leads

1. Prioritize correctness of decision branch over extra features.
2. If blocked, prefer shipping stable fallback-compatible implementation.
3. Do not compromise observability; it is required for debugging and demo credibility.
4. Keep all changes behind feature flags until final integration checkpoint.
