"""
Validator Agent — Reviews and validates execution plans for ShopWave.
"""

import asyncio
import json
from google import genai
from google.genai import types
from groq import Groq, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL, USE_GROQ, CONFIDENCE_THRESHOLD, CONFIDENCE_WARN_THRESHOLD

google_client = genai.Client(api_key=GEMINI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY) if USE_GROQ else None

# Canonical tool names — anything outside this set is a hallucination
VALID_TOOLS = {
    "lookup_customer_by_email", "get_customer", "get_order", "get_product",
    "get_orders_by_customer", "check_refund_eligibility", "issue_refund",
    "cancel_order", "search_knowledge_base", "send_reply", "escalate",
}

VALIDATOR_SYSTEM_PROMPT = """You are a senior ShopWave customer support plan validator. Review execution plans for safety, policy compliance, completeness, and correctness.

═══════════════════════════════════════════════════════════════
VALID TOOLS — Only these 11 tools exist in the system:
═══════════════════════════════════════════════════════════════
lookup_customer_by_email, get_customer, get_order, get_product,
get_orders_by_customer, check_refund_eligibility, issue_refund,
cancel_order, search_knowledge_base, send_reply, escalate
═══════════════════════════════════════════════════════════════

VALIDATION RULES:
1. Customer lookup (lookup_customer_by_email or get_customer) MUST come before any actions
2. get_order MUST come before check_refund_eligibility
3. check_refund_eligibility MUST come before issue_refund — NEVER skip this
4. Any tool name NOT in the valid list above is INVALID — flag it and suggest the correct tool
5. Parameters must be valid (NO PLACEHOLDERS like 'STEP_1_RESULT' or '{{customer_id}}')
6. Plan should not have redundant steps. If escalating, only gather MINIMUM necessary info.
7. VIP customers may have pre-approved exceptions — check customer notes
8. REJECT any plan that looks like it will fail due to missing dependencies.
9. JSON SAFETY: NEVER use string concatenation (like `+`) inside JSON strings. If you need dynamic references, just use a literal string like "step_2_result.amount".

If you find an INVALID tool name, replace it with the correct tool in the corrected_plan:
- check_warranty → get_product
- send_message/send_email/send_response → send_reply
- get_order_details/verify_status → get_order
- get_customer_notes/lookup_customer → lookup_customer_by_email
- approve_return → issue_refund
- flag_ticket/issue_exchange → escalate

OUTPUT FORMAT (strict JSON, no markdown):
{
    "valid": <true|false>,
    "adjusted_confidence": <float 0.0 to 1.0>,
    "issues": ["<issue 1>", "<issue 2>"],
    "fixes_applied": ["<fix 1>", "<fix 2>"],
    "corrected_plan": [<corrected plan steps if fixes were needed, null if plan is valid as-is>],
    "recommendation": "<approve|fix|reject|escalate>",
    "reasoning": "<detailed explanation>"
}
"""

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=3, min=8, max=120),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
async def run_validator(plan: dict, ticket: dict) -> dict:
    """Validate an execution plan for safety and completeness."""
    prompt = f"PLAN TO VALIDATE:\n{json.dumps(plan, indent=2)}\n\nORIGINAL TICKET:\n{json.dumps(ticket, indent=2)}"

    try:
        if USE_GROQ and groq_client:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": VALIDATOR_SYSTEM_PROMPT},
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
                    types.Content(role="user", parts=[types.Part(text=VALIDATOR_SYSTEM_PROMPT)]),
                    types.Content(role="model", parts=[types.Part(text="I understand. I will rigorously validate the ShopWave plan and return ONLY a raw JSON object.")]),
                    types.Content(role="user", parts=[types.Part(text=prompt)]),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json"
                )
            )
            raw_text = response.text

        val_text = raw_text.strip()
        if "```json" in val_text:
            val_text = val_text.split("```json")[-1].split("```")[0].strip()
        elif "```" in val_text:
            val_text = val_text.split("```")[-1].split("```")[0].strip()

        validation = json.loads(val_text)
        validation["_source"] = "groq_validator" if USE_GROQ else "google_validator"
        
        # Apply deterministic rule checks
        validation = _apply_rule_checks(validation, plan)
        return validation

    except RateLimitError as e:
        wait_time = 10
        print(f"\n[RATE LIMIT]: Groq 429 — waiting {wait_time}s before retry...")
        await asyncio.sleep(wait_time)
        raise e
    except Exception as e:
        print(f"\n[VALIDATOR EXCEPTION]: {str(e)}\n")
        raise e

def _apply_rule_checks(validation: dict, plan: dict) -> dict:
    """Apply deterministic rule checks on top of LLM validation."""
    issues = list(validation.get("issues", []))
    fixes = list(validation.get("fixes_applied", []))
    plan_steps = plan.get("plan", [])
    tool_sequence = [s.get("tool") for s in plan_steps]

    # Rule: issue_refund without check_refund_eligibility
    if "issue_refund" in tool_sequence and "check_refund_eligibility" not in tool_sequence:
        issues.append("CRITICAL: issue_refund called without check_refund_eligibility")
        validation["valid"] = False
        validation["recommendation"] = "fix"

    # Rule: No customer lookup
    if not any(t in tool_sequence for t in {"lookup_customer_by_email", "get_customer"}):
        issues.append("WARNING: No customer lookup step in plan")

    # Rule: Flag any hallucinated tool names
    for step in plan_steps:
        tool = step.get("tool", "")
        if tool and tool not in VALID_TOOLS:
            issues.append(f"INVALID TOOL: '{tool}' is not a valid tool — will be fuzzy-mapped by executor")
            validation["valid"] = False
            if validation.get("recommendation") == "approve":
                validation["recommendation"] = "fix"

    validation["issues"] = issues
    validation["fixes_applied"] = fixes
    return validation
