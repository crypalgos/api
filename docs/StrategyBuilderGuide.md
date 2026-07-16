# CrypAlgos Strategy Builder Guide

Welcome to **CrypAlgos Strategy Builder**, a visual environment for designing, testing, and understanding systematic trading strategies.

Unlike traditional trading platforms, CrypAlgos doesn't treat a strategy as a black box. Every decision made by the execution engine can be replayed, inspected, and explained through the Analyze Workspace.

This guide introduces the core building blocks of the Strategy Builder and walks through creating a complete multi-asset strategy from data selection to explainable backtesting.

---

# Strategy Architecture

Every strategy in CrypAlgos follows the same execution pipeline.

```text
Visual Strategy
        │
        ▼
Strategy Compiler
        │
        ▼
Compiled Python Strategy
        │
        ▼
Execution Engine
        │
        ▼
Backtest
        │
        ▼
Analyze Workspace
```

When you click **Run Backtest**, the visual graph is compiled into executable Python code. The execution engine evaluates the strategy against historical market data and generates deterministic results.

Running the same strategy with the same market data and parameters will always produce the same output.

---

# Strategy Building Blocks

Every strategy is built from five node types.

## 1. Data Node

The Data Node defines the market your strategy operates on.

Configuration:

* Exchange
* Market (Spot / Futures)
* Trading Symbol
* Timeframe
* Leverage

Examples:

* Delta Futures → BTCUSD → 1 Hour
* Binance Spot → ETHUSDT → 15 Minutes

A strategy may contain multiple Data Nodes, allowing simultaneous trading across different assets.

For educational purposes, leverage between **2× and 5×** is recommended.

---

## 2. Indicator Node

Indicator Nodes transform raw market data into analytical signals.

Supported indicators include:

* EMA
* SMA
* RSI
* ATR
* MACD
* Bollinger Bands
* VWAP
* Stochastic RSI
* and many more.

Multiple indicators can be attached to a single Data Node.

Example:

```
BTCUSD

↓

EMA(9)

EMA(21)

RSI(14)
```

---

## 3. Condition Node

Condition Nodes contain the trading logic.

Conditions compare indicators using operators such as:

* Crosses Above
* Crosses Below
* Greater Than
* Less Than
* Equal

Conditions may be grouped using nested AND / OR logic.

Example:

```
EMA(9) crosses above EMA(21)

AND

RSI > 50

AND

RSI < 70
```

---

## 4. Action Node

Action Nodes convert trading signals into executable orders.

Supported actions:

* Buy (Open Long)
* Sell (Close Long)
* Short (Open Short)
* Cover (Close Short)

Each Action defines:

* Execution Trigger
* Position Size
* Order Type
* Execution Parameters

Execution Triggers:

* Execute Immediately
* Execute On Bar Close

Position sizing options:

* Percentage of Equity
* Fixed USD
* Fixed Quantity

---

## 5. Policy Group

Policy Groups manage risk after a position is opened.

A Policy Group becomes active only after an entry order is filled.

Available policies include:

* Stop Loss
* Take Profit
* Trailing Stop
* Break Even

Policies are independent.

The runtime continuously evaluates every active policy, and whichever policy triggers first executes according to its configuration.

---

# How CrypAlgos Executes Your Strategy

The runtime follows a deterministic execution pipeline.

```text
Market Data
        │
        ▼
Indicators Calculated
        │
        ▼
Conditions Evaluated
        │
        ▼
Entry Action Triggered
        │
        ▼
Position Size Calculated
        │
        ▼
Entry Order Submitted
        │
        ▼
Entry Order Filled
        │
        ▼
Position Opens
        │
        ▼
Policy Group Activated
        ├── Stop Loss
        ├── Take Profit
        ├── Break Even
        └── Trailing Stop
        │
        ▼
Exit Order Filled
        │
        ▼
Position Closed
        │
        ▼
Runtime Events
        │
        ▼
Decision Trace Generated
        │
        ▼
Trade Ledger Updated
        │
        ▼
Analytics Report Generated
```

Every stage of this pipeline is inspectable inside the Analyze Workspace.

---

# Example Strategy

## Multi-Asset Trend + Momentum Strategy

This strategy trades Bitcoin and Ethereum simultaneously using trend confirmation and momentum filtering.

## Step 1 — Data

Create two Data Nodes.

Node A

```
Exchange: Delta

Market: Futures

Symbol: BTCUSD

Timeframe: 1 Hour

Leverage: 3×
```

Node B

```
Exchange: Delta

Market: Futures

Symbol: ETHUSD

Timeframe: 1 Hour

Leverage: 3×
```

---

## Step 2 — Indicators

For each asset add:

EMA

* Fast EMA (9)

* Slow EMA (21)

RSI

* Period 14

---

## Step 3 — Long Entry

```
EMA(9) crosses above EMA(21)

AND

RSI > 50

AND

RSI < 70
```

---

## Step 4 — Short Entry

```
EMA(9) crosses below EMA(21)

AND

RSI < 50

AND

RSI > 30
```

Duplicate this logic for both BTC and ETH.

Each asset evaluates independently.

A BTC signal never triggers an ETH trade.

---

## Step 5 — Actions

Connect the Long Conditions to Buy Actions.

Connect the Short Conditions to Short Actions.

Configuration:

Trigger

```
Execute On Bar Close
```

Position Size

```
10% of Portfolio Equity
```

---

## Step 6 — Risk Management

Attach a single Policy Group to every entry action.

Configuration:

Stop Loss

```
3%

Exit Quantity

100%
```

Take Profit

```
6%

Exit Quantity

50%
```

Trailing Stop

```
2%

Applied to remaining position
```

This creates an approximate 1:2 risk/reward profile while allowing the remaining position to capture larger trends.

---

# Analyze Workspace

Once the backtest completes, open the Analyze Workspace.

Unlike a traditional trading platform, CrypAlgos allows every execution decision to be replayed and inspected.

Available tools include:

* Chart Replay
* Runtime Inspector
* Decision Trace
* Runtime Events
* Trades
* Orders
* Positions
* Variables
* Portfolio Timeline
* Performance Metrics

Rather than only displaying an equity curve, CrypAlgos explains exactly why every trade occurred.

---

# Beyond Backtesting

Once your strategy performs well in a standard backtest, continue validating it with advanced research tools.

Available workflows include:

* Walk-Forward Analysis
* Monte Carlo Simulation
* Parameter Optimization
* Strategy Versioning

These tools help evaluate robustness and reduce the risk of overfitting before deploying a strategy to live markets.

---

# Final Thoughts

Building a profitable systematic strategy is an iterative process.

Develop your idea, backtest it, inspect every decision, refine the logic, and repeat.

CrypAlgos is designed to make every stage of that workflow transparent, reproducible, and explainable.
