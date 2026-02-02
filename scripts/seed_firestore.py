import random
from datetime import datetime, timedelta, timezone
from google.cloud import firestore  # uses GOOGLE_APPLICATION_CREDENTIALS env var

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

def make_timeline(base: datetime, scenario: str):
    """
    scenario:
      - normal_delivered
      - stuck_in_transit
      - delivery_attempted
      - returned_to_sender
      - damaged
    """
    timeline = [
        {"ts": iso(base), "status": "label_created", "location": "Toronto"},
        {"ts": iso(base + timedelta(hours=18)), "status": "picked_up", "location": "Toronto"},
        {"ts": iso(base + timedelta(days=1, hours=8)), "status": "in_transit", "location": "Mississauga"},
    ]

    if scenario == "stuck_in_transit":
        # no further scans
        return "in_transit", timeline

    timeline.append({"ts": iso(base + timedelta(days=2, hours=9)), "status": "out_for_delivery", "location": "Windsor"})

    if scenario == "normal_delivered":
        timeline.append({"ts": iso(base + timedelta(days=2, hours=15)), "status": "delivered", "location": "Windsor"})
        return "delivered", timeline

    if scenario == "delivery_attempted":
        timeline.append({"ts": iso(base + timedelta(days=2, hours=15)), "status": "delivery_attempted", "location": "Windsor"})
        return "delivery_attempted", timeline

    if scenario == "returned_to_sender":
        timeline.append({"ts": iso(base + timedelta(days=2, hours=12)), "status": "return_initiated", "location": "Windsor"})
        timeline.append({"ts": iso(base + timedelta(days=4, hours=10)), "status": "returned_to_sender", "location": "Toronto"})
        return "returned_to_sender", timeline

    if scenario == "damaged":
        timeline.append({"ts": iso(base + timedelta(days=2, hours=13)), "status": "damaged", "location": "Windsor"})
        return "damaged", timeline

    return "unknown", timeline

def seed(n=200):
    db = firestore.Client()
    now = datetime.now(timezone.utc)

    orders_ref = db.collection("orders")
    shipments_ref = db.collection("shipments")

    # This creates a realistic distribution of cases:
    scenarios = (
        ["normal_delivered"] * 110 +
        ["stuck_in_transit"] * 35 +
        ["delivery_attempted"] * 25 +
        ["returned_to_sender"] * 15 +
        ["damaged"] * 15
    )
    random.shuffle(scenarios)

    # Ensure at least a couple known IDs exist for testing
    # A1001 -> in_transit
    # A2002 -> delivered high value
    fixed = [
        ("A1001", "T9001", "stuck_in_transit", 120.0),
        ("A2002", "T9002", "normal_delivered", 420.0),
    ]

    # Seed fixed ones first
    for order_id, tracking_id, scenario, value in fixed:
        base = now - timedelta(days=3, hours=5)
        current_status, timeline = make_timeline(base, scenario)

        orders_ref.document(order_id).set({
            "order_id": order_id,
            "email": "anju@example.com",
            "value": float(value),
            "tracking_id": tracking_id,
            "created_at": iso(base),
        })

        shipments_ref.document(tracking_id).set({
            "tracking_id": tracking_id,
            "carrier": "MockCarrier",
            "current_status": current_status,
            "timeline": timeline,
            "scenario": scenario,
            "updated_at": iso(now),
        })

    # Seed the remaining N documents (skipping the fixed ones)
    start_i = 1
    created = 0
    while created < n:
        order_num = 1000 + start_i
        order_id = f"A{order_num}"
        tracking_id = f"T{9000 + start_i}"

        # skip if it's one of the fixed IDs
        if order_id in ("A1001", "A2002"):
            start_i += 1
            continue

        scenario = scenarios[created % len(scenarios)]
        base = now - timedelta(days=random.randint(1, 10), hours=random.randint(0, 12))
        current_status, timeline = make_timeline(base, scenario)

        value = float(random.choice([49.99, 89.99, 120.0, 199.0, 249.0, 320.0, 420.0, 799.0]))

        orders_ref.document(order_id).set({
            "order_id": order_id,
            "email": "anju@example.com",
            "value": value,
            "tracking_id": tracking_id,
            "created_at": iso(base),
        })

        shipments_ref.document(tracking_id).set({
            "tracking_id": tracking_id,
            "carrier": "MockCarrier",
            "current_status": current_status,
            "timeline": timeline,
            "scenario": scenario,
            "updated_at": iso(now),
        })

        created += 1
        start_i += 1

        if created % 25 == 0:
            print(f"Seeded {created}/{n}")

    # OPTIONAL: create placeholder collections (empty) for Day 2 completeness
    db.collection("cases").document("_placeholder").set({"note": "delete_me"})
    db.collection("action_logs").document("_placeholder").set({"note": "delete_me"})

    print("✅ Firestore seeding complete.")
    print("Tip: You can delete _placeholder docs later.")

if __name__ == "__main__":
    seed(200)
