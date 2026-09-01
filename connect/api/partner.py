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
