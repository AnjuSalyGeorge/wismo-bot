from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    message: str
    order_id: Optional[str] = None
    email: Optional[str] = None
    session_id: str = Field(default="demo-session")


class ChatResponse(BaseModel):
    reply: str
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
    timeline: List[TrackingEvent]
