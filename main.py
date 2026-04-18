"""
Multi-Agent Customer Support System — ShopWave
================================================
Entry point for the agent system using official Ksolves hackathon data.

Usage:
    # Process all 20 tickets (rate-limit safe batches)
    python main.py

    # Process a single ticket by ID
    python main.py --ticket TKT-001

    # Process with live output
    python main.py --verbose

    # Process subset (first N tickets)
    python main.py --limit 5

    # Sequential processing (safest for rate limits)
    python main.py --sequential

    # Custom batch size and delay (default: 4 tickets per batch, 30s between)
    python main.py --batch-size 3 --batch-delay 45

    # Resume from a specific ticket (skip first N)
    python main.py --skip 10
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
║       🛒 ShopWave Multi-Agent Customer Support System v2.0       ║
║       ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━          ║
║       MCP + LLM  │  Risk → Planner → Validator → Executor        ║
║       Reflection Loop  │  Dynamic Resolution │  Risk Intel        ║
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
    
    # Risk badge
    risk = result.get("risk_analysis", {})
    risk_level = risk.get("risk_level", "low") if risk else "low"
    risk_score = risk.get("risk_score", 0) if risk else 0
    risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "🔴"}.get(risk_level, "⚪")

    print(f"  {status_icon} {ticket_id} │ {intent:<20} │ conf: {confidence:.2f} │ "
          f"loops: {loops} │ risk: {risk_icon}{risk_score:>3} │{escalate_icon} {duration:.0f}ms")

    if verbose:
        expected = result.get("expected_action", "N/A")
        print(f"     📋 Expected: {expected}")
        if risk and risk.get("fraud_flags"):
            print(f"     🚨 Fraud flags: {risk['fraud_flags']}")
        if risk and risk.get("threat_detected"):
            print(f"     ⚠️  Threat language detected")
        if result.get("response"):
            reply_preview = result['response'].replace('\n', ' ')[:150]
            print(f"     📨 Reply: {reply_preview}...")
        print()


def load_existing_results(summary_path: str) -> list[dict]:
    """Load existing results from a previous run (for resume/append mode)."""
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("results", [])
        except (json.JSONDecodeError, KeyError):
            return []
    return []


async def process_batch_with_rate_limit(
    tickets: list[dict],
    batch_size: int,
    batch_delay: float,
    verbose: bool,
    sequential: bool,
) -> list[dict]:
    """
    Process tickets in rate-limit-safe batches.
    
    This is a production-grade pattern:
    - Process `batch_size` tickets concurrently
    - Wait `batch_delay` seconds between batches
    - Flush audit log after each batch
    - Print progress with batch indicators
    """
    all_results = []
    total_batches = (len(tickets) + batch_size - 1) // batch_size
    
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(tickets))
        batch = tickets[start_idx:end_idx]
        
        print(f"\n  {'━' * 63}")
        print(f"  📦 Batch {batch_num + 1}/{total_batches} "
              f"({len(batch)} tickets: {batch[0]['ticket_id']} → {batch[-1]['ticket_id']})")
        print(f"  {'━' * 63}\n")
        
        if sequential or len(batch) == 1:
            for ticket in batch:
                result = await process_ticket(ticket)
                all_results.append(result)
                print_result(result, verbose)
        else:
            batch_results = await process_tickets_concurrent(batch, max_concurrent=len(batch))
            for result in batch_results:
                print_result(result, verbose)
            all_results.extend(batch_results)
        
        # Flush audit log after each batch (safety: don't lose data on crash)
        logger.flush()
        print(f"  💾 Batch {batch_num + 1} complete — audit log flushed")
        
        # Rate limit cooldown between batches (skip after last batch)
        if batch_num < total_batches - 1:
            print(f"  ⏳ Rate limit cooldown: {batch_delay:.0f}s before next batch...")
            await asyncio.sleep(batch_delay)
    
    return all_results


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ShopWave Multi-Agent Customer Support System")
    parser.add_argument("--ticket", type=str, help="Process a specific ticket ID")
    parser.add_argument("--limit", type=int, help="Process only first N tickets")
    parser.add_argument("--skip", type=int, default=0, help="Skip first N tickets (for resume)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--sequential", action="store_true", help="Process sequentially (not concurrent)")
    parser.add_argument("--batch-size", type=int, default=4, help="Tickets per batch (default: 4)")
    parser.add_argument("--batch-delay", type=float, default=30.0, help="Seconds between batches (default: 30)")
    parser.add_argument("--fresh", action="store_true", help="Clear audit log before run")
    args = parser.parse_args()

    print_banner()

    # Optionally clear previous audit log
    if args.fresh and os.path.exists(AUDIT_LOG_PATH):
        os.remove(AUDIT_LOG_PATH)
        print("  🗑️  Cleared previous audit log (--fresh mode)")

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

    # Skip N tickets (for resuming)
    if args.skip > 0:
        tickets = tickets[args.skip:]
        print(f"  ⏭️  Skipped first {args.skip} tickets (resume mode)")

    # Limit if specified
    if args.limit:
        tickets = tickets[:args.limit]
        print(f"  📊 Limited to {args.limit} tickets")

    if not tickets:
        print("  ❌ No tickets to process!")
        return

    # Show ticket summary
    print(f"\n  {'─' * 63}")
    print(f"  Ticket Summary:")
    for t in tickets:
        tier_icon = {"1": "🟢", "2": "🟡", "3": "🔴"}.get(str(t.get("tier", 1)), "⚪")
        print(f"    {tier_icon} {t['ticket_id']} │ {t.get('subject', 'N/A')[:50]}")
    print(f"  {'─' * 63}\n")

    print(f"  ⚡ Processing {len(tickets)} ticket(s)...\n")
    print(f"  📦 Batch config: {args.batch_size} per batch, {args.batch_delay:.0f}s cooldown")
    print(f"  🔧 Mode: {'sequential' if args.sequential else 'concurrent'}\n")

    start_time = time.time()

    # Process tickets in rate-limit-safe batches
    if len(tickets) == 1:
        # Single ticket — no batching needed
        result = await process_ticket(tickets[0])
        results = [result]
        print_result(result, args.verbose)
        logger.flush()
    else:
        results = await process_batch_with_rate_limit(
            tickets=tickets,
            batch_size=args.batch_size,
            batch_delay=args.batch_delay,
            verbose=args.verbose,
            sequential=args.sequential,
        )

    total_time = time.time() - start_time

    # Final flush
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
    
    # Risk stats
    risk_alerts = sum(1 for r in results if r.get("risk_analysis", {}).get("risk_score", 0) > 30)
    threats = sum(1 for r in results if r.get("risk_analysis", {}).get("threat_detected", False))
    vip_count = sum(1 for r in results if r.get("risk_analysis", {}).get("vip_context") is not None)

    print(f"  Total tickets:       {len(results)}")
    print(f"  ✅ Succeeded:        {success_count}")
    print(f"  ❌ Failed:           {failed_count}")
    print(f"  ⬆️  Escalated:        {escalated_count}")
    print(f"  🔄 Reflection loops: {total_loops}")
    print(f"  📊 Avg confidence:   {avg_confidence:.2f}")
    print(f"  ⏱️  Total time:       {total_time:.1f}s")
    print(f"  📝 Audit log:        {AUDIT_LOG_PATH}")
    print(f"\n  🛡️  Risk Intelligence:")
    print(f"     Risk alerts:      {risk_alerts}")
    print(f"     Threats detected: {threats}")
    print(f"     VIP tickets:      {vip_count}")

    # Dead letter queue
    dlq = get_dead_letter_queue()
    if dlq:
        print(f"\n  ⚠️  Dead-letter queue: {len(dlq)} ticket(s)")
        for item in dlq:
            print(f"     - {item['ticket']['ticket_id']}: {item['reason'][:80]}")

    # Save results summary
    summary_path = os.path.join(OUTPUT_DIR, "results_summary.json")
    
    # Merge with existing results if appending
    existing_results = load_existing_results(summary_path) if not args.fresh else []
    existing_ids = {r.get("ticket_id") for r in existing_results}
    new_results = [r for r in results if r.get("ticket_id") not in existing_ids]
    combined_results = existing_results + new_results
    
    combined_success = sum(1 for r in combined_results if r.get("success"))
    combined_avg_conf = sum(r.get("confidence", 0) for r in combined_results) / len(combined_results) if combined_results else 0
    
    summary = {
        "run_timestamp": datetime.now().isoformat(),
        "system": "ShopWave Multi-Agent Support System v2.0",
        "hackathon": "Ksolves Agentic AI Hackathon 2026",
        "total_tickets": len(combined_results),
        "success_count": combined_success,
        "failed_count": len(combined_results) - combined_success,
        "escalated_count": sum(1 for r in combined_results if r.get("escalated")),
        "avg_confidence": round(combined_avg_conf, 3),
        "total_reflection_loops": sum(r.get("reflection_loops", 0) for r in combined_results),
        "total_time_seconds": round(total_time, 2),
        "dead_letter_queue_size": len(dlq),
        "risk_intelligence": {
            "risk_alerts": sum(1 for r in combined_results if r.get("risk_analysis", {}).get("risk_score", 0) > 30),
            "threats_detected": sum(1 for r in combined_results if r.get("risk_analysis", {}).get("threat_detected", False)),
            "vip_tickets": sum(1 for r in combined_results if r.get("risk_analysis", {}).get("vip_context") is not None),
        },
        "batch_config": {
            "batch_size": args.batch_size,
            "batch_delay": args.batch_delay,
            "mode": "sequential" if args.sequential else "concurrent",
        },
        "results": combined_results,
        "dead_letter_queue": dlq,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    if len(combined_results) > len(results):
        print(f"\n  📎 Merged with previous run: {len(combined_results)} total tickets")
    
    print(f"\n  📄 Full results:     {summary_path}")
    print(f"\n{'═' * 67}")
    print("  🏁 Done! — ShopWave Multi-Agent System v2.0")
    print(f"{'═' * 67}\n")


if __name__ == "__main__":
    asyncio.run(main())
