"""
Risk & Policy Intelligence Engine — Production-grade risk analysis for ShopWave.

Features:
- VIP customer detection and privilege application
- Fraud pattern detection (velocity, amount anomalies, repeat refunds)
- Threat/abuse detection (hostile language, social engineering)
- Customer tier-aware policy adjustments
- Risk scoring with actionable recommendations

This module runs BEFORE the executor to enrich the pipeline with risk context,
and AFTER execution to flag suspicious patterns.
"""

import re
from datetime import datetime
from typing import Any


# ═══════════════════════════════════════════════
# Risk Score Thresholds
# ═══════════════════════════════════════════════

RISK_LEVELS = {
    "low": (0, 30),
    "medium": (31, 60),
    "high": (61, 85),
    "critical": (86, 100),
}

# ═══════════════════════════════════════════════
# Fraud Signals
# ═══════════════════════════════════════════════

FRAUD_PATTERNS = {
    "high_value_refund": {
        "threshold": 500.0,
        "score": 25,
        "description": "Refund amount exceeds $500 — requires additional verification",
    },
    "repeat_refund": {
        "threshold": 2,
        "score": 35,
        "description": "Customer has multiple recent refund requests — possible abuse",
    },
    "new_account_refund": {
        "threshold": 30,  # days since first order
        "score": 20,
        "description": "Refund request from very new account",
    },
    "velocity_spike": {
        "threshold": 3,  # tickets in 24h
        "score": 30,
        "description": "Multiple tickets in short timeframe — possible automation",
    },
}

# ═══════════════════════════════════════════════
# Threat / Abuse Detection Patterns
# ═══════════════════════════════════════════════

THREAT_KEYWORDS = {
    "hostile": {
        "patterns": [
            r"\b(lawsuit|lawyer|attorney|legal\s+action|sue\s+you|court)\b",
            r"\b(scam|fraud|steal|stolen|rip\s*off|cheat)\b",
            r"\b(terrible|worst|horrible|disgusting|pathetic|incompetent)\b",
        ],
        "score": 15,
        "escalation_hint": "Customer is using hostile/threatening language",
    },
    "urgency_pressure": {
        "patterns": [
            r"\b(immediately|right\s+now|asap|urgent|emergency)\b",
            r"\b(cancel\s+everything|close\s+my\s+account|never\s+again)\b",
        ],
        "score": 10,
        "escalation_hint": "Customer expressing extreme urgency — may need priority handling",
    },
    "social_engineering": {
        "patterns": [
            r"\b(i\s+am\s+a\s+(vip|ceo|manager|director))\b",
            r"\b(my\s+friend\s+works|i\s+know\s+someone)\b",
            r"\b(override|bypass|exception|special\s+treatment)\b",
        ],
        "score": 20,
        "escalation_hint": "Possible social engineering attempt — verify customer identity",
    },
}

# ═══════════════════════════════════════════════
# VIP / Tier Policy Matrix
# ═══════════════════════════════════════════════

TIER_POLICIES = {
    3: {  # VIP tier
        "name": "VIP",
        "return_window_extension_days": 15,  # Extra 15 days beyond standard
        "max_refund_override": True,  # Can override normal refund limits
        "auto_escalation": False,  # VIPs get auto-resolved when possible
        "priority_level": "urgent",
        "courtesy_credit_eligible": True,
        "notes_check_required": True,  # Always check customer notes for VIPs
        "tone_override": "reassuring",  # Override response tone for VIPs
    },
    2: {  # Premium tier
        "name": "Premium",
        "return_window_extension_days": 7,
        "max_refund_override": False,
        "auto_escalation": False,
        "priority_level": "high",
        "courtesy_credit_eligible": True,
        "notes_check_required": True,
        "tone_override": None,
    },
    1: {  # Standard tier
        "name": "Standard",
        "return_window_extension_days": 0,
        "max_refund_override": False,
        "auto_escalation": False,
        "priority_level": "medium",
        "courtesy_credit_eligible": False,
        "notes_check_required": False,
        "tone_override": None,
    },
}


class RiskAnalysis:
    """Result of a risk analysis pass."""

    def __init__(self):
        self.risk_score: int = 0
        self.risk_level: str = "low"
        self.signals: list[dict] = []
        self.policy_adjustments: list[dict] = []
        self.recommendations: list[str] = []
        self.vip_context: dict | None = None
        self.threat_detected: bool = False
        self.fraud_flags: list[str] = []
        self.should_escalate: bool = False
        self.escalation_reason: str | None = None

    def add_signal(self, category: str, signal: str, score: int, details: str = ""):
        """Add a risk signal with scoring."""
        self.signals.append({
            "category": category,
            "signal": signal,
            "score": score,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        })
        self.risk_score = min(100, self.risk_score + score)
        self._update_level()

    def add_policy_adjustment(self, policy: str, original: str, adjusted: str, reason: str):
        """Record a policy adjustment made for this ticket."""
        self.policy_adjustments.append({
            "policy": policy,
            "original_value": original,
            "adjusted_value": adjusted,
            "reason": reason,
        })

    def _update_level(self):
        """Update risk level based on cumulative score."""
        for level, (low, high) in RISK_LEVELS.items():
            if low <= self.risk_score <= high:
                self.risk_level = level
                break

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "signals": self.signals,
            "policy_adjustments": self.policy_adjustments,
            "recommendations": self.recommendations,
            "vip_context": self.vip_context,
            "threat_detected": self.threat_detected,
            "fraud_flags": self.fraud_flags,
            "should_escalate": self.should_escalate,
            "escalation_reason": self.escalation_reason,
        }


def analyze_ticket_risk(ticket: dict, customer_context: dict | None = None) -> RiskAnalysis:
    """
    Pre-execution risk analysis — runs before the executor to enrich context.

    Args:
        ticket: The support ticket being processed
        customer_context: Optional customer data if already fetched

    Returns:
        RiskAnalysis with scores, signals, and policy adjustments
    """
    analysis = RiskAnalysis()

    # ─── 1. THREAT / ABUSE DETECTION ────────────────
    _detect_threats(analysis, ticket)

    # ─── 2. CUSTOMER TIER ANALYSIS ──────────────────
    tier = int(ticket.get("tier", 1))
    _analyze_tier(analysis, tier, customer_context)

    # ─── 3. FRAUD PATTERN DETECTION ─────────────────
    _detect_fraud_patterns(analysis, ticket, customer_context)

    # ─── 4. POLICY INTELLIGENCE ─────────────────────
    _apply_policy_intelligence(analysis, ticket, tier)

    # ─── 5. ESCALATION DECISION ─────────────────────
    if analysis.risk_score >= 70:
        analysis.should_escalate = True
        analysis.escalation_reason = (
            f"High risk score ({analysis.risk_score}/100): "
            + "; ".join([s["signal"] for s in analysis.signals[:3]])
        )
        analysis.recommendations.append(
            "ESCALATE: Risk score exceeds threshold — recommend human review"
        )

    if analysis.threat_detected:
        analysis.recommendations.append(
            "PRIORITY: Threat language detected — handle with care, consider supervisor involvement"
        )

    return analysis


def analyze_post_execution(
    analysis: RiskAnalysis,
    execution_result: dict,
    ticket: dict,
) -> RiskAnalysis:
    """
    Post-execution risk analysis — runs after execution to flag suspicious outcomes.

    Args:
        analysis: The pre-execution risk analysis
        execution_result: Result from the executor
        ticket: Original ticket

    Returns:
        Updated RiskAnalysis
    """
    context = execution_result.get("context", {})

    # Check if a refund was issued
    if context.get("refund_amount"):
        refund_amount = context["refund_amount"]
        if isinstance(refund_amount, (int, float)) and refund_amount > 500:
            analysis.add_signal(
                "fraud", "high_value_refund_processed",
                15, f"Refund of ${refund_amount:.2f} processed — flag for audit"
            )

    # Check for order amount vs refund amount mismatch
    order_amount = context.get("order_amount")
    refund_amount = context.get("refund_amount")
    if order_amount and refund_amount:
        try:
            if float(refund_amount) > float(order_amount):
                analysis.add_signal(
                    "fraud", "refund_exceeds_order",
                    40, f"Refund ${refund_amount} > Order ${order_amount}"
                )
                analysis.fraud_flags.append("REFUND_AMOUNT_MISMATCH")
        except (ValueError, TypeError):
            pass

    return analysis


# ═══════════════════════════════════════════════
# Internal Detection Functions
# ═══════════════════════════════════════════════

def _detect_threats(analysis: RiskAnalysis, ticket: dict):
    """Scan ticket text for threat/abuse patterns."""
    text = " ".join([
        ticket.get("subject", ""),
        ticket.get("body", ""),
        ticket.get("message", ""),
    ]).lower()

    for category, config in THREAT_KEYWORDS.items():
        for pattern in config["patterns"]:
            if re.search(pattern, text, re.IGNORECASE):
                analysis.add_signal(
                    "threat", category,
                    config["score"],
                    config["escalation_hint"]
                )
                analysis.threat_detected = True
                break  # One match per category is enough


def _analyze_tier(analysis: RiskAnalysis, tier: int, customer_context: dict | None):
    """Analyze customer tier and apply VIP intelligence."""
    policy = TIER_POLICIES.get(tier, TIER_POLICIES[1])

    if tier >= 2:
        analysis.vip_context = {
            "tier": tier,
            "tier_name": policy["name"],
            "privileges": {
                "extended_return_window": policy["return_window_extension_days"],
                "refund_override": policy["max_refund_override"],
                "courtesy_credit_eligible": policy["courtesy_credit_eligible"],
                "priority_level": policy["priority_level"],
            },
        }

        analysis.recommendations.append(
            f"{policy['name']} customer — apply {policy['name']}-tier privileges "
            f"(+{policy['return_window_extension_days']}d return window)"
        )

    # Check customer notes for VIPs
    if customer_context and policy["notes_check_required"]:
        notes = customer_context.get("notes", "")
        if notes:
            analysis.add_signal(
                "policy", "customer_notes_present",
                0,  # Informational, no risk score impact
                f"Customer notes: {notes[:200]}"
            )
            # Check for pre-approved exceptions
            if any(kw in notes.lower() for kw in ["pre-approved", "exception", "vip", "whitelist"]):
                analysis.add_policy_adjustment(
                    "refund_approval",
                    "standard_review",
                    "auto_approved",
                    f"Customer has pre-approved exception in notes: {notes[:100]}"
                )


def _detect_fraud_patterns(analysis: RiskAnalysis, ticket: dict, customer_context: dict | None):
    """Detect fraud patterns in the ticket context."""
    # High-value transaction check
    body = ticket.get("body", "") + " " + ticket.get("message", "")

    # Extract dollar amounts from text
    amounts = re.findall(r'\$(\d+(?:\.\d{2})?)', body)
    for amount_str in amounts:
        amount = float(amount_str)
        if amount > FRAUD_PATTERNS["high_value_refund"]["threshold"]:
            analysis.add_signal(
                "fraud", "high_value_mentioned",
                FRAUD_PATTERNS["high_value_refund"]["score"],
                f"Amount ${amount:.2f} mentioned in ticket — exceeds ${FRAUD_PATTERNS['high_value_refund']['threshold']}"
            )
            analysis.fraud_flags.append("HIGH_VALUE")

    # Repeat refund check (from customer context)
    if customer_context:
        total_orders = customer_context.get("total_orders", 0)
        total_spent = customer_context.get("total_spent", 0)

        # Very new account requesting refund
        if total_orders and total_orders <= 1:
            analysis.add_signal(
                "fraud", "new_account_activity",
                FRAUD_PATTERNS["new_account_refund"]["score"],
                f"Customer has only {total_orders} order(s) — new account flag"
            )
            analysis.fraud_flags.append("NEW_ACCOUNT")


def _apply_policy_intelligence(analysis: RiskAnalysis, ticket: dict, tier: int):
    """Apply tier-aware policy adjustments."""
    policy = TIER_POLICIES.get(tier, TIER_POLICIES[1])
    intent_keywords = ticket.get("body", "").lower() + " " + ticket.get("subject", "").lower()

    # Refund-related tickets
    if any(kw in intent_keywords for kw in ["refund", "return", "money back"]):
        if policy["return_window_extension_days"] > 0:
            analysis.add_policy_adjustment(
                "return_window",
                "30 days",
                f"{30 + policy['return_window_extension_days']} days",
                f"{policy['name']} tier gets +{policy['return_window_extension_days']} day extension"
            )

        if policy["courtesy_credit_eligible"]:
            analysis.recommendations.append(
                f"Consider offering courtesy credit if refund is denied — {policy['name']} tier eligible"
            )

    # Escalation-related
    if any(kw in intent_keywords for kw in ["warranty", "broken", "defective", "damaged"]):
        analysis.recommendations.append(
            f"Product quality issue detected — check warranty status via get_product"
        )

    # Cancellation with shipped status hint
    if "cancel" in intent_keywords:
        analysis.recommendations.append(
            "Cancellation request — verify order status is 'processing' before attempting cancel_order"
        )


def get_risk_summary_for_planner(analysis: RiskAnalysis) -> str:
    """
    Generate a concise risk context string for the planner prompt.
    This enriches the planner's awareness without overwhelming it.
    """
    parts = []

    if analysis.vip_context:
        tier_name = analysis.vip_context["tier_name"]
        parts.append(f"⚠️ {tier_name} CUSTOMER — apply {tier_name}-tier privileges")

    if analysis.threat_detected:
        parts.append("🔴 THREAT LANGUAGE DETECTED — handle with empathy, consider escalation")

    if analysis.fraud_flags:
        parts.append(f"🟡 FRAUD FLAGS: {', '.join(analysis.fraud_flags)}")

    if analysis.policy_adjustments:
        for adj in analysis.policy_adjustments:
            parts.append(f"📋 Policy: {adj['policy']} adjusted from {adj['original_value']} → {adj['adjusted_value']}")

    for rec in analysis.recommendations[:3]:  # Top 3 recommendations
        parts.append(f"💡 {rec}")

    if analysis.risk_score > 0:
        parts.append(f"📊 Risk Score: {analysis.risk_score}/100 ({analysis.risk_level})")

    return "\n".join(parts) if parts else "No risk signals detected."
