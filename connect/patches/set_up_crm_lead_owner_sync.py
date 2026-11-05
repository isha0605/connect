import frappe


def execute():
	"""Partners with CRM sync on get the webhook that brings Lead owner changes into Connect,
	and their team linked to its CRM users. Queued: it calls each partner's CRM."""
	for partner in frappe.get_all(
		"Partner CRM Settings", filters={"enabled": 1, "crm_reply_webhook_id": ["is", "set"]}, pluck="partner"
	):
		frappe.enqueue("connect.crm_lead_owner.set_up_owner_sync", queue="long", partner=partner)
