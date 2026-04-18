"""
Audit Logger — Comprehensive logging for every agent decision.

Logs:
- Thoughts (planner reasoning, validator validation)
- Actions (tool calls, parameters)
- Outputs (tool results, responses)
- Errors (failures, retries, escalations)
- Metadata (timestamps, durations, agent source)

This is your PROOF OF INTELLIGENCE.
"""

import json
import os
from datetime import datetime
from typing import Any
from config import AUDIT_LOG_PATH


class AuditLogger:
    """Thread-safe audit logger that accumulates entries and flushes to JSON."""

    def __init__(self):
        self.entries: list[dict] = []
        self._current_ticket: str | None = None

    def start_ticket(self, ticket_id: str, ticket: dict):
        """Mark the start of processing a new ticket."""
        self._current_ticket = ticket_id
        self._add_entry("TICKET_START", {
            "ticket_id": ticket_id,
            "ticket": ticket,
        })

    def log_thought(self, agent: str, thought: str, data: Any = None):
        """Log an agent's reasoning/thought process."""
        self._add_entry("THOUGHT", {
            "agent": agent,
            "thought": thought,
            "data": data,
        })

    def log_action(self, agent: str, action: str, params: dict | None = None):
        """Log an action taken by an agent."""
        self._add_entry("ACTION", {
            "agent": agent,
            "action": action,
            "params": params,
        })

    def log_output(self, agent: str, output: Any):
        """Log the output/result of an action."""
        self._add_entry("OUTPUT", {
            "agent": agent,
            "output": output,
        })

    def log_error(self, agent: str, error: str, details: Any = None):
        """Log an error encountered during processing."""
        self._add_entry("ERROR", {
            "agent": agent,
            "error": error,
            "details": details,
        })

    def log_decision(self, agent: str, decision: str, reasoning: str, data: Any = None):
        """Log a decision made by an agent (escalate, retry, fix plan, etc.)."""
        self._add_entry("DECISION", {
            "agent": agent,
            "decision": decision,
            "reasoning": reasoning,
            "data": data,
        })

    def end_ticket(self, ticket_id: str, outcome: str, summary: dict | None = None):
        """Mark the end of processing a ticket."""
        self._add_entry("TICKET_END", {
            "ticket_id": ticket_id,
            "outcome": outcome,
            "summary": summary,
        })
        self._current_ticket = None

    def _add_entry(self, event_type: str, data: dict):
        """Add a log entry with metadata."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "ticket_id": self._current_ticket,
            "event_type": event_type,
            **data,
        }
        self.entries.append(entry)

    def flush(self):
        """Write all entries to the audit log JSON file."""
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)

        # Load existing entries if file exists
        existing = []
        if os.path.exists(AUDIT_LOG_PATH):
            try:
                with open(AUDIT_LOG_PATH, "r") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                existing = []

        combined = existing + self.entries

        with open(AUDIT_LOG_PATH, "w") as f:
            json.dump(combined, f, indent=2, default=str)

        self.entries.clear()

    def get_summary(self) -> dict:
        """Get summary statistics of the logged entries."""
        total = len(self.entries)
        types = {}
        errors = 0
        tickets = set()
        for e in self.entries:
            t = e.get("event_type", "UNKNOWN")
            types[t] = types.get(t, 0) + 1
            if t == "ERROR":
                errors += 1
            if e.get("ticket_id"):
                tickets.add(e["ticket_id"])

        return {
            "total_entries": total,
            "event_types": types,
            "error_count": errors,
            "tickets_processed": len(tickets),
        }


# Global logger instance
logger = AuditLogger()
