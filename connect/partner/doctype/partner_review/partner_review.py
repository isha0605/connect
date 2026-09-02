# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint, get_fullname, nowdate

from connect.customer.doctype.customer.customer import get_customer_for_user
from connect.partner.doctype.partner.partner import recompute_rating_from_reviews


class PartnerReview(Document):
	def after_insert(self):
		recompute_rating_from_reviews(self.partner)

	def on_update(self):
		recompute_rating_from_reviews(self.partner)

	def on_trash(self):
		recompute_rating_from_reviews(self.partner, exclude=self.name)


def list_partner_reviews(partner):
	"""Returns a partner's reviews as a plain API call, since Studio's Document List resource isn't guest-accessible."""
	return frappe.get_all(
		"Partner Review",
		filters={"partner": partner},
		fields=[
			"reviewer_name", "customer", "rating", "headline", "quote", "reviewed_on", "verified",
			"business_understanding", "implementation_quality", "communication",
			"timeliness", "support", "technical_expertise",
		],
		order_by="reviewed_on desc",
		limit_page_length=100,
	)


def get_my_review_for_partner(partner):
	"""Returns the caller's own review of a partner, if one exists, so the review form opens pre-filled."""
	customer = get_customer_for_user()
	if not customer:
		return None
	rows = frappe.get_all(
		"Partner Review", filters={"partner": partner, "customer": customer}, fields=["*"], limit_page_length=1
	)
	return rows[0] if rows else None


def submit_partner_review(
	partner, rating, headline=None, quote=None,
	business_understanding=None, implementation_quality=None, communication=None,
	timeliness=None, support=None, technical_expertise=None,
):
	"""Creates or updates the caller's review of a partner."""
	customer = get_customer_for_user()
	if not customer:
		frappe.throw("Your account isn't linked to a customer company yet.", frappe.PermissionError)

	rating = cint(rating)
	if rating < 1 or rating > 5:
		frappe.throw("Rating must be between 1 and 5.")

	values = {
		"partner": partner,
		"customer": customer,
		"reviewer_name": get_fullname(frappe.session.user),
		"rating": rating,
		"headline": headline,
		"quote": quote,
		"reviewed_on": nowdate(),
		"verified": 1,
		"business_understanding": cint(business_understanding) or None,
		"implementation_quality": cint(implementation_quality) or None,
		"communication": cint(communication) or None,
		"timeliness": cint(timeliness) or None,
		"support": cint(support) or None,
		"technical_expertise": cint(technical_expertise) or None,
	}

	existing = frappe.db.get_value("Partner Review", {"partner": partner, "customer": customer}, "name")
	if existing:
		doc = frappe.get_doc("Partner Review", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.get_doc({"doctype": "Partner Review", **values})
		doc.insert(ignore_permissions=True)

	return {"name": doc.name}
