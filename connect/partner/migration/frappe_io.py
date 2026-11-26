import re

import frappe

from connect.partner.migration.mapping import Mapping, Table
from connect.partner.migration.owners import add_owner
from connect.partner.migration.report import Report
from connect.partner.migration.sources import get_all
from connect.partner.migration.store import (
	DELETED_IN_CONNECT,
	each_partner,
	get_existing,
	get_label,
	save,
)

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
		"contract_end_date_as_per_payment",
		"legacy_partner_type",
		"legacy_contract_end_date",
	}
)


# frappe.io names some countries differently from Frappe's Country list.
COUNTRY_NAMES = {
	"Congo - Kinshasa": "Congo, The Democratic Republic of the",
	"Congo - Brazzaville": "Congo",
}


def with_scheme(url: str) -> str:
	return url if "://" in url else f"https://{url}"


def first_number(value: object) -> object:
	"""The first whole number in a count typed as text, such as 60 in "60+". A value with no number
	is kept as it is, so the check reports it."""
	if isinstance(value, int):
		return value
	match = re.search(r"\d+", str(value))
	return int(match.group()) if match else value


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
		"custom_city": "city",
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
		"custom_journey_blog_link": "journey_blog_url",
		"custom_foundation_date": "foundation_date",
		"custom_team_size": "team_size",
		"custom_successful_projects_count": "successful_projects_count",
		"custom_contract_end_date_as_per_payment": "contract_end_date_as_per_payment",
		"custom_legacy_contract_end_date": "legacy_contract_end_date",
		"custom_legacy_partner_type": "legacy_partner_type",
	},
	convert={
		"verification_status": {
			"Approved": "Verified",
			"Rejected": "Rejected",
			"Not Approved": "Rejected",
			"Pending": "Pending Review",
		},
		"website": with_scheme,
		"country": COUNTRY_NAMES,
		"number_of_certified_members": first_number,
		"total_sites_count": first_number,
		"successful_projects_count": first_number,
	},
	files={"logo": "logo"},
	# frappe.io links one industry and one country; Connect keeps lists of them.
	tables={
		"industry_type": Table(
			"industries",
			Mapping(SOURCE, "Industry Type", "Partner Industry", fields={"industry": "industry"}),
		),
		"custom_countries_served": Table(
			"served_countries",
			Mapping(
				SOURCE,
				"Country",
				"Partner Served Country",
				fields={"country": "country"},
				convert={"country": COUNTRY_NAMES},
			),
		),
	},
	# The owner's name (their login is the partner's email), the Frappe staff member who looks after
	# the partner, and the address that becomes the partner's office.
	read_by_rules=frozenset({"partner_name", "success_manager", "address"}),
	# Details a partner or staff can fix in Connect: a bad one shouldn't hold back the partner. A team
	# size outside Connect's ranges, or an old tier Connect doesn't have, is listed and left out.
	may_drop=frozenset(
		{
			"phone",
			"contact_email",
			"website",
			"industries",
			"served_countries",
			"team_size",
			"legacy_partner_type",
		}
	),
)

MAPPINGS = (PARTNER,)


def fetch_rows(client) -> dict[str, list[dict]]:
	"""Every enabled frappe.io partner, in one request. Each linked industry and country becomes
	the one row of its Connect table."""
	partners = get_all(client, PARTNER.source_doctype, PARTNER.get_source_fields(), {"enabled": 1})
	for partner in partners:
		for source_field, table in PARTNER.tables.items():
			(target_field,) = table.mapping.fields.values()
			value = partner.get(source_field)
			partner[source_field] = [{target_field: value}] if value else []
	return {PARTNER.source_doctype: partners}


def get_partner_emails(rows: dict[str, list[dict]]) -> set[str]:
	"""The emails of the partners read: Press finds each partner's team by them."""
	return {row["email"] for row in rows[PARTNER.source_doctype] if row.get("email")}


def get_migrated_partner_emails() -> set[str]:
	"""The emails of the partners an earlier run brought from frappe.io, for a run of Press alone."""
	partners = frappe.get_all(
		"Migration Record",
		filters={"source": SOURCE, "source_doctype": PARTNER.source_doctype},
		pluck="target_name",
	)
	return set(
		frappe.get_all("Partner", filters={"name": ["in", partners], "email": ["is", "set"]}, pluck="email")
	)


def migrate(rows: dict[str, list[dict]], report: Report) -> None:
	"""Brings over each frappe.io partner under its frappe.io ID, with its owner and manager. frappe.io
	runs first: Press finds these partners by email."""
	for row in rows[PARTNER.source_doctype]:
		with each_partner(get_label(PARTNER, row["name"]), report):
			_migrate_partner(row, report)


def get_expected_names(rows: dict[str, list[dict]]) -> dict[str, list[str]]:
	"""The source records a clean run migrates, by DocType: every partner read."""
	return {PARTNER.source_doctype: [row["name"] for row in rows[PARTNER.source_doctype]]}


def _migrate_partner(row: dict, report: Report) -> None:
	values = PARTNER.get_values(row)
	country = values.get("country")
	values["partner_managers"] = _get_managers(row, report)
	values["offices"] = _get_offices(row, report)
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
		add_owner(partner, row.get("email"), row.get("partner_name"), country, report)


def _keep_connect_values(partner: str, values: dict) -> dict:
	"""For a partner already in Connect: frappe.io's own fields, and the others only where Connect
	has nothing yet."""
	doc = frappe.get_doc("Partner", partner)
	return {
		field: value
		for field, value in values.items()
		if field in FRAPPE_IO_OWNED or doc.get(field) in (None, "", [])
	}


def _get_offices(row: dict, report: Report) -> list[dict]:
	"""frappe.io keeps one address per partner, in a text box. Connect's office needs a city too, as
	Frappe's Address does, so an address without a city is reported and left out."""
	address = (row.get("address") or "").strip()
	city = (row.get("custom_city") or "").strip()
	if address and not city:
		report.add("values_dropped", f"{row['name']}: Partner.address has no city, so no office was added")
	if not (address and city):
		return []
	return [{"city": city, "address": address}]


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
