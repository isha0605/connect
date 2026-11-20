# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""Copies the registered state of each approved application to its partner, for partners
	approved before approval copied it."""
	application = frappe.qb.DocType("Partner Application")
	partner = frappe.qb.DocType("Partner")
	rows = (
		frappe.qb.from_(application)
		.join(partner)
		.on(partner.name == application.partner)
		.select(application.partner, application.registered_state)
		.where(application.docstatus == 1)
		.where(application.status == "Approved")
		.where(application.registered_state.notnull() & (application.registered_state != ""))
		.where(partner.state.isnull() | (partner.state == ""))
	).run(as_dict=True)

	for row in rows:
		frappe.db.set_value("Partner", row.partner, "state", row.registered_state, update_modified=False)
