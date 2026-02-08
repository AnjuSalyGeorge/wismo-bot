# app/models.py

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    message: str
    order_id: Optional[str] = None
    email: Optional[str] = None
    session_id: str = Field(default="demo-session")


class ChatResponse(BaseModel):
    # user-facing text
    reply: str

    # ✅ new (Day 6/7): LLM understanding layer outputs
    intent: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    llm_confidence: Optional[float] = None
    risk_flags: List[str] = Field(default_factory=list)

    # existing fields
    actions_taken: List[Dict[str, Any]] = Field(default_factory=list)
    case_id: Optional[str] = None


class Order(BaseModel):
    order_id: str
    email: str
    value: float
    tracking_id: str


class TrackingEvent(BaseModel):
    ts: str
    status: str
    location: Optional[str] = None


class Shipment(BaseModel):
    tracking_id: str
    carrier: str
    current_status: str
    timeline: List[TrackingEvent] = Field(default_factory=list)
