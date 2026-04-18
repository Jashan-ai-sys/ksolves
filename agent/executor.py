"""
Executor — Executes validated plans by calling MCP tools via stdio.

Features:
- Async execution of tool calls via MCP stdio protocol
- Exponential backoff retry (3 attempts)
- Timeout handling per tool call
- Context accumulation across steps
- Schema validation of tool outputs
- Error capture for audit trail
"""

import asyncio
import json
import time
from typing import Any
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from config import MAX_RETRIES, RETRY_BASE_DELAY, RETRY_BACKOFF_FACTOR, TOOL_TIMEOUT

# Fuzzy Tool Mapping for LLM Hallucinations
TOOL_ALIAS_MAP = {
    # send_reply aliases
    "send_message": "send_reply",
    "send_response": "send_reply",
    "send_email": "send_reply",
    "reply_to_customer": "send_reply",
    "reply_customer": "send_reply",
    "send_notification": "send_reply",
    "notify_customer": "send_reply",
    "compose_reply": "send_reply",
    # get_order aliases
    "get_order_details": "get_order",
    "verify_status": "get_order",
    "order_details": "get_order",
    "order_status": "get_order",
    "check_order_status": "get_order",
    "fetch_order": "get_order",
    "retrieve_order": "get_order",
    "get_order_status": "get_order",
    "get_order_info": "get_order",
    # get_customer aliases
    "get_customer_notes": "get_customer",
    "get_customer_info": "get_customer",
    "get_customer_details": "get_customer",
    "customer_info": "get_customer",
    "fetch_customer": "get_customer",
    "retrieve_customer": "get_customer",
    "get_customer_profile": "get_customer",
    # lookup_customer_by_email aliases
    "lookup_customer": "lookup_customer_by_email",
    "find_customer": "lookup_customer_by_email",
    "search_customer": "lookup_customer_by_email",
    "find_customer_by_email": "lookup_customer_by_email",
    "customer_lookup": "lookup_customer_by_email",
    "search_customer_by_email": "lookup_customer_by_email",
    # get_product aliases
    "check_warranty": "get_product",
    "get_product_info": "get_product",
    "get_product_details": "get_product",
    "product_info": "get_product",
    "check_warranty_status": "get_product",
    "get_warranty": "get_product",
    "get_warranty_info": "get_product",
    # issue_refund aliases
    "approve_return": "issue_refund",
    "process_refund": "issue_refund",
    "refund_order": "issue_refund",
    "create_refund": "issue_refund",
    "initiate_refund": "issue_refund",
    # check_refund_eligibility aliases
    "check_refund": "check_refund_eligibility",
    "refund_eligibility": "check_refund_eligibility",
    "check_eligibility": "check_refund_eligibility",
    "verify_refund_eligibility": "check_refund_eligibility",
    # cancel_order aliases
    "cancel": "cancel_order",
    "order_cancel": "cancel_order",
    "cancel_purchase": "cancel_order",
    # escalate aliases
    "issue_exchange": "escalate",
    "flag_ticket": "escalate",
    "escalate_ticket": "escalate",
    "flag_for_review": "escalate",
    "human_escalation": "escalate",
    "transfer_to_agent": "escalate",
    "escalate_to_human": "escalate",
    # search_knowledge_base aliases
    "check_stock": "search_knowledge_base",
    "search_kb": "search_knowledge_base",
    "search_faq": "search_knowledge_base",
    "search_policy": "search_knowledge_base",
    "check_policy": "search_knowledge_base",
    "lookup_policy": "search_knowledge_base",
    # get_orders_by_customer aliases
    "get_customer_orders": "get_orders_by_customer",
    "list_orders": "get_orders_by_customer",
    "customer_orders": "get_orders_by_customer",
    "find_orders": "get_orders_by_customer",
}

# Canonical valid tools
VALID_TOOLS = {
    "lookup_customer_by_email", "get_customer", "get_order", "get_product",
    "get_orders_by_customer", "check_refund_eligibility", "issue_refund",
    "cancel_order", "search_knowledge_base", "send_reply", "escalate",
}


def resolve_tool_name(tool_name: str) -> str:
    """Resolve a potentially hallucinated tool name to a valid one."""
    if tool_name in VALID_TOOLS:
        return tool_name
    if tool_name in TOOL_ALIAS_MAP:
        resolved = TOOL_ALIAS_MAP[tool_name]
        print(f"  [MAPPER]: Routing hallucinated tool '{tool_name}' → '{resolved}'")
        return resolved
    # Last resort: try case-insensitive / underscore-normalized matching
    normalized = tool_name.lower().replace("-", "_").replace(" ", "_")
    if normalized in VALID_TOOLS:
        print(f"  [MAPPER]: Normalized '{tool_name}' → '{normalized}'")
        return normalized
    if normalized in TOOL_ALIAS_MAP:
        resolved = TOOL_ALIAS_MAP[normalized]
        print(f"  [MAPPER]: Normalized+mapped '{tool_name}' → '{resolved}'")
        return resolved
    # Give up — let MCP server handle the error
    print(f"  [MAPPER]: ⚠️ UNKNOWN tool '{tool_name}' — no mapping found, passing through")
    return tool_name


class ExecutionResult:
    """Result of executing a single plan step."""
    def __init__(self, step: int, tool: str, success: bool, data: Any = None,
                 error: str | None = None, attempts: int = 1, duration_ms: float = 0):
        self.step = step
        self.tool = tool
        self.success = success
        self.data = data
        self.error = error
        self.attempts = attempts
        self.duration_ms = duration_ms

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "tool": self.tool,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "attempts": self.attempts,
            "duration_ms": round(self.duration_ms, 2)
        }


async def execute_plan(plan_steps: list[dict], server_params: StdioServerParameters) -> dict:
    """
    Execute a validated plan by calling MCP tools sequentially.
    """
    results: list[ExecutionResult] = []
    context: dict[str, Any] = {}
    overall_success = True
    failed_steps = []

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            for step_dict in plan_steps:
                step_num = step_dict.get("step", len(results) + 1)
                original_tool = step_dict.get("tool", "unknown")
                
                # Apply Fuzzy Mapping via resolve_tool_name()
                tool_name = resolve_tool_name(original_tool)
                
                params = step_dict.get("params", {})

                # Inject context values into params where referenced
                params = _resolve_context_params(params, context)

                result = await _execute_with_retry(
                    session=session,
                    step=step_num,
                    tool=tool_name,
                    params=params,
                    max_retries=MAX_RETRIES,
                )

                results.append(result)

                if result.success and result.data:
                    context[f"step_{step_num}"] = result.data
                    context[f"{tool_name}_result"] = result.data
                    _extract_context(context, tool_name, result.data)
                else:
                    overall_success = False
                    failed_steps.append({
                        "step": step_num,
                        "tool": tool_name,
                        "error": result.error
                    })

    return {
        "success": overall_success,
        "results": [r.to_dict() for r in results],
        "context": context,
        "failed_steps": failed_steps,
        "total_steps": len(plan_steps),
        "completed_steps": sum(1 for r in results if r.success)
    }


async def _execute_with_retry(session: ClientSession, step: int, tool: str,
                                params: dict, max_retries: int) -> ExecutionResult:
    """Execute a single tool call with exponential backoff retry."""
    last_error = None
    start_time = time.time()

    for attempt in range(1, max_retries + 1):
        attempt_start = time.time()
        try:
            result = await asyncio.wait_for(
                session.call_tool(tool, arguments=params),
                timeout=TOOL_TIMEOUT
            )

            duration_ms = (time.time() - attempt_start) * 1000

            if result.content:
                raw_text = ""
                for content_item in result.content:
                    if hasattr(content_item, "text"):
                        raw_text += content_item.text

                try:
                    parsed = json.loads(raw_text)
                except json.JSONDecodeError:
                    parsed = {"raw": raw_text}

                is_valid = _validate_tool_output(tool, parsed)

                if is_valid:
                    return ExecutionResult(
                        step=step, tool=tool, success=True,
                        data=parsed, attempts=attempt, duration_ms=duration_ms
                    )
                else:
                    last_error = f"Invalid response from {tool}: {json.dumps(parsed)[:200]}"
            else:
                last_error = f"Empty response from {tool}"

        except asyncio.TimeoutError:
            last_error = f"Timeout after {TOOL_TIMEOUT}s"
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)}"

        if attempt < max_retries:
            delay = RETRY_BASE_DELAY * (RETRY_BACKOFF_FACTOR ** (attempt - 1))
            await asyncio.sleep(delay)

    duration_ms = (time.time() - start_time) * 1000
    return ExecutionResult(
        step=step, tool=tool, success=False,
        error=last_error, attempts=max_retries,
        duration_ms=duration_ms
    )


def _validate_tool_output(tool: str, data: dict) -> bool:
    """Validate tool output matches expected schema."""
    if isinstance(data, dict):
        if data.get("error_code") == 500:
            return False
        if data.get("processed") == "partial":
            return False
        if data.get("sent") == "unknown":
            return False
        if data.get("escalated") == "maybe":
            return False
        if data.get("eligible") == "maybe":
            return False
        if data.get("found") == "maybe":
            return False
        if data.get("cancelled") == "unknown":
            return False
        if data.get("orders") == "error":
            return False
        if data.get("product") is None and "success" not in data:
            return False

        if "success" in data:
            return data["success"] is True

        if "error" in data and data.get("data") is None and data.get("msg"):
            return False

    return True


def _resolve_context_params(params: dict, context: dict) -> dict:
    """
    Replace context references in params with actual values from execution context.

    Handles:
    - {{mustache}} syntax: "{{customer_id}}" → "CUST-001"
    - Dynamic step references: "step_2_result.amount" → 129.99
    - Dotted path resolution: "step_1.data.customer_id" → "CUST-001"
    - LLM hallucination patterns: "CUSTOMER_ID_FROM_STEP_1" → "CUST-001"
    - Type coercion for known numeric fields (amount, price, etc.)
    """
    resolved = {}
    for key, value in params.items():
        if isinstance(value, str):
            # 1. Handle strict {{mustache}} syntax
            if "{{" in value and "}}" in value:
                for ctx_key, ctx_val in context.items():
                    tag = f"{{{{{ctx_key}}}}}"
                    if tag in value:
                        value = value.replace(tag, str(ctx_val))

            # 2. Dynamic step reference resolution (the CRITICAL FIX)
            #    Patterns: "step_2_result.amount", "step_1_result.data.customer_id"
            resolved_val = _resolve_dynamic_reference(value, context)
            if resolved_val is not None:
                value = resolved_val

            # 3. Handle LLM hallucination patterns (e.g., 'CUSTOMER_ID_FROM_STEP_1')
            if isinstance(value, str):
                upper_val = value.upper()
                if "FROM_STEP" in upper_val or ("STEP_" in upper_val and "result" not in value.lower()):
                    # Resolve Customer ID
                    if "CUSTOMER_ID" in upper_val:
                        value = str(context.get("customer_id", value))
                    # Resolve Order ID
                    elif "ORDER_ID" in upper_val:
                        value = str(context.get("order_id", value))
                    # Resolve Product ID
                    elif "PRODUCT_ID" in upper_val:
                        value = str(context.get("product_id", value))

            # 4. Type coercion for known numeric fields
            value = _coerce_type(key, value)

            resolved[key] = value
        elif isinstance(value, dict):
            resolved[key] = _resolve_context_params(value, context)
        else:
            resolved[key] = value
    return resolved


def _resolve_dynamic_reference(value: str, context: dict) -> Any:
    """
    Resolve dynamic step references to actual values from execution context.

    Supports:
    - "step_2_result.amount" → context["step_2"]["data"]["amount"] or context["step_2"]["amount"]
    - "step_1.data.customer_id" → traverses nested dicts
    - "step_3_result.eligible" → context["step_3"]["data"]["eligible"]
    - Direct context key references: "order_amount" → context["order_amount"]
    """
    if not isinstance(value, str):
        return None

    # Pattern 1: step_X_result.field (most common LLM pattern)
    match = __import__('re').match(r'^step_(\d+)_result\.(.+)$', value, __import__('re').IGNORECASE)
    if match:
        step_num = match.group(1)
        field_path = match.group(2)  # e.g., "amount" or "data.customer_id"
        step_key = f"step_{step_num}"

        step_data = context.get(step_key)
        if step_data is not None:
            resolved = _traverse_path(step_data, field_path)
            if resolved is not None:
                print(f"  [RESOLVER]: step_{step_num}_result.{field_path} → {resolved}")
                return resolved

    # Pattern 2: step_X.field
    match = __import__('re').match(r'^step_(\d+)\.(.+)$', value, __import__('re').IGNORECASE)
    if match:
        step_num = match.group(1)
        field_path = match.group(2)
        step_key = f"step_{step_num}"

        step_data = context.get(step_key)
        if step_data is not None:
            resolved = _traverse_path(step_data, field_path)
            if resolved is not None:
                print(f"  [RESOLVER]: step_{step_num}.{field_path} → {resolved}")
                return resolved

    # Pattern 3: tool_name_result.field (e.g., "get_order_result.amount")
    match = __import__('re').match(r'^(\w+)_result\.(.+)$', value, __import__('re').IGNORECASE)
    if match:
        tool_key = match.group(1) + "_result"
        field_path = match.group(2)
        tool_data = context.get(tool_key)
        if tool_data is not None:
            resolved = _traverse_path(tool_data, field_path)
            if resolved is not None:
                print(f"  [RESOLVER]: {tool_key}.{field_path} → {resolved}")
                return resolved

    # Pattern 4: Direct context key lookup (e.g., value IS a context key)
    if value in context and not value.startswith("step_"):
        resolved = context[value]
        if resolved is not None:
            print(f"  [RESOLVER]: direct key '{value}' → {resolved}")
            return resolved

    return None


def _traverse_path(data: Any, dotted_path: str) -> Any:
    """
    Traverse a nested dict/object using a dotted path.
    e.g., "data.customer_id" on {"data": {"customer_id": "C001"}} → "C001"

    Also checks the 'data' sub-key automatically (MCP tools wrap in {"success": true, "data": {...}})
    """
    parts = dotted_path.split(".")
    current = data

    for part in parts:
        if isinstance(current, dict):
            if part in current:
                current = current[part]
            elif "data" in current and isinstance(current["data"], dict):
                # Auto-unwrap MCP-style {"success": true, "data": {...}} responses
                current = current["data"].get(part)
                if current is None:
                    return None
            else:
                return None
        else:
            return None

    return current


# Known numeric parameter names — these should always be numbers, not strings
NUMERIC_PARAMS = {"amount", "price", "refund_amount", "quantity", "total", "max_amount", "credit"}


def _coerce_type(key: str, value: Any) -> Any:
    """
    Coerce parameter types based on known field semantics.
    Prevents 'unable to parse string as number' errors.
    """
    if not isinstance(value, str):
        return value

    # Numeric coercion for known fields
    if key.lower() in NUMERIC_PARAMS:
        try:
            # Remove currency symbols and commas
            clean = value.replace("$", "").replace(",", "").strip()
            if "." in clean:
                coerced = float(clean)
            else:
                coerced = int(clean)
            print(f"  [COERCE]: {key} '{value}' → {coerced} (string→number)")
            return coerced
        except (ValueError, TypeError):
            pass  # Not a number string, leave as-is

    return value


def _extract_context(context: dict, tool: str, data: dict) -> None:
    """Extract key values from tool outputs for downstream steps."""
    if not isinstance(data, dict):
        return

    inner = data.get("data", data)
    if not isinstance(inner, dict):
        # Could be a list (get_orders_by_customer)
        if isinstance(inner, list) and len(inner) > 0:
            context["customer_orders"] = inner
            # If there's only one order, extract its details
            if len(inner) == 1:
                _extract_order_context(context, inner[0])
        return

    if tool == "get_order":
        _extract_order_context(context, inner)

    elif tool in ("get_customer", "lookup_customer_by_email"):
        context["customer_id"] = inner.get("customer_id")
        context["customer_name"] = inner.get("name")
        context["customer_email"] = inner.get("email")
        context["customer_tier"] = inner.get("tier")
        context["customer_notes"] = inner.get("notes")
        context["customer_total_orders"] = inner.get("total_orders")
        context["customer_total_spent"] = inner.get("total_spent")

    elif tool == "get_product":
        context["product_name"] = inner.get("name")
        context["product_category"] = inner.get("category")
        context["warranty_months"] = inner.get("warranty_months")
        context["return_window_days"] = inner.get("return_window_days")
        context["product_returnable"] = inner.get("returnable")
        context["product_notes"] = inner.get("notes")

    elif tool == "get_orders_by_customer":
        orders = inner if isinstance(inner, list) else data.get("data", [])
        if isinstance(orders, list):
            context["customer_orders"] = orders

    elif tool == "check_refund_eligibility":
        context["refund_eligible"] = inner.get("eligible")
        context["max_refund_amount"] = inner.get("max_refund_amount")
        context["refund_reason"] = inner.get("reason")
        context["return_deadline"] = inner.get("return_deadline")
        context["within_return_window"] = inner.get("within_return_window")

    elif tool == "issue_refund":
        context["refund_id"] = inner.get("refund_id")
        context["refund_amount"] = inner.get("amount")

    elif tool == "cancel_order":
        context["order_cancelled"] = True
        context["cancel_refund_amount"] = inner.get("refund_amount")

    elif tool == "escalate":
        context["escalated"] = True
        context["escalation_id"] = inner.get("escalation_id")
        context["assigned_to"] = inner.get("assigned_to")

    elif tool == "search_knowledge_base":
        context["kb_results"] = inner.get("results", [])

    elif tool == "send_reply":
        context["reply_sent"] = True


def _extract_order_context(context: dict, order: dict) -> None:
    """Extract order-specific context."""
    context["order_id"] = order.get("order_id")
    context["order_status"] = order.get("status")
    context["order_amount"] = order.get("amount")
    context["order_date"] = order.get("order_date")
    context["delivery_date"] = order.get("delivery_date")
    context["return_deadline"] = order.get("return_deadline")
    context["refund_status"] = order.get("refund_status")
    context["order_notes"] = order.get("notes")
    context["product_id"] = order.get("product_id")
    context["customer_id_from_order"] = order.get("customer_id")
    # Enriched fields from MCP server
    if "product_name" in order:
        context["product_name"] = order.get("product_name")
    if "product_category" in order:
        context["product_category"] = order.get("product_category")
    if "warranty_months" in order:
        context["warranty_months"] = order.get("warranty_months")
