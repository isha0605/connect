import frappe

# Whitelisted entry point only; the logic lives in connect.analytics.


# Open to guests: the funnel starts before sign-up. The answer holds only Pulse's public,
# write-only ingest key.
@frappe.whitelist(allow_guest=True)
def get_config():
	from connect.analytics import get_browser_config

	return get_browser_config()
