import frappe


def execute():
	"""A partner's one address becomes their first office, then the old column goes."""
	if not frappe.db.has_column("Partner", "address"):
		return

	partner = frappe.qb.DocType("Partner")
	rows = (
		frappe.qb.from_(partner)
		.select(partner.name, partner.address, partner.city, partner.country)
		.where(partner.address.isnotnull() & (partner.address != ""))
		.run(as_dict=True)
	)
	for row in rows:
		if frappe.db.exists("Partner Office", {"parent": row.name, "parenttype": "Partner"}):
			continue
		frappe.get_doc(
			{
				"doctype": "Partner Office",
				"parent": row.name,
				"parenttype": "Partner",
				"parentfield": "offices",
				"idx": 1,
				# the office needs a city; a partner without one has at least a country
				"city": row.city or row.country,
				"address": row.address.strip(),
			}
		).db_insert()

	frappe.db.sql_ddl("alter table `tabPartner` drop column `address`")
