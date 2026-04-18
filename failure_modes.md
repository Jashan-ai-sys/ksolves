# Failure Modes Documentation — ShopWave Multi-Agent System

## Overview

This document catalogs all known failure modes in the ShopWave multi-agent customer support system, their detection mechanisms, and recovery strategies. The system is **designed to fail gracefully** — failures are expected, handled, and logged.

---

## 1. Tool-Level Failures

### 1.1 Connection Timeout
- **What**: MCP tool call exceeds the 15-second timeout
- **Frequency**: ~5-8% of calls (simulated)
- **Detection**: `asyncio.TimeoutError` caught in executor
- **Recovery**: Exponential backoff retry (1s → 2s → 4s), max 3 attempts
- **If all retries fail**: Step marked as failed, reflection loop triggered
- **Log event**: `ERROR` with `timeout` details

### 1.2 Service Unavailable (503)
- **What**: MCP tool returns a 503 server error
- **Frequency**: ~3-5% of calls
- **Detection**: `ConnectionError` caught in executor
- **Recovery**: Same retry logic as timeout
- **Log event**: `ERROR` with `ConnectionError` details

### 1.3 Malformed Response
- **What**: Tool returns data that doesn't match expected schema
- **Examples**:
  - `{"error": false, "data": null, "msg": "partial response"}`
  - `{"eligible": "maybe", "amount": "unknown"}`
  - `{"processed": "partial", "refund_id": null}`
  - `{"found": "maybe", "data": null}`
- **Detection**: `_validate_tool_output()` schema check in executor
- **Recovery**: Treated as failure, triggers retry
- **Log event**: `ERROR` with `Invalid response format` message

### 1.4 Order Not Found (ORD-9999)
- **What**: Ticket references non-existent order ID (e.g., TKT-017 with ORD-9999)
- **Detection**: Tool returns `{"success": false, "error": "Order not found"}`
- **Recovery**: Agent should inform customer and ask for correct order details
- **Impact**: Tests system's ability to handle invalid input gracefully

### 1.5 Customer Not Found (unknown email)
- **What**: Ticket email not in customer database (e.g., TKT-016 with unknown.user@email.com)
- **Detection**: `lookup_customer_by_email` returns not found
- **Recovery**: Agent should ask customer for correct email/order details
- **Impact**: Tests system's identity verification flow

---

## 2. Agent-Level Failures

### 2.1 Planner: Invalid JSON Output
- **What**: Gemini returns non-JSON or malformed JSON from planner
- **Detection**: `json.JSONDecodeError` in `run_planner()`
- **Recovery**: Fallback plan generated with escalation step
- **Impact**: Ticket is escalated rather than dropped

### 2.2 Planner: Missing Required Fields
- **What**: Planner JSON missing `intent`, `confidence`, or `plan`
- **Detection**: Field validation check after parsing
- **Recovery**: `ValueError` triggers fallback escalation plan

### 2.3 Validator: LLM Failure
- **What**: Validator Gemini call fails or returns invalid JSON
- **Detection**: Exception handling in `run_validator()`
- **Recovery**: Rule-based fallback validation (`_fallback_validation()`)

### 2.4 Responder: Generation Failure
- **What**: Responder Gemini call fails
- **Detection**: Exception in `run_responder()`
- **Recovery**: Template-based fallback response (ShopWave branded)

---

## 3. Pipeline-Level Failures

### 3.1 Low Confidence Plan
- **What**: Planner confidence below threshold (0.6)
- **Detection**: Confidence check in orchestrator
- **Recovery**: Plan overridden with escalation steps
- **Log event**: `DECISION` with `ESCALATE` reason

### 3.2 Validator Plan Rejection
- **What**: Validator determines plan is unsafe or policy-violating
- **Detection**: `recommendation == "reject"` from validator
- **Recovery**: Reflection loop — planner re-plans with failure context
- **Max attempts**: 2 reflection loops
- **If exhausted**: Ticket sent to dead-letter queue

### 3.3 Execution Failure → Reflection
- **What**: One or more tool calls fail during execution
- **Detection**: `execution_result["success"] == False`
- **Recovery**: Full context (which steps failed, why) sent back to planner
- **Max loops**: 2

### 3.4 Dead-Letter Queue
- **What**: Ticket cannot be resolved after all reflection loops
- **Recovery**: Ticket stored in dead-letter queue for manual review
- **Data preserved**: Full ticket, last plan, last validation, last execution

---

## 4. ShopWave Policy Violations (Caught by Validator)

### 4.1 Refund Without Eligibility Check
- **Rule**: `issue_refund` without prior `check_refund_eligibility` → CRITICAL
- **Action**: Confidence reduced by 0.3, plan marked for fix/rejection
- **Prevents**: Unauthorized refunds

### 4.2 Expired Return Window Approval
- **Rule**: Approving return for order past `return_deadline` for standard customer
- **Detection**: Validator cross-checks dates
- **Exception**: VIP customers with pre-approved exceptions in notes

### 4.3 Social Engineering Detection
- **Rule**: Customer claims tier/policy that doesn't exist (e.g., TKT-018)
- **Detection**: Verified tier via `get_customer` vs. claimed tier
- **Action**: Flag ticket, set confidence to 0.2, decline politely

### 4.4 Wrong Cancel Status
- **Rule**: `cancel_order` for shipped/delivered orders
- **Detection**: Validator checks order status before allowing cancel
- **Action**: Must wait for delivery and return instead

### 4.5 Missing Customer Reply
- **Rule**: Plan should end with `send_reply`
- **Prevents**: "Ghost" tickets where customer never hears back

---

## 5. Ticket-Specific Edge Cases (from Hackathon Data)

| Ticket | Edge Case | Expected Handling |
|---|---|---|
| TKT-002 | Return window expired (15-day watch) | Deny return, offer alternatives |
| TKT-003 | Return expired but warranty active | Escalate as warranty claim |
| TKT-005 | VIP with pre-approved exception | Approve despite expired window |
| TKT-006 | No order ID provided | Look up by email, find order |
| TKT-009 | Refund already processed | Confirm status, advise wait time |
| TKT-013 | Expired + device registered online | Non-returnable, decline with both reasons |
| TKT-016 | Unknown customer, no order ID | Ask for verification |
| TKT-017 | Non-existent order, threatening language | Flag, respond professionally |
| TKT-018 | Social engineering (fake tier claim) | Flag, decline politely |
| TKT-020 | Completely ambiguous request | Ask clarifying questions |

---

## Failure Recovery Matrix

| Failure Type | Detection | Recovery | Worst Case |
|---|---|---|---|
| Tool timeout | `TimeoutError` | 3x retry + backoff | Step fails → reflection |
| Malformed response | Schema validation | Retry | Step fails → reflection |
| Low confidence | Threshold check | Force escalation | Human handles ticket |
| Bad plan | Validator rules | Fix or re-plan | Dead-letter queue |
| Execution failure | Result check | Reflection loop | Dead-letter queue |
| LLM failure | Exception catch | Fallback templates | Degraded but functional |
| Total failure | All loops exhausted | Dead-letter queue | Manual review required |
| Policy violation | Validator + rules | Reject + re-plan | Escalation |
| Social engineering | Tier verification | Flag + decline | Escalation to fraud team |

---

## Design Philosophy

> "A system that never fails is a system that hasn't been tested.
> A system that fails and recovers is a system that's production-ready."

Every failure mode has a handler. Every handler produces auditable output. No ticket is ever silently dropped. The dead-letter queue ensures nothing is lost, and the audit log provides complete observability into every decision.
