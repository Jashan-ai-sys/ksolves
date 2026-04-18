"""
Planner Agent — Analyzes tickets and generates execution plans for ShopWave.
"""

import asyncio
import json
from google import genai
from google.genai import types
from groq import Groq, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL, USE_GROQ

# Multi-Provider Clients
google_client = genai.Client(api_key=GEMINI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY) if USE_GROQ else None

PLANNER_SYSTEM_PROMPT = """You are an expert customer support planner for ShopWave, an e-commerce company. Your job is to analyze a customer support ticket and produce a structured execution plan.

═══════════════════════════════════════════════════════════════
AVAILABLE TOOLS — You MUST ONLY use tools from this list.
Do NOT invent, guess, or hallucinate tool names.
═══════════════════════════════════════════════════════════════

1. lookup_customer_by_email(email: str)
   → Find customer by email address. Use when ticket has email but no customer ID.

2. get_customer(customer_id: str)
   → Retrieve customer profile: name, email, tier, notes, order history, spend.

3. get_order(order_id: str)
   → Retrieve order details: status, amount, dates, return deadline, refund status.

4. get_product(product_id: str)
   → Retrieve product info: name, category, price, warranty, return window.

5. get_orders_by_customer(customer_id: str)
   → Retrieve ALL orders for a customer. Use when ticket doesn't specify an order ID.

6. check_refund_eligibility(order_id: str)
   → Check if order qualifies for refund. MUST be called BEFORE issue_refund.

7. issue_refund(order_id: str, amount: float, reason: str)
   → Process a refund. ALWAYS call check_refund_eligibility first.
   ⚠️ CRITICAL: 'amount' MUST be a NUMBER (e.g., 129.99), NOT a string reference.
   Use the exact dollar value from the order, NOT "step_2_result.amount".

8. cancel_order(order_id: str)
   → Cancel an order. Only works for orders in 'processing' status.

9. search_knowledge_base(query: str)
   → Search ShopWave KB for policies, procedures, FAQs.

10. send_reply(customer_id: str, message: str)
    → Send a reply message to a customer.

11. escalate(ticket_id: str, reason: str, priority: str, summary: str, recommended_action: str)
    → Escalate ticket to a human agent. priority must be: low|medium|high|urgent.

⚠️  THERE ARE NO OTHER TOOLS. Do not use: check_warranty, send_message,
    send_email, approve_return, verify_status, get_order_details,
    get_customer_notes, flag_ticket, check_stock, or any other name.
═══════════════════════════════════════════════════════════════

SHOPWAVE POLICY REFRESHER:
- Returns allowed within 30 days of delivery
- Refund processing time: 5-7 business days
- VIP (Tier 3): +15 day extended return window, priority handling
- Premium (Tier 2): +7 day extended return window

PLANNING RULES:
1. BE CONCISE: Avoid 'over-planning'. If a ticket requires escalation (e.g., warranty check), don't gather 5 pieces of info if 2 are enough to justify the escalation.
2. PARAMETERS: Use EXACT VALUES from the ticket when possible. For issue_refund, the 'amount' parameter MUST be a literal number (e.g., 129.99), NOT a string like "step_2_result.amount".
3. DEPENDENCIES: Ensure tool order is logical. lookup_customer_by_email -> get_order -> check_refund_eligibility -> issue_refund.
4. REFLECTION: If provided with 'execution_context', analyze why the previous plan failed and fix it specifically.
5. OUTPUT FORMAT: Raw JSON only. No markdown. No comments. No trailing commas.
6. RISK AWARENESS: If RISK INTELLIGENCE is provided below, factor it into your plan (VIP privileges, threat handling, fraud caution).

OUTPUT FORMAT (strict JSON, no markdown fences):
{
    "intent": "<refund_request|order_status|cancel_order|warranty_claim|product_info|other>",
    "confidence": <float 0.0 to 1.0>,
    "reasoning": "<detailed thoughts on why this plan was chosen>",
    "plan": [
        {
            "step": <int>,
            "tool": "<tool_name from the AVAILABLE TOOLS list above>",
            "params": { ... },
            "purpose": "<brief explanation of why this step is needed>"
        }
    ],
    "escalation_needed": <true|false>,
    "estimated_complexity": "<low|medium|high>"
}
"""

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=3, min=8, max=120),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
async def run_planner(ticket: dict, execution_context: dict | None = None, risk_context: str | None = None) -> dict:
    """Analyze a ticket and produce an execution plan with risk-aware intelligence."""
    prompt = f"TICKET DATA:\n{json.dumps(ticket, indent=2)}"

    # Inject risk intelligence if available
    if risk_context and risk_context != "No risk signals detected.":
        prompt += f"\n\nRISK INTELLIGENCE (from pre-analysis):\n{risk_context}"

    if execution_context:
        prompt += f"\n\nREFLECTION CONTEXT (PREVIOUS FAILURE):\n{json.dumps(execution_context, indent=2)}\n Please refine the plan based on this failure."

    try:
        # LLM Call
        if USE_GROQ and groq_client:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            raw_text = response.choices[0].message.content
        else:
            response = google_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=PLANNER_SYSTEM_PROMPT)]),
                    types.Content(role="model", parts=[types.Part(text="I understand. I will return ONLY a raw JSON object using ONLY the 11 tools listed.")]),
                    types.Content(role="user", parts=[types.Part(text=prompt)]),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            )
            raw_text = response.text

        # Cleanup
        val_text = raw_text.strip()
        if "```json" in val_text:
            val_text = val_text.split("```json")[-1].split("```")[0].strip()
        elif "```" in val_text:
            val_text = val_text.split("```")[-1].split("```")[0].strip()

        plan = json.loads(val_text)
        plan["_source"] = "groq_planner" if USE_GROQ else "google_planner"
        return plan

    except RateLimitError as e:
        wait_time = 10
        print(f"\n[RATE LIMIT]: Groq 429 — waiting {wait_time}s before retry...")
        await asyncio.sleep(wait_time)
        raise e
    except Exception as e:
        print(f"\n[GROQ/GENAI ERROR]: {type(e).__name__}: {str(e)}")
        if hasattr(e, 'response'):
            print(f"Response data: {e.response.text if hasattr(e.response, 'text') else e.response}")
        raise e
