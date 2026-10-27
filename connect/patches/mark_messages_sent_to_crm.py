import frappe
from frappe.query_builder.functions import IfNull

from connect.crm_integration import SENT_BEFORE_TRACKING


def execute():
	"""Threads already in a partner's CRM sent their messages before Connect noted which ones it
	sent. Marks those as sent, so the CRM sync doesn't send them all again."""
	threads = frappe.get_all("Connect Thread", filters={"crm_lead_id": ["is", "set"]}, pluck="name")
	if not threads:
		return

	Message = frappe.qb.DocType("Connect Message")
	(
		frappe.qb.update(Message)
		.set(Message.crm_communication, SENT_BEFORE_TRACKING)
		.where(Message.thread.isin(threads))
		.where(IfNull(Message.crm_communication, "") == "")
		.where(IfNull(Message.crm_source_communication, "") == "")
	).run()
