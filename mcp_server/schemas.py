"""
Pydantic schemas for MCP tool inputs and outputs.
Adapted for official Ksolves hackathon data schemas.
"""

from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum


# ═══════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════

class OrderStatus(str, Enum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class CustomerTier(str, Enum):
    STANDARD = "standard"
    PREMIUM = "premium"
    VIP = "vip"

class EscalationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

class TicketSource(str, Enum):
    EMAIL = "email"
    TICKET_QUEUE = "ticket_queue"


# ═══════════════════════════════════════════════
# Data Models (matching hackathon JSON schemas)
# ═══════════════════════════════════════════════

class CustomerAddress(BaseModel):
    street: str
    city: str
    state: str
    zip: str

class Customer(BaseModel):
    customer_id: str
    name: str
    email: str
    phone: str
    tier: CustomerTier
    member_since: str
    total_orders: int
    total_spent: float
    address: CustomerAddress
    notes: str

class Order(BaseModel):
    order_id: str
    customer_id: str
    product_id: str
    quantity: int
    amount: float
    status: OrderStatus
    order_date: str
    delivery_date: Optional[str] = None
    return_deadline: Optional[str] = None
    refund_status: Optional[str] = None
    notes: str

class Product(BaseModel):
    product_id: str
    name: str
    category: str
    price: float
    warranty_months: int
    return_window_days: int
    returnable: bool
    notes: str

class Ticket(BaseModel):
    ticket_id: str
    customer_email: str
    subject: str
    body: str
    source: TicketSource
    created_at: str
    tier: int = Field(ge=1, le=3, description="Complexity tier: 1=simple, 2=medium, 3=hard")
    expected_action: str


# ═══════════════════════════════════════════════
# Tool Output Models
# ═══════════════════════════════════════════════

class RefundEligibility(BaseModel):
    order_id: str
    eligible: bool
    reason: str
    order_status: Optional[str] = None
    amount: Optional[float] = None
    return_deadline: Optional[str] = None
    within_return_window: Optional[bool] = None
    customer_tier: Optional[str] = None

class RefundResult(BaseModel):
    success: bool
    refund_id: Optional[str] = None
    order_id: str
    amount: float
    message: str

class CancelResult(BaseModel):
    success: bool
    order_id: str
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    refund_amount: Optional[float] = None
    message: str

class EscalationResult(BaseModel):
    success: bool
    escalation_id: Optional[str] = None
    ticket_id: str
    assigned_to: Optional[str] = None
    priority: str
    message: str
