import frappe

# The final Starter Pack pricing. seed_starter_packs only creates missing packs, so a site
# seeded before this still has Manufacturing at 10K / 5 hours. Orders already placed keep
# the price they were sold at: each order snapshots its lines.
PRICING = {
	"accounts_sales_purchase_stock": (10000, 5),
	"manufacturing": (20000, 10),
	"hr": (10000, 5),
	"payroll": (10000, 5),
}


def execute():
	for pack_key, (price, total_hours) in PRICING.items():
		if frappe.db.exists("Starter Pack", pack_key):
			frappe.db.set_value("Starter Pack", pack_key, {"price": price, "total_hours": total_hours})
