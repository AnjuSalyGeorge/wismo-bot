from google.cloud import firestore

db = firestore.Client()

order = db.collection("orders").document("A2002").get()
print("Order A2002 exists:", order.exists)

if order.exists:
    od = order.to_dict()
    print("Order:", od)

    tracking_id = od["tracking_id"]
    ship = db.collection("shipments").document(tracking_id).get()
    print("Shipment", tracking_id, "exists:", ship.exists)

    if ship.exists:
        sd = ship.to_dict()
        print("Shipment status:", sd.get("current_status"))
        print("Scenario:", sd.get("scenario"))
        print("Timeline length:", len(sd.get("timeline", [])))
