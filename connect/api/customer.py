import frappe

# Whitelisted entry points only — the actual logic lives next to the doctype it
# belongs to (Customer, Requirement, Shortlist, Price Estimate). Kept here as
# thin wrappers because the frontend calls these dotted paths
# (connect.api.customer.<name>) directly, and frappe.whitelist() has to
# decorate the function actually reached by that path.


@frappe.whitelist(allow_guest=True)
def signup_customer(full_name, company_name, email, password):
	from connect.customer.doctype.customer.customer import signup_customer
	return signup_customer(full_name, company_name, email, password)


@frappe.whitelist(allow_guest=True)
def get_my_customer():
	from connect.customer.doctype.customer.customer import get_my_customer
	return get_my_customer()


@frappe.whitelist(allow_guest=True)
def get_pricing_view(partner, requirement=None):
	from connect.customer.doctype.price_estimate.price_estimate import get_pricing_view
	return get_pricing_view(partner, requirement=requirement)


@frappe.whitelist()
def save_price_estimate(partner, selected_addons, total, requirement=None, pack_type=None):
	from connect.customer.doctype.price_estimate.price_estimate import save_price_estimate
	return save_price_estimate(partner, selected_addons, total, requirement=requirement, pack_type=pack_type)


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
def save_customer_requirement(
	country, industry, apps=None,
	looking_for=None, company_size=None, current_situation=None, timeline=None, delivery_preference=None, budget=None,
	special_requirements=None, additional_notes=None, outcome=None,
):
	from connect.customer.doctype.requirement.requirement import save_customer_requirement
	return save_customer_requirement(
		country, industry, apps=apps, looking_for=looking_for, company_size=company_size,
		current_situation=current_situation, timeline=timeline, delivery_preference=delivery_preference,
		budget=budget, special_requirements=special_requirements, additional_notes=additional_notes,
		outcome=outcome,
	)


@frappe.whitelist(allow_guest=True)
def get_my_requirement():
	from connect.customer.doctype.requirement.requirement import get_my_requirement
	return get_my_requirement()
