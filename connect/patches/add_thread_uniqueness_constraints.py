import frappe
from frappe.query_builder import functions as fn


def execute():
	"""Adds real DB-level uniqueness constraints to back up the app's existing check-then-insert duplicate guards."""

	def add_unique_if_no_duplicates(doctype, fields):
		table = frappe.qb.DocType(doctype)
		columns = [table[f] for f in fields]
		duplicate = (
			frappe.qb.from_(table)
			.select(*columns)
			.groupby(*columns)
			.having(fn.Count("*") > 1)
			.limit(1)
		).run()
		if duplicate:
			frappe.log_error(
				title=f"add_thread_uniqueness_constraints: skipped {doctype}",
				message=f"Existing duplicate rows for {fields} on {doctype} — clean up manually, then rerun frappe.db.add_unique.",
			)
			return
		frappe.db.add_unique(doctype, fields)

	for row in frappe.get_all("Connect DM Thread", fields=["name", "user_a", "user_b"]):
		if row.user_a > row.user_b:
			frappe.db.set_value(
				"Connect DM Thread",
				row.name,
				{"user_a": row.user_b, "user_b": row.user_a},
				update_modified=False,
			)

	add_unique_if_no_duplicates("Connect Thread", ["customer", "partner"])
	add_unique_if_no_duplicates("Connect Partner Member", ["partner", "user"])
	add_unique_if_no_duplicates("Connect DM Thread", ["user_a", "user_b"])
