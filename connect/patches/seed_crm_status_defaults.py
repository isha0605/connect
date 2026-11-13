# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# Frappe CRM's own Lead statuses and the Connect stage each starts on. Deal statuses need none:
# Connect's stages after Open have the same names. Converted is a Lead the CRM made a Deal of.
LEAD_STATUS_STAGES = {
	"New": "Open",
	"Contacted": "Follow Up",
	"Nurture": "Follow Up",
	"Qualified": "Qualification",
	"Converted": "Qualification",
	"Unqualified": "Lost",
}


def execute():
	"""Seeds the defaults, then gives partners already connected the default for every status
	they haven't picked a stage for."""
	seed()
	_fill_partner_maps()


def seed():
	for status, stage in LEAD_STATUS_STAGES.items():
		if not frappe.db.exists("CRM Status Default", f"CRM Lead: {status}"):
			doc = {"doctype": "CRM Status Default", "crm_doctype": "CRM Lead", "crm_status": status, "stage": stage}
			frappe.get_doc(doc).insert(ignore_permissions=True)


def _fill_partner_maps():
	from connect.crm_stage_sync import default_stages

	stage_for = default_stages()
	unpicked = {"stage": ["is", "not set"]}
	rows = frappe.get_all("Partner CRM Status Map", filters=unpicked, fields=["name", "crm_doctype", "crm_status"])
	for row in rows:
		stage = stage_for(row.crm_doctype, row.crm_status)
		if stage:
			frappe.db.set_value("Partner CRM Status Map", row.name, "stage", stage, update_modified=False)
