# Copyright (c) 2026
# For license information, please see license.txt

import frappe


def execute():
	"""The reply and owner webhooks now tell Connect's own emails by their Message-ID, not by
	the API user, so a partner whose CRM user is also Connect's API user gets their replies.
	Each partner's webhooks are set up again in the background: a CRM down must not stop migrate."""
	partners = frappe.get_all("Partner CRM Settings", filters={"enabled": 1, "crm_type": "Frappe CRM"}, pluck="name")
	for partner in partners:
		frappe.enqueue("connect.crm_integration.refresh_partner_webhooks", queue="long", partner=partner)
