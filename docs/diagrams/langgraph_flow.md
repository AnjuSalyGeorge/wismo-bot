## LangGraph Flow (Node-level)

[intake]
  - load session from Firestore
  - append user message to session history

[understand]
  - infer intent (LLM_MODE=local via Ollama OR stub)
  - extract order_id/email
  - reuse last_intent for follow-up messages if needed
  - if missing order_id/email -> ask follow-up and stop

[retrieve]
  - get_order(order_id, email)
  - get_tracking(tracking_id)
  - store confirmed order/email in session

[decide]
  - diagnose issue from message + shipment status
  - apply policy rules (recommended_action)
  - handle special flows:
      - delivery_attempted -> ask access questions
      - damaged -> ask damage questions
      - returned_to_sender -> verify address prompt
      - repeat claims -> escalate + create/reuse case
  - log actions + update session/case_id
