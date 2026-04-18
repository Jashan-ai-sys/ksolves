# 🛒 ShopWave Multi-Agent Customer Support System

> A production-grade, fault-tolerant multi-agent system using **Google ADK + MCP** for automated customer support ticket resolution.
> Built for the **Ksolves Agentic AI Hackathon 2026**.

## Architecture

```
Ticket → Planner Agent → Validator Agent → Executor (MCP) → Responder Agent → Audit Log
              ↑                                    |
              └──── Reflection Loop (on failure) ──┘
```

### Agent Pipeline

| Agent | Role | Model |
|---|---|---|
| **Planner** | Classifies intent, estimates confidence, generates step-by-step execution plans | Gemini 2.0 Flash |
| **Validator** | Reviews plans for safety, ShopWave policy compliance, correct ordering. Can reject/fix plans | Gemini 2.0 Flash |
| **Executor** | Runs MCP tool calls with retry logic (3x exponential backoff) | N/A (tool runner) |
| **Responder** | Generates human-like ShopWave customer replies following tone guidelines | Gemini 2.0 Flash |
| **Orchestrator** | Coordinates all agents, manages reflection loops, dead-letter queue | N/A (pipeline) |

### MCP Tools (ShopWave APIs)

| Tool | Purpose | Failure Rate |
|---|---|---|
| `lookup_customer_by_email` | Find customer by email address | 10% |
| `get_customer` | Retrieve customer profile (tier, notes, history) | 10% |
| `get_order` | Retrieve order details (status, dates, return deadline) | 12% |
| `get_product` | Retrieve product info (warranty, return window) | 8% |
| `get_orders_by_customer` | Find all orders for a customer | 10% |
| `check_refund_eligibility` | Check if order qualifies for refund | 18% |
| `issue_refund` | Process a refund | 20% |
| `cancel_order` | Cancel order (processing status only) | 10% |
| `search_knowledge_base` | Search ShopWave KB (policies, FAQs) | 5% |
| `send_reply` | Send reply to customer | 8% |
| `escalate` | Escalate to human agent with summary | 5% |

> Tools simulate real-world conditions: random timeouts, 503 errors, and malformed responses.

## Key Features

- **🔄 Reflection Loop**: On execution failure, planner re-plans with failure context (max 2 loops)
- **🛡️ Validator**: Catches unsafe plans (e.g., refund without eligibility check, social engineering)
- **📊 Confidence Calibration**: Plans below 0.6 confidence → auto-escalate
- **📬 Dead-Letter Queue**: Failed tickets preserved for manual review
- **📝 Audit Log**: Every thought, action, decision, and error logged to JSON
- **⚡ Concurrency**: `asyncio.gather()` for parallel ticket processing
- **🔁 Retry System**: 3x exponential backoff on tool failures
- **🏷️ Policy-Aware**: Understands ShopWave return windows, tier privileges, warranty rules

## Quick Start

### 1. Install Dependencies

```bash
python -m venv venv
.\venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### 2. Configure API Key

Edit `.env` and set your Google AI API key:

```
GOOGLE_API_KEY=your-actual-api-key
```

### 3. Run

```bash
# Process all 20 hackathon tickets
python main.py

# Process a single ticket
python main.py --ticket TKT-001

# Verbose output with expected actions
python main.py --verbose --limit 5

# Sequential processing
python main.py --sequential
```

## Data (Official Hackathon Data)

All data sourced from the official `ksolves/agentic_ai_hackthon_2026_sample_data` repo:

| File | Contents |
|---|---|
| `data/tickets.json` | 20 support tickets (varying complexity tiers 1-3) |
| `data/customers.json` | 10 customers (standard, premium, VIP tiers) |
| `data/orders.json` | 15 orders (processing, shipped, delivered) |
| `data/products.json` | 8 products (electronics, footwear, home, sports) |
| `data/knowledge-base.md` | ShopWave policies (returns, refunds, warranty, escalation) |

## Project Structure

```
├── agent/
│   ├── planner.py          # Intent classification + plan generation
│   ├── validator.py        # Plan validation + safety checks
│   ├── responder.py        # ShopWave customer reply generation
│   ├── executor.py         # MCP tool execution with retries
│   ├── orchestrator.py     # Pipeline coordination + reflection
│   └── audit_logger.py     # Comprehensive audit logging
├── mcp_server/
│   ├── server.py           # FastMCP server with 11 tools
│   └── schemas.py          # Pydantic models for I/O
├── data/                   # Official hackathon data
│   ├── tickets.json
│   ├── customers.json
│   ├── orders.json
│   ├── products.json
│   └── knowledge-base.md
├── output/
│   ├── audit_log.json      # Generated audit trail
│   └── results_summary.json
├── config.py               # Configuration & thresholds
├── main.py                 # Entry point
├── failure_modes.md        # Failure documentation
└── requirements.txt
```

## Design Philosophy

> "We designed a multi-agent system with a planner-validator loop, MCP-based tool execution, and a fault-tolerant orchestration layer."

1. **Fail intentionally**: MCP tools have realistic failure rates (5-20%). The agent must handle it.
2. **Validate everything**: Validator catches unsafe plans before execution.
3. **Reflect on failure**: Planner re-plans using failure context instead of giving up.
4. **Never lose data**: Dead-letter queue preserves unresolvable tickets.
5. **Log everything**: Audit trail proves the agent's intelligence and decision-making.
6. **Policy-aware**: System understands ShopWave's tiered return windows, warranty policies, and escalation guidelines.

## Tech Stack

- **Framework**: Google ADK (Agent Development Kit)
- **Tools Protocol**: MCP (Model Context Protocol) via FastMCP
- **LLM**: Google Gemini 2.0 Flash
- **Language**: Python 3.11+
- **Async**: asyncio for concurrency
- **Validation**: Pydantic for schema enforcement
