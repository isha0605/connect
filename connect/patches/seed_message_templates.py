import frappe

PARTNER_TEMPLATES = [
	(
		"Initial response",
		"Thanks for reaching out! I've reviewed your requirements and would love to discuss further. Could you share a bit more about your timeline and budget range?",
	),
	(
		"Scope clarification",
		"Hi, thanks for your interest. Before we proceed, could you confirm which Frappe modules/apps you're looking to implement?",
	),
	(
		"Quotation delivered",
		"Please find our quotation attached. Happy to walk through any line item or adjust scope based on your feedback.",
	),
	(
		"Kickoff scheduling",
		"Welcome aboard! Next step is a kickoff call to align on scope, timeline, and access requirements. Does a time this week work?",
	),
	(
		"Access request",
		"Could you share admin access to your Frappe instance (or confirm if you'd like us to set up a new one)?",
	),
	(
		"Status update",
		"Quick update: we've completed the current milestone and are on track for the next one. Happy to share more detail if useful.",
	),
	(
		"Go-live check-in",
		"Deployment is complete! Let us know if anything needs adjustment over the next few days as your team starts using it.",
	),
	(
		"Follow-up nudge",
		"Following up on my previous message — happy to answer any questions before you decide.",
	),
]

CUSTOMER_TEMPLATES = [
	(
		"Initial enquiry",
		"Hi, we're looking to implement a Frappe solution and came across your profile. Could you share your experience with similar projects?",
	),
	(
		"Availability check",
		"Do you have availability to take on a new project starting soon?",
	),
	(
		"Quote clarification",
		"Thanks for the quote — could you break down what's included in one of the line items?",
	),
	(
		"Ready to proceed",
		"Sounds good, let's move forward. What do you need from our side to get started?",
	),
	(
		"Progress check-in",
		"Just checking in — how's progress looking against the timeline we discussed?",
	),
	(
		"Raising a concern",
		"We're seeing an issue and would appreciate someone taking a look when possible.",
	),
]


def execute():
	"""Seed the platform's global default quick-reply templates, one per side. Safe to re-run —
	skips any (title, side) pair that already exists rather than duplicating it."""
	if not frappe.db.table_exists("Connect Message Template"):
		return

	_seed(PARTNER_TEMPLATES, "Partner")
	_seed(CUSTOMER_TEMPLATES, "Customer")


def _seed(templates, side):
	for title, content in templates:
		if frappe.db.exists("Connect Message Template", {"title": title, "side": side, "is_global": 1}):
			continue
		frappe.get_doc({
			"doctype": "Connect Message Template",
			"title": title,
			"content": content,
			"side": side,
			"is_global": 1,
		}).insert(ignore_permissions=True)
