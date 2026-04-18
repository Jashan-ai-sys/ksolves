"""
Multi-Agent Customer Support System — ShopWave
================================================
Entry point for the agent system using official Ksolves hackathon data.

Usage:
    # Process all 20 tickets
    python main.py

    # Process a single ticket by ID
    python main.py --ticket TKT-001

    # Process with live output
    python main.py --verbose

    # Process subset (first N tickets)
    python main.py --limit 5

    # Sequential processing
    python main.py --sequential
"""

import asyncio
import json
import sys
import os
import argparse
import time
from datetime import datetime

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

from config import TICKETS_PATH, AUDIT_LOG_PATH, OUTPUT_DIR
from agent.orchestrator import process_ticket, process_tickets_concurrent, get_dead_letter_queue
from agent.audit_logger import logger


def load_tickets(path: str) -> list[dict]:
    """Load tickets from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_banner():
    """Print startup banner."""
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║       🛒 ShopWave Multi-Agent Customer Support System            ║
║       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━          ║
║       Google ADK + MCP  │  Planner → Validator → Executor        ║
║       Reflection Loop   │  Dead-Letter Queue  │  Audit Log       ║
║       Ksolves Agentic AI Hackathon 2026                          ║
╚═══════════════════════════════════════════════════════════════════╝
""")


def print_result(result: dict, verbose: bool = False):
    """Pretty-print a ticket processing result."""
    ticket_id = result.get("ticket_id", "UNKNOWN")
    success = result.get("success", False)
    intent = result.get("intent", "unknown")
    confidence = result.get("confidence", 0.0)
    loops = result.get("reflection_loops", 0)
    escalated = result.get("escalated", False)
    duration = result.get("duration_ms", 0)

    status_icon = "✅" if success else "❌"
    escalate_icon = " ⬆️ESC" if escalated else ""

    print(f"  {status_icon} {ticket_id} │ {intent:<20} │ conf: {confidence:.2f} │ "
          f"loops: {loops} │{escalate_icon} {duration:.0f}ms")

    if verbose:
        expected = result.get("expected_action", "N/A")
        print(f"     📋 Expected: {expected}")
        if result.get("response"):
            reply_preview = result['response'].replace('\n', ' ')[:150]
            print(f"     📨 Reply: {reply_preview}...")
        print()


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ShopWave Multi-Agent Customer Support System")
    parser.add_argument("--ticket", type=str, help="Process a specific ticket ID")
    parser.add_argument("--limit", type=int, help="Process only first N tickets")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--sequential", action="store_true", help="Process sequentially (not concurrent)")
    args = parser.parse_args()

    print_banner()

    # Load tickets
    tickets = load_tickets(TICKETS_PATH)
    print(f"  📋 Loaded {len(tickets)} tickets from hackathon data")

    # Filter by ticket ID if specified
    if args.ticket:
        tickets = [t for t in tickets if t["ticket_id"] == args.ticket]
        if not tickets:
            print(f"  ❌ Ticket {args.ticket} not found!")
            return
        print(f"  🎯 Processing single ticket: {args.ticket}")

    # Limit if specified
    if args.limit:
        tickets = tickets[:args.limit]
        print(f"  📊 Limited to first {args.limit} tickets")

    # Show ticket summary
    print(f"\n  {'─' * 63}")
    print(f"  Ticket Summary:")
    for t in tickets:
        tier_icon = {"1": "🟢", "2": "🟡", "3": "🔴"}.get(str(t.get("tier", 1)), "⚪")
        print(f"    {tier_icon} {t['ticket_id']} │ {t.get('subject', 'N/A')[:50]}")
    print(f"  {'─' * 63}\n")

    print(f"  ⚡ Processing {len(tickets)} ticket(s)...\n")

    start_time = time.time()

    # Process tickets
    if args.sequential or len(tickets) == 1:
        results = []
        for ticket in tickets:
            result = await process_ticket(ticket)
            results.append(result)
            print_result(result, args.verbose)
    else:
        print(f"  🔀 Running concurrently (max 5 parallel)...\n")
        results = await process_tickets_concurrent(tickets, max_concurrent=5)
        for result in results:
            print_result(result, args.verbose)

    total_time = time.time() - start_time

    # Flush audit log
    logger.flush()

    # Print summary
    print(f"\n{'═' * 67}")
    print(f"  📊 EXECUTION SUMMARY")
    print(f"{'═' * 67}")

    success_count = sum(1 for r in results if r.get("success"))
    failed_count = len(results) - success_count
    escalated_count = sum(1 for r in results if r.get("escalated"))
    avg_confidence = sum(r.get("confidence", 0) for r in results) / len(results) if results else 0
    total_loops = sum(r.get("reflection_loops", 0) for r in results)

    print(f"  Total tickets:       {len(results)}")
    print(f"  ✅ Succeeded:        {success_count}")
    print(f"  ❌ Failed:           {failed_count}")
    print(f"  ⬆️  Escalated:        {escalated_count}")
    print(f"  🔄 Reflection loops: {total_loops}")
    print(f"  📊 Avg confidence:   {avg_confidence:.2f}")
    print(f"  ⏱️  Total time:       {total_time:.1f}s")
    print(f"  📝 Audit log:        {AUDIT_LOG_PATH}")

    # Dead letter queue
    dlq = get_dead_letter_queue()
    if dlq:
        print(f"\n  ⚠️  Dead-letter queue: {len(dlq)} ticket(s)")
        for item in dlq:
            print(f"     - {item['ticket']['ticket_id']}: {item['reason'][:80]}")

    # Save results summary
    summary_path = os.path.join(OUTPUT_DIR, "results_summary.json")
    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "system": "ShopWave Multi-Agent Support System",
        "hackathon": "Ksolves Agentic AI Hackathon 2026",
        "total_tickets": len(results),
        "success_count": success_count,
        "failed_count": failed_count,
        "escalated_count": escalated_count,
        "avg_confidence": round(avg_confidence, 3),
        "total_reflection_loops": total_loops,
        "total_time_seconds": round(total_time, 2),
        "dead_letter_queue_size": len(dlq),
        "results": results,
        "dead_letter_queue": dlq,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n  📄 Full results:     {summary_path}")
    print(f"\n{'═' * 67}")
    print("  🏁 Done! — ShopWave Multi-Agent System")
    print(f"{'═' * 67}\n")


if __name__ == "__main__":
    asyncio.run(main())
