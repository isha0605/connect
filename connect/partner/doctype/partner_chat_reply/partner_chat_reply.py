# Copyright (c) 2026, Isha and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class PartnerChatReply(Document):
	"""One customer chat message the partner had to answer within one working day: Due
	until the partner replies, then Fulfilled or Failed. connect.partner.chat_sla writes it."""
