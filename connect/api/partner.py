import frappe

# Whitelisted entry points only — the actual logic lives next to the doctype it
# belongs to (Partner, Partner Review). Kept here as thin wrappers because the
# frontend calls these dotted paths (connect.api.partner.<name>) directly, and
# frappe.whitelist() has to decorate the function actually reached by that
# path.


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
def signup_partner(full_name, company_name, email, password, country=None):
	from connect.partner.doctype.partner.partner import signup_partner
	return signup_partner(full_name, company_name, email, password, country=country)


@frappe.whitelist()
def upload_partner_logo():
	from connect.partner.doctype.partner.partner import upload_partner_logo
	return upload_partner_logo()


@frappe.whitelist()
def upload_partner_asset():
	from connect.partner.doctype.partner.partner import upload_partner_asset
	return upload_partner_asset()


@frappe.whitelist()
def update_my_partner_profile(
	partner_name=None, tagline=None, description=None, country=None, city=None,
	address=None, website=None, industry=None, year_founded=None, rollouts=None,
	hourly_rate=None, response_time_hours=None, sites_deployed=None,
	typical_project_size=None, proposal_timeline=None, certified_experts=None,
	certs_erpnext=None, certs_frappe_framework=None, countries_served=None,
	references_count=None, starter_pack=None, demo_available=None,
	logo_position_x=None, logo_position_y=None,
	apps=None, migrations=None, business_processes=None, implementation_types=None, languages=None,
	founder=None, success_stories=None, packs=None, addons=None,
):
	from connect.partner.doctype.partner.partner import update_my_partner_profile
	return update_my_partner_profile(
		partner_name=partner_name, tagline=tagline, description=description, country=country,
		city=city, address=address, website=website, industry=industry, year_founded=year_founded,
		rollouts=rollouts, hourly_rate=hourly_rate, response_time_hours=response_time_hours,
		sites_deployed=sites_deployed, typical_project_size=typical_project_size,
		proposal_timeline=proposal_timeline, certified_experts=certified_experts,
		certs_erpnext=certs_erpnext, certs_frappe_framework=certs_frappe_framework,
		countries_served=countries_served, references_count=references_count,
		starter_pack=starter_pack, demo_available=demo_available,
		logo_position_x=logo_position_x, logo_position_y=logo_position_y,
		apps=apps, migrations=migrations, business_processes=business_processes,
		implementation_types=implementation_types,
		languages=languages, founder=founder, success_stories=success_stories, packs=packs, addons=addons,
	)
