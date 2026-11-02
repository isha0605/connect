import frappe


def execute():
	"""A partner's customers now come from the leads they win. Each lead already hired gives its
	partner the customer, Onboarding, from when they accepted; one per partner and customer."""
	frappe.db.add_unique("Partner Customer", ["partner", "customer"])

	Quote = frappe.qb.DocType("Project Quote")
	Thread = frappe.qb.DocType("Connect Thread")
	hired = (
		frappe.qb.from_(Quote)
		.join(Thread)
		.on(Thread.name == Quote.thread)
		.select(
			Quote.name, Quote.partner, Thread.customer, Quote.lead_owner, Quote.customer_project, Quote.responded_on,
			Quote.creation,
		)
		.where(Quote.status == "Hired")
		.orderby(Quote.responded_on)
		.run(as_dict=True)
	)
	for quote in hired:
		if frappe.db.exists("Partner Customer", {"partner": quote.partner, "customer": quote.customer}):
			continue
		frappe.get_doc(
			{
				"doctype": "Partner Customer",
				"partner": quote.partner,
				"customer": quote.customer,
				"stage": "Onboarding",
				"source": "Connect",
				"assigned_to": quote.lead_owner,
				"quote": quote.name,
				"project": quote.customer_project,
				"converted_on": quote.responded_on or quote.creation,
			}
		).insert(ignore_permissions=True)
