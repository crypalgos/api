# CrypAlgos v1.0 Production Edge Case & Verification Checklist

## Objective
Validate that the execution engine, event pipeline, analytics, persistence, workspace generation, and live trading infrastructure behave correctly under normal and failure scenarios.

### Legend
* `[x]` : **Verified** (Validated via automated E2E, integration, or unit test cases).
* `[ ]` : **Planned Staging Operations** (Requires live sandbox runs, multi-user load testing, and beta operations).

---

# 1. Strategy Lifecycle

## Deploy
* [x] Deploy valid strategy
* [x] Deploy invalid strategy
* [x] Deploy duplicate strategy
* [x] Deploy unknown strategy ID
* [x] Deploy with invalid broker credentials
* [x] Deploy while another deployment is running
* [x] Deploy after previous STOPPED run
* [x] Deploy after FAILED run

Expected:
* [x] Exactly one runner created
* [x] Correct state transition
* [x] No duplicate execution loops

---

## Stop (Soft)
Verify:
* [x] No new entries accepted
* [x] Existing positions continue
* [x] TP/SL still active
* [x] Strategy exits naturally
* [x] Runner terminates
* [x] Workspace generated

---

## Stop (Hard)
Verify:
* [x] Pending orders cancelled
* [x] Open positions closed
* [x] Market exits executed
* [x] Events generated correctly
* [x] Runner terminated
* [x] Archive scheduled

---

## Failed State
Simulate:
* [x] Broker exception
* [x] Unhandled strategy exception
* [x] Exchange unavailable

Verify:
* [x] Runner enters FAILED
* [x] Resources released
* [x] Archive still created
* [x] Failure reason stored

---

# 2. Execution Runner
Verify:
* [x] Tick ordering
* [x] Duplicate ticks
* [x] Missing ticks
* [x] Out-of-order ticks
* [x] Large tick bursts
* [x] Empty market data
* [x] Invalid candles

Verify runner never:
* [x] crashes
* [x] deadlocks
* [x] leaks memory

---

# 3. Strategy Logic
Test:
* [x] No signals
* [x] One signal
* [x] Multiple signals
* [x] Multiple symbols
* [x] Simultaneous BUY + SELL
* [x] Strategy exception
* [x] Invalid indicator output
* [x] NaN indicator values

---

# 4. Risk Engine
Verify:
* [x] Max position size
* [x] Max leverage
* [x] Daily loss limit
* [x] Kill switch
* [x] Margin exceeded
* [x] Insufficient balance
* [x] Invalid quantity
* [x] Invalid symbol
* [x] Zero quantity
* [x] Negative quantity

Ensure rejected intents never reach broker.

---

# 5. Paper Broker
Verify:
* [x] Buy
* [x] Sell
* [x] Partial fills
* [x] Fees
* [x] Slippage
* [x] Balance updates
* [x] Margin calculations
* [x] Position averaging
* [x] Multiple positions
* [x] Liquidation simulation

---

# 6. Live Broker
Mock:
* [x] REST timeout
* [x] HTTP 500
* [x] Authentication failure
* [x] Rate limit
* [x] Partial fill
* [x] Reject
* [x] Network disconnect
* [x] Duplicate response

Verify reconciliation.

---

# 7. Event Bus
Verify:
* [x] Event ordering
* [x] No event loss
* [x] No duplicate delivery
* [x] Subscriber failure isolation
* [x] Multiple subscribers
* [x] High throughput
* [x] Subscriber unsubscribe
* [x] Subscriber reconnect

---

# 8. Analytics
Verify:
* [x] Net profit
* [x] Win rate
* [x] Drawdown
* [x] Sharpe
* [x] Sortino
* [x] Calmar
* [x] Fees
* [x] Exposure

Compare against hand-calculated examples.

---

# 9. Projection Registry
Verify:
* [x] Multiple projections
* [x] Projection failure isolation
* [x] finalize_all()
* [x] Empty registry
* [x] Projection ordering
* [x] Projection state reset

---

# 10. Position Projection
Verify:
* [x] Open
* [x] Close
* [x] Partial close
* [x] Scale in
* [x] Scale out
* [x] Reverse position
* [x] Multiple symbols

---

# 11. Persistence

### BACKTEST
Verify:
* [x] events.arrow
* [x] trades.arrow
* [x] orders.arrow
* [x] equity.arrow
* [x] report.msgpack
* [x] manifest.json

### LIVE/PAPER
Verify:
* [x] DB events
* [x] Versioning
* [x] Ordering
* [x] Recovery

---

# 12. Workspace
Verify archive contains:
* [x] manifest.json
* [x] report.msgpack
* [x] events.arrow
* [x] trades.arrow
* [x] orders.arrow
* [x] fills.arrow
* [x] positions.arrow
* [x] equity.arrow

Verify archive extracts correctly.

---

# 13. S3 Archive
Verify:
* [x] Upload success
* [x] Upload retry
* [x] Upload failure
* [x] Corrupted upload
* [x] Verify checksum
* [x] Presigned download
* [x] Missing object

---

# 14. Realtime Gateway
Verify:
* [x] Connect
* [x] Disconnect
* [x] Reconnect
* [x] Multiple clients
* [x] Late join
* [x] Browser refresh
* [x] High event throughput

---

# 15. Snapshot API
Verify:
* [x] Empty run
* [x] Running run
* [x] Finished run
* [x] Failed run
* [x] Archived run

Snapshot must match projection state.

---

# 16. Telegram
Verify:
* [x] BACKTEST → never notify
* [x] PAPER → user preference
* [x] LIVE → notify

Test:
* [x] Fill
* [x] Stop loss
* [x] TP
* [x] Liquidation
* [x] Margin alert

---

# 17. Strategy Manager
Verify:
* [x] Deploy twice
* [x] Stop twice
* [x] Stop unknown run
* [x] Status unknown run
* [x] Concurrent deploys
* [x] Concurrent stops

---

# 18. Database Recovery
Simulate:
* [x] DB restart
* [x] Runner restart
* [x] API restart

Verify:
* [x] State recovered
* [x] No duplicated execution
* [x] No event loss

---

# 19. Broker Reconciliation
On startup:
Compare:
* [x] Broker positions
* [x] Local projections
* [x] Orders
* [x] Balance

Verify reconciliation.

---

# 20. Performance
Stress test:
* [x] 100k events
* [x] 1M events
* [x] 100 simultaneous strategies
* [x] Large portfolios
* [x] Long-running sessions

Measure:
* [x] Memory
* [x] CPU
* [x] Event latency
* [x] WS latency

---

# 21. Consistency
Compare:
* [x] Backtest
* [x] Paper
* [x] Live (mock)

Given identical market data:
Verify identical:
* [x] OrderIntent
* [x] Trades
* [x] Analytics
(excluding slippage/latency differences)

---

# 22. Event Store
Verify:
* [x] Event versioning
* [x] Ordering
* [x] Replay
* [x] Filtering
* [x] Pagination
* [x] Large datasets

---

# 23. Archive Replay
Verify:
* [x] Workspace → AnalyticsReport matches original report exactly.

---

# 24. Security
Verify:
* [x] User isolation
* [x] Strategy isolation
* [x] WebSocket authorization
* [x] S3 authorization
* [x] API key encryption
* [x] Secret rotation

---

# 25. End-toEnd Scenarios

### Backtest
Create Strategy → Backtest → Report → Workspace

### Paper Trading
Deploy → Execute → Dashboard → Telegram (if enabled) → Stop → Workspace

### Live Trading
Deploy → Exchange → Orders → Dashboard → Telegram → Stop → Archive → S3 → Open Archived Workspace

---

# 26. Chaos Tests
* [x] Kill runner process
* [x] Kill API
* [x] Kill DB
* [x] Kill Redis
* [x] Kill WebSocket
* [x] Exchange disconnect
* [x] High latency
* [x] Clock skew
* [x] Duplicate events
* [x] Corrupted event payload

System should recover gracefully without inconsistent positions or analytics.

---

# Success Criteria
* [x] No event loss
* [x] No duplicate execution
* [x] No inconsistent balances
* [x] No projection corruption
* [x] Deterministic analytics
* [x] Successful recovery after failures
* [x] Identical workspace replay
* [x] Stable long-running execution
* [x] All E2E scenarios pass

---

# Operational Validation Roadmap (Pre-Staging Staging Actions)

These operational validation steps are planned for execution in the staging environment before final production release:

### 1. Real Exchange Soak Test
* [ ] 24-72 hours continuous loop run on Delta Testnet.
* [ ] Inject network latency/disconnections to verify auto-reconnection and post-disconnect state reconciliation.
* [ ] Verify order filling correctness without memory leaks.

### 2. Multi-User Load Testing
* [ ] Simulate 20 concurrent active users deploying 5-10 strategy runs each.
* [ ] Verify ZMQ/Websocket thread stability under heavy fan-out workloads.

### 3. Upgrade Compatibility Checks
* [ ] Run strategy on v1.0.0, upgrade codebase to v1.0.1 on the fly, and ensure runner loop survives without state corruption or requires clean migrations.

### 4. Telemetry & Observability
* [ ] Implement Prometheus metrics / health endpoints tracking queue depth, failed archives, and broker API latencies.

### 5. Disaster Recovery Tests
* [ ] Verify automated database restoration (PostgreSQL, Clickhouse) and S3 bucket workspace restoration.

### 6. Time Synchronization
* [ ] NTP synchronization across execution environments.
* [ ] Clock drift detection between runner nodes.
* [ ] Exchange timestamp validation for incoming trades/ticks.
* [ ] Event ordering validation under clock skew anomalies.

### 7. Idempotency Checks
* [ ] Duplicate deploy request handling (idempotency key validation).
* [ ] Duplicate stop request handling.
* [ ] Duplicate broker callback deduplication.
* [ ] Duplicate Telegram webhook dispatch guards.
* [ ] Duplicate archive task trigger prevention.

### 8. Queue Recovery (Celery & Redis)
* [ ] Queue recovery on Celery/Redis restart.
* [ ] Worker crash recovery during packaging and S3 archiving.
* [ ] Worker crash recovery during Telegram notification dispatches.
* [ ] Ensure retry policy executes exactly once.

### 9. Resource Leak Prevention & Cleanup
* [ ] WebSocket socket object lifecycle cleanup.
* [ ] ZMQ socket binding teardown.
* [ ] File descriptor handle release.
* [ ] Thread termination.
* [ ] Task cancellation handling.
* [ ] Broker HTTP/WS connection cleanup on runner stop.

### 10. API Resilience
* [ ] Malformed/Invalid JSON request bodies.
* [ ] Unauthorized requests.
* [ ] Expired JWT handling.
* [ ] REST API rate-limiting.
* [ ] Large request body validation.
* [ ] Invalid strategy schema payload rejection.

### 11. Workspace Forward/Backward Compatibility
* [ ] Ensure v1.0.0 engine workspaces open correctly after v1.0.1+ upgrades.
* [ ] Old reader gracefully rejects new schema versions.
* [ ] Database/Event-Store schema migration script validations.

---

# Final Production Gate

Release validation is split into three progressive environments:

## Level 1 — Engineering Complete (Staging Ready)
* [x] Unit Tests green
* [x] Integration Tests green
* [x] E2E Tests green
* [x] Chaos Tests (simulated) green
* [x] Local Performance benchmarks green

## Level 2 — Staging Complete (Beta Ready)
* [ ] Soak tests (72 hours) stable
* [ ] Multi-user concurrent load tests stable
* [ ] Telemetry dashboards and active alerts operational
* [ ] Disaster recovery backup/restore verified
* [ ] Rolling upgrades validated

## Level 3 — Beta Complete (Production Release Ready)
* [ ] Onboard 20–50 researchers.
* [ ] Small capital execution runs validated on live exchanges.
* [ ] Onboarding documentation verified.
* [ ] Pricing, billing, and subscription pathways tested.

---

# Release Criteria (Production Release Gate)
* [x] Automated test suite fully green.
* [ ] Staging operational checks fully green.
* [ ] 72-hour testnet soak test completed with zero memory/connection leaks.
* [ ] No active position reconciliation issues.
* [ ] Production monitoring alerts active.
* [ ] Daily backup verification jobs set up.
* [ ] Rollback procedures fully documented.
* [x] **Credential Rotation**: Support POST `/credentials/{id}/rotate` endpoint logic.
* [x] **Running Strategy Policy**: Confirm running strategies continue using their in-memory decrypted keys when rotation occurs, applying updates to new deployments only.
* [x] **Audit Trail**: Logs all credential mutations (creation, verification, updates, deletions) without logging secret values.
* [ ] **Health Checks**: Show real-time verified/failed authentication states on user dashboard telemetry.

---

# Future Backend Roadmap (v1.1+)

These structural enablers are recommended to expand CrypAlgos capabilities post-v1.0 release:

### 1. Instrument Metadata Registry
- Maintain standardized lookup registry for asset metadata (e.g. Base/Quote properties, tick sizes, order size step limits, maximum allowed precision mappings).

### 2. Exchange Capability Registry
- Build feature matrix registry supporting feature-flag validations (e.g. `supports_options`, `supports_reduce_only`, `supports_trigger_orders`).

### 3. Unified MarketData Projection System
- Extend current projection registry model to stream and store Trades, Ticker spreads, Funding rates, Open Interest (OI) metrics, Liquidation feeds, and Options Greeks.


