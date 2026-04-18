"""
MCP Server — FastMCP-based Tool Server for ShopWave Customer Support.

Uses the OFFICIAL hackathon data (customers, orders, products, knowledge base).
Simulates real-world API conditions with:
- Random failures (timeouts, 503 errors, malformed responses)
- Varying latency
- Edge cases (invalid data, missing fields)

This is INTENTIONALLY imperfect. The agent must handle it.
"""

import asyncio
import json
import random
import uuid
import os
from datetime import datetime
from mcp.server.fastmcp import FastMCP

# ═══════════════════════════════════════════════
# Server Instance
# ═══════════════════════════════════════════════

mcp = FastMCP("ShopWaveSupportTools")

# ═══════════════════════════════════════════════
# Load Hackathon Data
# ═══════════════════════════════════════════════

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hackathon_data")

def _load_json(filename: str) -> list:
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_text(filename: str) -> str:
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# Load all datasets into memory
CUSTOMERS: list[dict] = _load_json("customers.json")
ORDERS: list[dict] = _load_json("orders.json")
PRODUCTS: list[dict] = _load_json("products.json")
KNOWLEDGE_BASE_MD: str = _load_text("knowledge-base.md")

# Build lookup indexes
CUSTOMERS_BY_ID = {c["customer_id"]: c for c in CUSTOMERS}
CUSTOMERS_BY_EMAIL = {c["email"]: c for c in CUSTOMERS}
ORDERS_BY_ID = {o["order_id"]: o for o in ORDERS}
PRODUCTS_BY_ID = {p["product_id"]: p for p in PRODUCTS}

# Track state mutations
REFUND_LEDGER: dict[str, dict] = {}
CANCELLED_ORDERS: set[str] = set()
SENT_MESSAGES: list[dict] = []
ESCALATIONS: list[dict] = []


# ═══════════════════════════════════════════════
# Failure Simulation
# ═══════════════════════════════════════════════

async def maybe_fail(failure_rate: float = 0.15, tool_name: str = "unknown"):
    """Simulate random failures. This is INTENTIONAL."""
    # Random latency (50ms - 2s)
    delay = random.uniform(0.05, 2.0)
    await asyncio.sleep(delay)

    roll = random.random()
    if roll < failure_rate * 0.4:
        raise TimeoutError(f"[{tool_name}] Connection timed out after 10s")
    elif roll < failure_rate * 0.7:
        raise ConnectionError(f"[{tool_name}] Service temporarily unavailable (503)")
    elif roll < failure_rate:
        return "MALFORMED"
    return "OK"


# ═══════════════════════════════════════════════
# MCP Tools
# ═══════════════════════════════════════════════

@mcp.tool()
async def get_order(order_id: str) -> str:
    """Retrieve order details by order ID. Returns order info including status, amount, dates, return deadline, refund status, and notes."""
    result = await maybe_fail(failure_rate=0.12, tool_name="get_order")
    if result == "MALFORMED":
        return json.dumps({"error": False, "data": None, "msg": "partial response"})

    order = ORDERS_BY_ID.get(order_id)
    if not order:
        return json.dumps({"success": False, "error": f"Order {order_id} not found in system"})

    # Enrich with product info
    product = PRODUCTS_BY_ID.get(order.get("product_id", ""))
    enriched = {**order}
    if product:
        enriched["product_name"] = product["name"]
        enriched["product_category"] = product["category"]
        enriched["warranty_months"] = product["warranty_months"]
        enriched["return_window_days"] = product["return_window_days"]

    return json.dumps({"success": True, "data": enriched})


@mcp.tool()
async def get_customer(customer_id: str) -> str:
    """Retrieve customer profile by customer ID. Returns name, email, tier, notes, order history, and spend."""
    result = await maybe_fail(failure_rate=0.10, tool_name="get_customer")
    if result == "MALFORMED":
        return json.dumps({"name": None, "error_code": 500})

    customer = CUSTOMERS_BY_ID.get(customer_id)
    if not customer:
        return json.dumps({"success": False, "error": f"Customer {customer_id} not found"})

    return json.dumps({"success": True, "data": customer})


@mcp.tool()
async def lookup_customer_by_email(email: str) -> str:
    """Look up a customer using their email address. Use this when ticket has email but no customer ID."""
    result = await maybe_fail(failure_rate=0.10, tool_name="lookup_customer_by_email")
    if result == "MALFORMED":
        return json.dumps({"found": "maybe", "data": None})

    customer = CUSTOMERS_BY_EMAIL.get(email)
    if not customer:
        return json.dumps({"success": False, "error": f"No customer found with email {email}"})

    return json.dumps({"success": True, "data": customer})


@mcp.tool()
async def get_product(product_id: str) -> str:
    """Retrieve product details by product ID. Returns name, category, price, warranty, return window."""
    result = await maybe_fail(failure_rate=0.08, tool_name="get_product")
    if result == "MALFORMED":
        return json.dumps({"product": None})

    product = PRODUCTS_BY_ID.get(product_id)
    if not product:
        return json.dumps({"success": False, "error": f"Product {product_id} not found"})

    return json.dumps({"success": True, "data": product})


@mcp.tool()
async def get_orders_by_customer(customer_id: str) -> str:
    """Retrieve all orders for a given customer ID. Useful when ticket doesn't specify an order ID."""
    result = await maybe_fail(failure_rate=0.10, tool_name="get_orders_by_customer")
    if result == "MALFORMED":
        return json.dumps({"orders": "error"})

    customer_orders = [o for o in ORDERS if o["customer_id"] == customer_id]
    if not customer_orders:
        return json.dumps({"success": False, "error": f"No orders found for customer {customer_id}"})

    return json.dumps({"success": True, "data": customer_orders, "count": len(customer_orders)})


@mcp.tool()
async def check_refund_eligibility(order_id: str) -> str:
    """Check if an order is eligible for a refund. Evaluates return window, order status, refund history, and product policy. MUST be called before issue_refund."""
    result = await maybe_fail(failure_rate=0.18, tool_name="check_refund_eligibility")
    if result == "MALFORMED":
        return json.dumps({"eligible": "maybe", "amount": "unknown"})

    order = ORDERS_BY_ID.get(order_id)
    if not order:
        return json.dumps({"success": False, "error": f"Order {order_id} not found"})

    # Already refunded?
    if order.get("refund_status") == "refunded":
        return json.dumps({
            "success": True,
            "data": {
                "order_id": order_id,
                "eligible": False,
                "reason": "Refund already processed for this order",
                "refund_status": "already_refunded"
            }
        })

    # Also check our runtime ledger
    if order_id in REFUND_LEDGER:
        return json.dumps({
            "success": True,
            "data": {
                "order_id": order_id,
                "eligible": False,
                "reason": "Refund already processed during this session",
                "refund_status": "already_refunded"
            }
        })

    product = PRODUCTS_BY_ID.get(order.get("product_id", ""))
    customer = CUSTOMERS_BY_ID.get(order.get("customer_id", ""))

    # Check return deadline
    return_deadline = order.get("return_deadline")
    ticket_date = "2024-03-15"  # Approximate ticket processing date

    within_window = True
    if return_deadline:
        within_window = ticket_date <= return_deadline

    # Check if order is in returnable status
    status = order.get("status", "")

    response_data = {
        "order_id": order_id,
        "order_status": status,
        "amount": order.get("amount"),
        "return_deadline": return_deadline,
        "within_return_window": within_window,
        "product_returnable": product.get("returnable", True) if product else True,
        "customer_tier": customer.get("tier", "standard") if customer else "standard",
        "customer_notes": customer.get("notes", "") if customer else "",
        "order_notes": order.get("notes", ""),
    }

    if status in ("delivered",) and within_window:
        response_data["eligible"] = True
        response_data["reason"] = "Within return window, order delivered"
        response_data["max_refund_amount"] = order.get("amount")
    elif status == "processing":
        response_data["eligible"] = True
        response_data["reason"] = "Order still processing — can cancel for full refund"
        response_data["max_refund_amount"] = order.get("amount")
    elif status == "shipped":
        response_data["eligible"] = False
        response_data["reason"] = "Order is shipped — must wait for delivery then return"
    elif not within_window:
        response_data["eligible"] = False
        response_data["reason"] = f"Return window expired (deadline: {return_deadline})"
    else:
        response_data["eligible"] = False
        response_data["reason"] = f"Order status '{status}' not eligible for refund"

    return json.dumps({"success": True, "data": response_data})


@mcp.tool()
async def issue_refund(order_id: str, amount: float, reason: str) -> str:
    """Process a refund for an order. Requires order_id, amount, and reason. ALWAYS call check_refund_eligibility first."""
    result = await maybe_fail(failure_rate=0.20, tool_name="issue_refund")
    if result == "MALFORMED":
        return json.dumps({"processed": "partial", "refund_id": None})

    order = ORDERS_BY_ID.get(order_id)
    if not order:
        return json.dumps({"success": False, "error": f"Order {order_id} not found"})

    if amount > order.get("amount", 0):
        return json.dumps({"success": False, "error": f"Refund amount ${amount} exceeds order amount ${order['amount']}"})

    if order_id in REFUND_LEDGER or order.get("refund_status") == "refunded":
        return json.dumps({"success": False, "error": "Refund already processed for this order"})

    refund_id = f"REF-{uuid.uuid4().hex[:8].upper()}"
    REFUND_LEDGER[order_id] = {
        "refund_id": refund_id,
        "amount": amount,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    }

    return json.dumps({
        "success": True,
        "data": {
            "refund_id": refund_id,
            "order_id": order_id,
            "amount": amount,
            "message": f"Refund of ${amount:.2f} processed successfully. Expect 5-7 business days for bank processing."
        }
    })


@mcp.tool()
async def cancel_order(order_id: str) -> str:
    """Cancel an order. Only works for orders in 'processing' status (not yet shipped)."""
    result = await maybe_fail(failure_rate=0.10, tool_name="cancel_order")
    if result == "MALFORMED":
        return json.dumps({"cancelled": "unknown"})

    order = ORDERS_BY_ID.get(order_id)
    if not order:
        return json.dumps({"success": False, "error": f"Order {order_id} not found"})

    if order_id in CANCELLED_ORDERS:
        return json.dumps({"success": False, "error": "Order already cancelled"})

    status = order.get("status", "")
    if status == "processing":
        CANCELLED_ORDERS.add(order_id)
        return json.dumps({
            "success": True,
            "data": {
                "order_id": order_id,
                "previous_status": status,
                "new_status": "cancelled",
                "refund_amount": order.get("amount"),
                "message": f"Order {order_id} cancelled. Refund of ${order.get('amount', 0):.2f} will be processed within 3-5 business days."
            }
        })
    elif status == "shipped":
        return json.dumps({
            "success": False,
            "error": f"Cannot cancel — order already shipped. Customer must wait for delivery and initiate a return."
        })
    elif status == "delivered":
        return json.dumps({
            "success": False,
            "error": f"Cannot cancel — order already delivered. Customer should initiate a return instead."
        })
    else:
        return json.dumps({
            "success": False,
            "error": f"Cannot cancel order with status '{status}'"
        })


@mcp.tool()
async def send_reply(customer_id: str, message: str) -> str:
    """Send a reply message to a customer. Requires customer_id and the message content."""
    result = await maybe_fail(failure_rate=0.08, tool_name="send_reply")
    if result == "MALFORMED":
        return json.dumps({"sent": "unknown", "id": None})

    customer = CUSTOMERS_BY_ID.get(customer_id)
    if not customer:
        return json.dumps({"success": False, "error": f"Customer {customer_id} not found"})

    message_id = f"MSG-{uuid.uuid4().hex[:8].upper()}"
    SENT_MESSAGES.append({
        "message_id": message_id,
        "customer_id": customer_id,
        "customer_name": customer["name"],
        "email": customer["email"],
        "message": message,
        "timestamp": datetime.now().isoformat()
    })

    return json.dumps({
        "success": True,
        "data": {
            "message_id": message_id,
            "customer_id": customer_id,
            "sent_to": f"{customer['name']} ({customer['email']})",
            "message": f"Reply sent successfully to {customer['name']}"
        }
    })


@mcp.tool()
async def escalate(ticket_id: str, reason: str, priority: str = "medium", summary: str = "", recommended_action: str = "") -> str:
    """Escalate a ticket to a human agent. Include summary of what was attempted and recommended action."""
    result = await maybe_fail(failure_rate=0.05, tool_name="escalate")
    if result == "MALFORMED":
        return json.dumps({"escalated": "maybe"})

    valid_priorities = ["low", "medium", "high", "urgent"]
    if priority not in valid_priorities:
        priority = "medium"

    escalation_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
    assigned_agents = ["Agent Sarah", "Agent Mike", "Supervisor Lisa", "Warranty Team", "Specialist Tom"]
    assigned = random.choice(assigned_agents)

    ESCALATIONS.append({
        "escalation_id": escalation_id,
        "ticket_id": ticket_id,
        "reason": reason,
        "summary": summary,
        "recommended_action": recommended_action,
        "priority": priority,
        "assigned_to": assigned,
        "timestamp": datetime.now().isoformat()
    })

    return json.dumps({
        "success": True,
        "data": {
            "escalation_id": escalation_id,
            "ticket_id": ticket_id,
            "assigned_to": assigned,
            "priority": priority,
            "message": f"Ticket escalated with {priority} priority. Assigned to {assigned}."
        }
    })


@mcp.tool()
async def search_knowledge_base(query: str) -> str:
    """Search the ShopWave internal knowledge base for policies, procedures, and FAQs. Contains return policy, refund policy, warranty, cancellation, exchange, tier privileges, and escalation guidelines."""
    result = await maybe_fail(failure_rate=0.05, tool_name="search_knowledge_base")
    if result == "MALFORMED":
        return json.dumps({"results": []})

    # Parse the markdown KB into sections
    sections = []
    current_section = {"title": "", "content": ""}
    for line in KNOWLEDGE_BASE_MD.split("\n"):
        if line.startswith("## "):
            if current_section["title"]:
                sections.append(current_section)
            current_section = {"title": line.strip("# ").strip(), "content": ""}
        else:
            current_section["content"] += line + "\n"
    if current_section["title"]:
        sections.append(current_section)

    # Keyword matching
    query_lower = query.lower()
    matches = []
    for section in sections:
        score = 0
        title_lower = section["title"].lower()
        content_lower = section["content"].lower()
        for word in query_lower.split():
            if len(word) < 3:
                continue
            if word in title_lower:
                score += 5
            if word in content_lower:
                score += content_lower.count(word)
        if score > 0:
            matches.append({**section, "_score": score})

    matches.sort(key=lambda x: x["_score"], reverse=True)
    for m in matches:
        del m["_score"]

    return json.dumps({
        "success": True,
        "data": {
            "query": query,
            "results": matches[:3],
            "total_found": len(matches)
        }
    })


# ═══════════════════════════════════════════════
# Server Entry Point
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    print("Starting ShopWave MCP Support Tools Server...")
    mcp.run()
