import frappe


def execute():
	"""Completing a project now needs the partner's Live mark (Customer Project.live_on). A project
	already hired by a customer the partner has at Live was marked live before the field existed."""
	Project = frappe.qb.DocType("Customer Project")
	Quote = frappe.qb.DocType("Project Quote")
	Thread = frappe.qb.DocType("Connect Thread")
	PartnerCustomer = frappe.qb.DocType("Partner Customer")
	rows = (
		frappe.qb.from_(Project)
		.join(Quote)
		.on(Quote.name == Project.hired_quote)
		.join(Thread)
		.on(Thread.name == Quote.thread)
		.join(PartnerCustomer)
		.on((PartnerCustomer.partner == Project.partner) & (PartnerCustomer.customer == Thread.customer))
		.select(Project.name, PartnerCustomer.modified)
		.where(Project.status == "Hired")
		.where(Project.live_on.isnull())
		.where(PartnerCustomer.stage == "Live")
		.run(as_dict=True)
	)
	for row in rows:
		frappe.db.set_value("Customer Project", row.name, "live_on", row.modified, update_modified=False)
