"""
Responder Agent — Generates human-like ShopWave customer replies.
"""

import asyncio
import json
from google import genai
from google.genai import types
from groq import Groq, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import GEMINI_API_KEY, GEMINI_MODEL, GROQ_API_KEY, GROQ_MODEL, USE_GROQ

google_client = genai.Client(api_key=GEMINI_API_KEY)
groq_client = Groq(api_key=GROQ_API_KEY) if USE_GROQ else None

RESPONDER_SYSTEM_PROMPT = """You are a professional, empathetic ShopWave customer support representative. Generate a reply to the customer based on the execution results.

SHOPWAVE TONE & COMMUNICATION GUIDELINES:
1. Always address the customer by their FIRST NAME
2. Be empathetic and professional — never dismissive
3. If declining a request, explain the reason clearly and offer alternatives
6. Reference specific details (order ID, product name, amounts, dates)
7. Clearly state what was done and next steps

OUTPUT FORMAT (strict JSON, no markdown):
{
    "reply": "<the customer-facing reply message>",
    "tone": "<empathetic|professional|apologetic|informative|reassuring>",
    "key_points": ["<point 1>", "<point 2>"],
    "follow_up_needed": <true|false>
}
"""

@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=3, min=8, max=120),
    retry=retry_if_exception_type(Exception),
    reraise=True
)
async def run_responder(ticket: dict, execution_result: dict, plan: dict) -> dict:
    """Generate a human-like customer reply based on execution results."""
    context = execution_result.get("context", {})
    prompt = f"TICKET:\n{json.dumps(ticket, indent=2)}\n\nCONTEXT:\n{json.dumps(context, indent=2)}"

    try:
        if USE_GROQ and groq_client:
            response = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": RESPONDER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                response_format={"type": "json_object"}
            )
            raw_text = response.choices[0].message.content
        else:
            response = google_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Content(role="user", parts=[types.Part(text=RESPONDER_SYSTEM_PROMPT)]),
                    types.Content(role="model", parts=[types.Part(text="I understand. I will generate warm ShopWave replies and return ONLY a raw JSON object.")]),
                    types.Content(role="user", parts=[types.Part(text=prompt)]),
                ],
                config=types.GenerateContentConfig(
                    temperature=0.4,
                    response_mime_type="application/json"
                )
            )
            raw_text = response.text

        val_text = raw_text.strip()
        if "```json" in val_text:
            val_text = val_text.split("```json")[-1].split("```")[0].strip()
        elif "```" in val_text:
            val_text = val_text.split("```")[-1].split("```")[0].strip()

        reply_data = json.loads(val_text)
        reply_data["_source"] = "groq_responder" if USE_GROQ else "google_responder"
        return reply_data

    except RateLimitError as e:
        wait_time = 10
        print(f"\n[RATE LIMIT]: Groq 429 — waiting {wait_time}s before retry...")
        await asyncio.sleep(wait_time)
        raise e
    except Exception as e:
        print(f"\n[RESPONDER EXCEPTION]: {str(e)}\n")
        raise e
