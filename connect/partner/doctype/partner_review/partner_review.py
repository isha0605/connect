# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_fullname, nowdate

from connect.partner.doctype.partner.partner import recompute_rating_from_reviews


class PartnerReview(Document):
	def validate(self):
		from connect.customer.doctype.customer.customer import get_customer_for_user
		if not self.customer:
			self.customer = get_customer_for_user()
		if not self.customer:
			frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

		if not self.reviewer_name:
			self.reviewer_name = get_fullname(frappe.session.user)
		if not self.reviewed_on:
			self.reviewed_on = nowdate()

		self.rating = cint(self.rating)
		if self.rating < 1 or self.rating > 5:
			frappe.throw(_("Rating must be between 1 and 5."))

	def after_insert(self):
		recompute_rating_from_reviews(self.partner)

	def on_update(self):
		recompute_rating_from_reviews(self.partner)

	def on_trash(self):
		recompute_rating_from_reviews(self.partner, exclude=self.name)


def submit_partner_review(
	partner: str,
	rating: int,
	headline: str | None = None,
	quote: str | None = None,
	business_understanding: int | None = None,
	implementation_quality: int | None = None,
	communication: int | None = None,
	timeliness: int | None = None,
	support: int | None = None,
	technical_expertise: int | None = None,
):
	"""Create or update the current customer's review of a partner. Partner.rating
	and the dimension scores are recomputed by Partner Review's own
	after_insert/on_update hook, not here."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		frappe.throw(_("Your account isn't linked to a customer company yet."), frappe.PermissionError)

	rating = cint(rating)
	if rating < 1 or rating > 5:
		frappe.throw(_("Rating must be between 1 and 5."))

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


def get_my_review_for_partner(partner: str):
	"""The current user's own review of this partner, if they've already left one —
	lets the "Write a Review" form load as an edit instead of a blank form."""
	from connect.customer.doctype.customer.customer import get_customer_for_user
	customer = get_customer_for_user()
	if not customer:
		return None
	rows = frappe.get_all(
		"Partner Review", filters={"partner": partner, "customer": customer}, fields=["*"], limit_page_length=1
	)
	return rows[0] if rows else None


def list_partner_reviews(partner: str):
	"""Reviews tab on Partner Profile. Studio's "Document List" resource type calls
	frappe.client.get_list under the hood, which isn't guest-whitelisted regardless of
	the target doctype's own Guest permission — same fix as list_partner_filter_options."""
	return frappe.get_all(
		"Partner Review",
		filters={"partner": partner},
		fields=["reviewer_name", "rating", "headline", "quote", "reviewed_on", "verified"],
		order_by="reviewed_on desc",
		limit_page_length=100,
	)
