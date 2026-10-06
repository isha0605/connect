import frappe


def execute():
	"""A customer can now have one thread with Frappe per Starter Pack consultant, so the
	(customer, partner) unique index becomes (customer, partner, consultant).

	Threads without a consultant (Contact Partner) store it as NULL, which a unique index
	doesn't compare, so for those the duplicate check in Connect Thread.validate is the guard."""
	table = "tabConnect Thread"
	indexes = {row.Key_name for row in frappe.db.sql(f"show index from `{table}`", as_dict=True)}
	if "unique_customer_partner" in indexes:
		frappe.db.sql_ddl(f"alter table `{table}` drop index `unique_customer_partner`")
	if "unique_customer_partner_consultant" not in indexes:
		frappe.db.add_unique("Connect Thread", ["customer", "partner", "consultant"])
