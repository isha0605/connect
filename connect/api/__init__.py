import frappe

# Whitelisted entry points only — the actual logic lives next to the doctype it
# belongs to (connect.utils for account/team/profile, or each doctype's own .py).
# Kept here as thin wrappers because the frontend calls these dotted paths
# (connect.api.<name>) directly, and frappe.whitelist() has to decorate the
# function actually reached by that path.


@frappe.whitelist()
def get_my_company_members():
	from connect.utils import get_my_company_members
	return get_my_company_members()


@frappe.whitelist()
def get_my_team():
	from connect.utils import get_my_team
	return get_my_team()


@frappe.whitelist()
def remove_team_member(member):
	from connect.utils import remove_team_member
	return remove_team_member(member)


@frappe.whitelist()
def add_team_member(email, role=None, password=None):
	from connect.utils import add_team_member
	return add_team_member(email, role=role, password=password)


@frappe.whitelist()
def get_my_profile():
	from connect.utils import get_my_profile
	return get_my_profile()


@frappe.whitelist()
def update_my_profile(full_name, phone=None, role=None):
	from connect.utils import update_my_profile
	return update_my_profile(full_name, phone=phone, role=role)


@frappe.whitelist()
def upload_profile_image():
	from connect.utils import upload_profile_image
	return upload_profile_image()


@frappe.whitelist(allow_guest=True)
def get_my_context():
	from connect.utils import get_my_context
	return get_my_context()


@frappe.whitelist(allow_guest=True)
def signup_customer(full_name, company_name, email, password):
	from connect.customer.doctype.customer.customer import signup_customer
	return signup_customer(full_name, company_name, email, password)


@frappe.whitelist(allow_guest=True)
def get_my_customer():
	from connect.customer.doctype.customer.customer import get_my_customer
	return get_my_customer()


@frappe.whitelist(allow_guest=True)
def search_partners(
	search=None, industry=None, product=None, region=None, delivery_mode=None, country=None,
	tier=None, business_process=None, implementation_type=None, language=None,
	min_rating=None, min_pmm_level=None, max_response_time=None,
	extra_filters=None,
	sort=None, limit=100,
):
	from connect.partner.doctype.partner.partner import search_partners
	return search_partners(
		search=search, industry=industry, product=product, region=region, delivery_mode=delivery_mode,
		country=country, tier=tier, business_process=business_process, implementation_type=implementation_type,
		language=language, min_rating=min_rating, min_pmm_level=min_pmm_level, max_response_time=max_response_time,
		extra_filters=extra_filters, sort=sort, limit=limit,
	)


@frappe.whitelist(allow_guest=True)
def count_matching_partners(answers=None):
	from connect.partner.doctype.partner.partner import count_matching_partners
	return count_matching_partners(answers=answers)


@frappe.whitelist(allow_guest=True)
def wizard_match_state(answers=None):
	from connect.partner.doctype.partner.partner import wizard_match_state
	return wizard_match_state(answers=answers)


@frappe.whitelist(allow_guest=True)
def list_matching_partners(answers=None, limit=8):
	from connect.partner.doctype.partner.partner import list_matching_partners
	return list_matching_partners(answers=answers, limit=limit)


@frappe.whitelist(allow_guest=True)
def list_partner_countries():
	from connect.partner.doctype.partner.partner import list_partner_countries
	return list_partner_countries()


@frappe.whitelist(allow_guest=True)
def list_partner_filter_options():
	from connect.partner.doctype.partner.partner import list_partner_filter_options
	return list_partner_filter_options()


@frappe.whitelist(allow_guest=True)
def get_partner_preview(partner):
	from connect.partner.doctype.partner.partner import get_partner_preview
	return get_partner_preview(partner)


@frappe.whitelist(allow_guest=True)
def get_partner_document(partner):
	from connect.partner.doctype.partner.partner import get_partner_document
	return get_partner_document(partner)


@frappe.whitelist(allow_guest=True)
def list_partner_reviews(partner):
	from connect.partner.doctype.partner_review.partner_review import list_partner_reviews
	return list_partner_reviews(partner)


@frappe.whitelist()
def get_my_review_for_partner(partner):
	from connect.partner.doctype.partner_review.partner_review import get_my_review_for_partner
	return get_my_review_for_partner(partner)


@frappe.whitelist()
def submit_partner_review(
	partner, rating, headline=None, quote=None,
	business_understanding=None, implementation_quality=None, communication=None,
	timeliness=None, support=None, technical_expertise=None,
):
	from connect.partner.doctype.partner_review.partner_review import submit_partner_review
	return submit_partner_review(
		partner, rating, headline=headline, quote=quote,
		business_understanding=business_understanding, implementation_quality=implementation_quality,
		communication=communication, timeliness=timeliness, support=support,
		technical_expertise=technical_expertise,
	)


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
