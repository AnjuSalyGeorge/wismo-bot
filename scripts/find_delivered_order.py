from app.config import get_firestore_client

DELIVERED_STATUSES = {"delivered", "delivery_confirmed", "delivered_to_mailroom"}

def main():
    db = get_firestore_client()

    shipments_ref = db.collection("shipments")

    # Firestore queries on arrays-of-maps are limited, so we scan in batches.
    # This is fine for a seeded demo dataset (200 shipments).
    scanned = 0
    found = 0

    for doc in shipments_ref.stream():
        scanned += 1
        s = doc.to_dict() or {}
        status = (s.get("current_status") or "").lower().strip()

        if status in DELIVERED_STATUSES:
            tracking_id = s.get("tracking_id") or doc.id

            # Find an order that references this tracking_id
            order_q = (
                db.collection("orders")
                .where("tracking_id", "==", tracking_id)
                .limit(1)
                .stream()
            )
            order_doc = next(order_q, None)

            order_id = None
            email = None
            value = None
            if order_doc:
                od = order_doc.to_dict() or {}
                order_id = od.get("order_id") or order_doc.id
                email = od.get("email")
                value = od.get("value")

            print("✅ Found delivered shipment")
            print(f"  tracking_id: {tracking_id}")
            print(f"  shipment_status: {status}")
            if order_id:
                print(f"  order_id: {order_id}")
                print(f"  email: {email}")
                print(f"  value: {value}")
            else:
                print("  (No order found referencing this tracking_id)")

            found += 1
            # Stop after first match (we just need one to test)
            break

    if found == 0:
        print("❌ No delivered shipments found in Firestore.")
        print(f"Scanned {scanned} shipments. Try reseeding or adjust seed scenarios.")

if __name__ == "__main__":
    main()
