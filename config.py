"""
Configuration & Constants for the Multi-Agent System.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Google Gemini Configuration
# ─────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Groq Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
USE_GROQ = os.getenv("USE_GROQ", "false").lower() == "true"

# ─────────────────────────────────────────────
# MCP Server Configuration
# ─────────────────────────────────────────────
MCP_SERVER_HOST = "127.0.0.1"
MCP_SERVER_PORT = 8100

# ─────────────────────────────────────────────
# Retry Configuration
# ─────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0        # seconds
RETRY_BACKOFF_FACTOR = 2.0    # exponential backoff multiplier
TOOL_TIMEOUT = 15.0           # seconds per tool call

# ─────────────────────────────────────────────
# Agent Configuration
# ─────────────────────────────────────────────
CONFIDENCE_THRESHOLD = 0.6    # plans below this → escalate
CONFIDENCE_WARN_THRESHOLD = 0.75  # plans below this → validator scrutiny
MAX_REFLECTION_LOOPS = 2      # max re-plan attempts on failure
MAX_CONCURRENT_TICKETS = 2    # Keep low for Groq free-tier rate limits (each ticket = 3 LLM calls)
TIER_PRIORITY = {3: 0, 2: 1, 1: 2} # Map ticket tier to priority (lower is faster)

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "hackathon_data")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
AUDIT_LOG_PATH = os.path.join(OUTPUT_DIR, "audit_log.json")
TICKETS_PATH = os.path.join(DATA_DIR, "tickets.json")
KNOWLEDGE_BASE_PATH = os.path.join(DATA_DIR, "knowledge_base.json")

# Ensure output dir exists
os.makedirs(OUTPUT_DIR, exist_ok=True)
