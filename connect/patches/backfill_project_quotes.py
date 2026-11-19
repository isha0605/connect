# Copyright (c) 2026
# For license information, please see license.txt

import frappe
from frappe import _

from connect.customer.doctype.customer_project.brief import await_quote


def execute():
	"""Gives each brief shared before quotes were tracked its Project Quote rows. Its partners
	are the threads that got the project's Requirement card from its owner when it was shared."""
	Project = frappe.qb.DocType("Customer Project")
	Quote = frappe.qb.DocType("Project Quote")
	tracked = frappe.qb.from_(Quote).select(Quote.customer_project).where(Quote.customer_project.isnotnull())
	projects = (
		frappe.qb.from_(Project)
		.select(Project.name, Project.user, Project.shared_on, Project.description)
		.where(Project.shared_on.isnotnull())
		.where(Project.name.notin(tracked))
		.run(as_dict=True)
	)
	for project in projects:
		for thread, partner in _briefed_threads(project):
			await_quote(project.name, partner, thread)


def _briefed_threads(project) -> list[tuple[str, str]]:
	Message = frappe.qb.DocType("Connect Message")
	Thread = frappe.qb.DocType("Connect Thread")
	messages = (
		frappe.qb.from_(Message)
		.join(Thread)
		.on(Thread.name == Message.thread)
		.select(Message.thread, Message.content, Thread.partner)
		.where(Message.sender == project.user)
		.where(Message.message_type == "Requirement")
		.where(
			Message.creation.between(
				frappe.utils.add_to_date(project.shared_on, minutes=-5),
				frappe.utils.add_to_date(project.shared_on, minutes=5),
			)
		)
		.where(Thread.partner.isnotnull())
		.run(as_dict=True)
	)
	brief = _looking_for(project)
	return [
		(m.thread, m.partner)
		for m in messages
		if (frappe.parse_json(m.content or "{}") or {}).get("looking_for") == brief
	]


def _looking_for(project) -> str | None:
	"""How a Requirement card worded the brief when this patch was written."""
	if not project.description:
		return project.get("project_name")
	return _("Custom implementation: {0}").format(project.description)
