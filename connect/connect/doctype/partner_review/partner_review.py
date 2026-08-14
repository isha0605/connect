# Copyright (c) 2026
# For license information, please see license.txt

from frappe.model.document import Document

from connect.connect.doctype.partner.partner import recompute_rating_from_reviews


class PartnerReview(Document):
	def after_insert(self):
		recompute_rating_from_reviews(self.partner)

	def on_update(self):
		recompute_rating_from_reviews(self.partner)

	def on_trash(self):
		recompute_rating_from_reviews(self.partner, exclude=self.name)
