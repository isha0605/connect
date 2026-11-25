from frappe.model.document import Document


class IntegrationSettings(Document):
	"""Connections to the other Frappe sites Connect talks to: Press, Frappe School, Frappe Cloud and frappe.io."""

	def on_update(self):
		if self.has_value_changed("apply_tier_and_listing_changes") and self.apply_tier_and_listing_changes:
			from connect.crm_partners import queue_all_partners

			# Connect takes over from frappe.io now: Frappe's CRM gets every partner once.
			queue_all_partners()
