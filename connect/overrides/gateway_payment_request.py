# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _

from bwh_payments.bwh_payments.doctype.gateway_payment_request.gateway_payment_request import (
	GatewayPaymentRequest as BWHGatewayPaymentRequest,
)


class GatewayPaymentRequest(BWHGatewayPaymentRequest):
	@frappe.whitelist()
	def refund(self, amount: float | None = None, payment_entry: str | None = None):
		# bwh_payments sends the refund to the gateway before it saves, and doc_events
		# only run after the method, so a hook can't stop a refund in time. This is the
		# last point before the money moves.
		if self.ref_doctype == "Starter Pack Order" and frappe.db.get_value(
			"Starter Pack Order", self.ref_docname, "kickoff_date"
		):
			frappe.throw(
				_("{0} can't be refunded: the implementation has already kicked off.").format(
					frappe.bold(self.ref_docname)
				),
				title=_("Refund Not Allowed"),
			)
		return super().refund(amount=amount, payment_entry=payment_entry)
