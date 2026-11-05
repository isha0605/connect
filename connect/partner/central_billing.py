import re
import zlib

from connect.partner.doctype.partner_customer.partner_customer import WANTS_TO_LINK

CURRENCY = "INR"

# Demo plans and their monthly price, until the real ones come from Frappe Cloud.
DEMO_PLANS = {"Business": 9000, "Starter": 2500}


def customer_billing(records: list) -> dict[str, dict]:
	"""Each Partner Customer's Frappe Cloud sites and MRR, by record name.

	Demo data for now: Connect can't read Frappe Cloud (Central) yet. Every answer says
	is_demo, so the pages mark the numbers as not real. Takes the records together so the
	real version can ask Frappe Cloud once for all of them."""
	return {record.name: _demo_billing(record) for record in records}


def _demo_billing(record) -> dict:
	# Frappe Cloud shares a customer's sites with the partner only once the link is approved.
	if record.stage == WANTS_TO_LINK:
		return {"sites": [], "mrr": 0, "currency": CURRENCY, "is_demo": True}

	slug = re.sub(r"[^a-z0-9]+", "-", (record.customer_name or record.customer).lower()).strip("-")
	is_active = record.stage != "Churned"
	sites = [_demo_site(f"{slug}.frappe.cloud", "Business", is_active)]
	# The same customer always gets the same demo sites.
	if zlib.crc32(record.name.encode()) % 2:
		sites.append(_demo_site(f"{slug}-uat.frappe.cloud", "Starter", is_active))
	return {"sites": sites, "mrr": sum(site["amount"] for site in sites), "currency": CURRENCY, "is_demo": True}


def _demo_site(name: str, plan: str, is_active: bool) -> dict:
	return {
		"name": name,
		"plan": plan,
		"amount": DEMO_PLANS[plan] if is_active else 0,
		"currency": CURRENCY,
		"region": "Mumbai",
		"status": "Active" if is_active else "Suspended",
		"apps": ["ERPNext"],
	}
