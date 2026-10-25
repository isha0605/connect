import frappe
from frappe.utils import cint, flt

# Orders placed before replace_starter_packs_with_ui_packs still hold the four retired packs,
# which the catalog no longer serves, so their Scope of work came up empty. Each moves to the
# pack that now sells the same work. A new line costs what the lines it replaces cost, so the
# order's paid amount is unchanged.
CORE_PACKS = {"accounts_sales_purchase_stock", "manufacturing"}
HR_PACKS = {"hr", "payroll"}
OLD_PACKS = CORE_PACKS | HR_PACKS


def execute():
	orders = frappe.get_all(
		"Starter Pack Order Item",
		filters={"parenttype": "Starter Pack Order", "starter_pack": ["in", list(OLD_PACKS)]},
		pluck="parent",
		distinct=True,
	)
	for order in orders:
		move_order(order)


def move_order(order):
	old_rows = frappe.get_all(
		"Starter Pack Order Item",
		filters={"parent": order, "parenttype": "Starter Pack Order"},
		fields=["name", "starter_pack", "price"],
		order_by="idx asc",
	)
	new_rows = [line for line in replacement_lines(old_rows) if line]

	# Direct writes: a placed order's validate refuses any change to its packs.
	frappe.db.delete("Starter Pack Order Item", {"name": ["in", [row.name for row in old_rows]]})
	for idx, (pack_key, price) in enumerate(new_rows, start=1):
		insert_line(order, idx, pack_key, price)

	total_hours = sum(cint(frappe.db.get_value("Starter Pack", key, "total_hours")) for key, _ in new_rows)
	frappe.db.set_value("Starter Pack Order", order, "total_hours", total_hours, update_modified=False)


def replacement_lines(old_rows):
	"""(pack_key, price) for the Core line, then the HR line. Manufacturing alone also becomes
	Core + Manufacturing, the only pack that now sells it."""
	keys = {row.starter_pack for row in old_rows}
	return [
		merged_line(old_rows, CORE_PACKS, "core-manufacturing" if "manufacturing" in keys else "core"),
		merged_line(old_rows, HR_PACKS, "hr-payroll"),
	]


def merged_line(old_rows, old_keys, new_key):
	replaced = [row for row in old_rows if row.starter_pack in old_keys]
	if not replaced:
		return None
	return new_key, sum(flt(row.price) for row in replaced)


def insert_line(order, idx, pack_key, price):
	pack = frappe.db.get_value(
		"Starter Pack", pack_key, ["pack_name", "total_hours", "delivery_days"], as_dict=True
	)
	frappe.get_doc(
		{
			"doctype": "Starter Pack Order Item",
			"parent": order,
			"parenttype": "Starter Pack Order",
			"parentfield": "packs",
			"idx": idx,
			"starter_pack": pack_key,
			"pack_name": pack.pack_name,
			"price": price,
			"total_hours": pack.total_hours,
			"delivery_days": pack.delivery_days,
		}
	).db_insert()
