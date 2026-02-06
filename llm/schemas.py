from pydantic import BaseModel, Field
from typing import List, Optional, Literal


IntentLabel = Literal[
    "track_order",
    "delivered_not_received",
    "return_to_sender",
    "address_issue",
    "damaged",
    "delivery_attempted",
    "delayed",
    "stuck_in_transit",
    "unknown",
]

SuggestedAction = Literal["ask_followup", "proceed"]


class IntentOutput(BaseModel):
    intent: IntentLabel
    extracted_order_id: Optional[str] = None
    extracted_email: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    risk_flags: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    suggested_next_action: SuggestedAction = "proceed"
