import frappe
from frappe.rate_limiter import rate_limit

# Whitelisted entry points only — the actual logic lives next to the doctype it
# belongs to (Customer, Requirement, Shortlist). Kept here as
# thin wrappers because the frontend calls these dotted paths
# (connect.api.customer.<name>) directly, and frappe.whitelist() has to
# decorate the function actually reached by that path.


@frappe.whitelist(allow_guest=True)
def get_my_customer():
	from connect.customer.doctype.customer.customer import get_my_customer
	return get_my_customer()


@frappe.whitelist(allow_guest=True)
def get_my_shortlisted_partner_names():
	from connect.customer.doctype.shortlist.shortlist import get_my_shortlisted_partner_names
	return get_my_shortlisted_partner_names()


@frappe.whitelist()
def add_to_shortlist(partner):
	from connect.customer.doctype.shortlist.shortlist import add_to_shortlist
	return add_to_shortlist(partner)


@frappe.whitelist()
def remove_from_shortlist(partner):
	from connect.customer.doctype.shortlist.shortlist import remove_from_shortlist
	return remove_from_shortlist(partner)


@frappe.whitelist()
def list_my_shortlist():
	from connect.customer.doctype.shortlist.shortlist import list_my_shortlist
	return list_my_shortlist()


@frappe.whitelist()
def get_company_details():
	from connect.customer.doctype.customer.customer import get_my_company_details
	return get_my_company_details()


@frappe.whitelist(methods=["POST"])
def save_company_details(details):
	from connect.customer.doctype.customer.customer import save_my_company_details
	return save_my_company_details(frappe.parse_json(details))


# Open to visitors without an account, so a few per hour from one address, against spam.
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=60 * 60)
def submit_enquiry(
	first_name, last_name, email, phone, company_name, designation, employees, current_software,
	industry, state, message, source=None,
):
	from connect.customer.doctype.enquiry.enquiry import submit_enquiry
	return submit_enquiry(
		{
			"first_name": first_name,
			"last_name": last_name,
			"email": email,
			"phone": phone,
			"company_name": company_name,
			"designation": designation,
			"employees": employees,
			"current_software": current_software,
			"industry": industry,
			"state": state,
			"message": message,
		},
		source=source,
	)
