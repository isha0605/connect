from collections import defaultdict

import frappe

from connect.partner.migration.mapping import Mapping, Table
from connect.partner.migration.owners import add_owner
from connect.partner.migration.report import Report
from connect.partner.migration.sources import get_all, get_child_rows
from connect.partner.migration.store import DELETED_IN_CONNECT, each_partner, get_existing, save

SOURCE = "frappe.io"
# What frappe.io still decides once a partner is in Connect. Partners and Connect own the rest, so a
# later run fills only what Connect has blank, and never undoes what a partner edited.
FRAPPE_IO_OWNED = frozenset(
	{
		"email",
		"enabled",
		"contract_start_date",
		"contract_end_date",
		"contract_renewed",
		"apply_legacy_contract",
		"commitment_scrutiny_date",
	}
)


def with_scheme(url: str) -> str:
	return url if "://" in url else f"https://{url}"


PARTNER = Mapping(
	source=SOURCE,
	source_doctype="Partner",
	target_doctype="Partner",
	fields={
		"company_name": "company_name",
		"partner_type": "tier",
		"status": "verification_status",
		"enabled": "enabled",
		"email": "email",
		"contact_email": "contact_email",
		"phone_number": "phone",
		"partner_website": "website",
		"country": "country",
		"custom_state": "state",
		"description": "description",
		"show_in_website": "show_in_website",
		"listing_date": "listed_on",
		"route": "frappe_io_route",
		"custom_process_maturity_level": "pmm_level",
		"payment_currency": "currency",
		"start_date": "contract_start_date",
		"end_date": "contract_end_date",
		"custom_contract_renewed": "contract_renewed",
		"signup_date": "signup_date",
		"commitment_scrutiny_date": "commitment_scrutiny_date",
		"custom_apply_legacy_contract": "apply_legacy_contract",
		"custom_last_partner_type": "previous_tier",
		"custom_partner_type_change_date": "tier_changed_on",
		"custom_number_of_certified_members": "number_of_certified_members",
		"custom_total_sites_count": "total_sites_count",
	},
	convert={
		"verification_status": {"Approved": "Verified", "Rejected": "Rejected", "Pending": "Pending Review"},
		"website": with_scheme,
	},
	files={"logo": "logo"},
	tables={
		"industry_type": Table(
			"industries",
			Mapping(SOURCE, "Partner Industry Type", "Partner Industry", fields={"industry": "industry"}),
		),
		"custom_countries_served": Table(
			"served_countries",
			Mapping(
				SOURCE, "Partner Countries Served", "Partner Served Country", fields={"country": "country"}
			),
		),
	},
	# The owner's login and name, and the Frappe staff member who looks after the partner.
	read_by_rules=frozenset({"user", "partner_name", "success_manager"}),
	# Contact details and lists a partner can fix in Connect: a bad one shouldn't hold back the partner.
	may_drop=frozenset({"phone", "contact_email", "website", "industries", "served_countries"}),
	skipped=frozenset(
		{
			# Lead routing and partner scoring stay on frappe.io: Connect has its own.
			"auto_pass_unresponsive_leads",
			"max_unresponded_leads",
			"received_last_unresponsive_lead",
			"custom_unresponded_leads_quota",
			"custom_pass_leads_from_outside_country",
			"custom_domain_avg",
			"custom_domain_indicator",
			"custom_domain_score",
			"custom_domain_score_total",
			"custom_skillset_",
			"custom_skillset_indicator",
			"custom_skillset_score",
			"custom_skillset_score_total",
			"custom_revenue_contribution",
			# Connect counts these from the certificates it holds.
			"custom_erpnext_certified",
			"custom_framework_certified",
			# Connect works out the region from the country, and apps from the success stories.
			"territory",
			"custom_app_expertise",
			"skype_id",
			"old_name",
		}
	),
)

MAPPINGS = (PARTNER,)


def fetch_rows(client) -> dict[str, list[dict]]:
	"""Every enabled frappe.io partner, with its tables: the partners in one request, then each
	table's rows for 100 partners at a time."""
	partners = get_all(client, PARTNER.source_doctype, ["*"], {"enabled": 1})
	names = [partner["name"] for partner in partners]
	for source_field, table in PARTNER.tables.items():
		rows = defaultdict(list)
		for row in get_child_rows(
			client, PARTNER.source_doctype, table.mapping.source_doctype, source_field, names
		):
			rows[row["parent"]].append(row)
		for partner in partners:
			partner[source_field] = rows[partner["name"]]
	return {PARTNER.source_doctype: partners}


def migrate(rows: dict[str, list[dict]], report: Report) -> None:
	"""Brings over each frappe.io partner under its frappe.io ID, with its owner and manager."""
	for row in rows[PARTNER.source_doctype]:
		with each_partner(f"frappe.io partner {row['name']}", report):
			_migrate_partner(row, report)


def get_expected_names(rows: dict[str, list[dict]]) -> dict[str, list[str]]:
	"""The source records a clean run migrates, by DocType: every partner read."""
	return {PARTNER.source_doctype: [row["name"] for row in rows[PARTNER.source_doctype]]}


def _migrate_partner(row: dict, report: Report) -> None:
	values = PARTNER.get_values(row)
	values["partner_managers"] = _get_managers(row, report)
	existing = get_existing(PARTNER, row["name"], name=row["name"])
	if existing and frappe.db.exists("Partner", existing):
		values = _keep_connect_values(existing, values)

	partner, outcome = save(
		PARTNER,
		row["name"],
		values,
		name=row["name"],
		file_urls=PARTNER.get_file_urls(row),
		update_existing=True,
		report=report,
	)
	report.add(f"partners_{outcome.replace(' ', '_')}", f"frappe.io {row['name']} → {partner}")
	if outcome != DELETED_IN_CONNECT:
		add_owner(partner, row.get("user"), row.get("partner_name"), row.get("country"), report)


def _keep_connect_values(partner: str, values: dict) -> dict:
	"""For a partner already in Connect: frappe.io's own fields, and the others only where Connect
	has nothing yet."""
	doc = frappe.get_doc("Partner", partner)
	return {
		field: value
		for field, value in values.items()
		if field in FRAPPE_IO_OWNED or doc.get(field) in (None, "", [])
	}


def _get_managers(row: dict, report: Report) -> list[dict]:
	"""frappe.io keeps one success manager per partner. One without a Connect login is reported, as
	Connect can't show them as the partner's manager."""
	manager = row.get("success_manager")
	if not manager:
		return []
	if not frappe.db.exists("User", manager):
		report.add("managers_missing", f"{row['name']}: {manager} has no Connect login")
		return []
	return [{"user": manager}]
