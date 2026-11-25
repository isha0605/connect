from collections import defaultdict

import frappe
from frappe import _

from connect.partner.doctype.partner_application.partner_application import NEW_PARTNER_TIER
from connect.partner.doctype.partner_certificate.partner_certificate import recount_certificates
from connect.partner.migration.mapping import Mapping
from connect.partner.migration.owners import add_owner
from connect.partner.migration.report import Report
from connect.partner.migration.sources import get_all, get_where_in
from connect.partner.migration.store import (
	MigrationProblem,
	each_partner,
	get_label,
	get_migrated,
	is_deleted,
	remember,
	save,
)

SOURCE = "Press"
_ONBOARDING_FIELDS = (
	"company_name",
	"company_email",
	"registered_country",
	"registered_state",
	"contact",
	"address",
	"headquarter_city",
	"annual_revenue",
	"revenue_currency",
	"employee_range",
	"certified_employees_range",
	"verticals_served",
	"customer_count_range",
	"erpnext_customer_count_range",
	"existing_partnerships",
	"erp_implementations_range",
	"agreed_to_due_diligence",
	"agreed_to_partnership_agreement",
	"status",
	"submitted_on",
	"reviewed_on",
	"approved_on",
	"reviewer_comments",
)
_AUDIT_FIELDS = (
	"mode_of_audit",
	"partner_tier",
	"status",
	"requested_on",
	"proposed_audit_date",
	"audit_date",
	"implementation_summary",
	"implementation_finding",
	"implementation_observation",
	"sales_summary",
	"sales_finding",
	"sales_observation",
	"support_summary",
	"support_finding",
	"support_observation",
	"next_actions",
)
# An onboarding submitted and waiting for review: its team applied and isn't a partner yet.
PENDING_REVIEW = "Pending Review"

# Only a team's name and emails are read: they tie Press's records to the partner with that email.
TEAM = Mapping(
	source=SOURCE,
	source_doctype="Team",
	target_doctype="Partner",
	read_by_rules=frozenset({"user", "partner_email"}),
)
ONBOARDING = Mapping(
	source=SOURCE,
	source_doctype="Partner Onboarding",
	target_doctype="Partner Application",
	fields={field: field for field in _ONBOARDING_FIELDS},
	files={"incorporation_certificate": "incorporation_certificate", "company_logo": "company_logo"},
	read_by_rules=frozenset({"team"}),
	# Not reviewed yet, and the onboarding it amends isn't migrated.
	skipped=frozenset({"reviewed_by", "amended_from"}),
	is_submitted=True,
)
CERTIFICATE = Mapping(
	source=SOURCE,
	source_doctype="Partner Certificate",
	target_doctype="Partner Certificate",
	fields={
		field: field for field in ("course", "partner_member_email", "partner_member_name", "issue_date")
	},
	read_by_rules=frozenset({"team", "certificate_link"}),
)
AUDIT = Mapping(
	source=SOURCE,
	source_doctype="Partner Audit",
	target_doctype="Partner Audit",
	fields={field: field for field in _AUDIT_FIELDS},
	files={"audit_report": "audit_report"},
	read_by_rules=frozenset({"partner_team", "conducted_by"}),
	# Press required none of its fields, so an old audit may have no mode.
	may_be_blank=frozenset({"mode_of_audit"}),
)
NON_CONFORMANCE = Mapping(
	source=SOURCE,
	source_doctype="Partner Non Conformance",
	target_doctype="Partner Non Conformance",
	fields={
		"status": "status",
		"department": "department",
		"expected_closure": "expected_closure",
		"closed_on": "closed_on",
		"nc_statement": "statement",
		"nc_description": "description",
		"measures_to_close_nc": "closure_measures",
	},
	files={"evidence": "evidence"},
	read_by_rules=frozenset({"partner_team", "partner_audit", "closed_by"}),
	# Press required none of its fields, so an old non-conformance may have no statement or department.
	may_be_blank=frozenset({"statement", "department"}),
)
MAPPINGS = (TEAM, ONBOARDING, CERTIFICATE, AUDIT, NON_CONFORMANCE)
# The field naming the team each Press record belongs to.
_TEAM_FIELDS = {
	ONBOARDING.source_doctype: "team",
	CERTIFICATE.source_doctype: "team",
	AUDIT.source_doctype: "partner_team",
	NON_CONFORMANCE.source_doctype: "partner_team",
}
# A Team is a whole Frappe Cloud account: only these columns are read.
_TEAM_COLUMNS = ["name", "user", "partner_email"]


def fetch_rows(client, partner_emails: set[str]) -> dict[str, list[dict]]:
	"""The Press records of these partners and of applicants: the teams with a partner's email, the
	onboardings pending review with their teams, and those teams' certificates, audits and
	non-conformances."""
	onboardings = get_all(
		client, ONBOARDING.source_doctype, ["*"], {"status": PENDING_REVIEW, "team": ["is", "set"]}
	)
	teams = {}
	for fieldname, values in (
		("partner_email", partner_emails),
		("user", partner_emails),
		("name", {row["team"] for row in onboardings}),
	):
		for team in get_where_in(client, TEAM.source_doctype, _TEAM_COLUMNS, fieldname, values):
			teams[team["name"]] = team

	rows = {TEAM.source_doctype: list(teams.values()), ONBOARDING.source_doctype: onboardings}
	for mapping in (CERTIFICATE, AUDIT, NON_CONFORMANCE):
		team_field = _TEAM_FIELDS[mapping.source_doctype]
		rows[mapping.source_doctype] = get_where_in(client, mapping.source_doctype, ["*"], team_field, teams)
	return rows


def migrate(rows: dict[str, list[dict]], report: Report) -> None:
	"""Brings each Press team's records to its partner: the frappe.io partner with the team's email,
	or, for a team that applied, a new partner made from its onboarding."""
	certificates = _get_newest_certificates(rows[CERTIFICATE.source_doctype])
	newest = {row["name"] for row in certificates}
	for row in rows[CERTIFICATE.source_doctype]:
		if row["name"] not in newest:
			report.add(
				"skipped",
				f"Certificate {row['name']}: an older copy of {row.get('partner_member_email')} / {row.get('course')}",
			)

	records = {
		"onboardings": _group(rows[ONBOARDING.source_doctype], ONBOARDING),
		"certificates": _group(certificates, CERTIFICATE),
		"audits": _group(rows[AUDIT.source_doctype], AUDIT),
		"non_conformances": _group(rows[NON_CONFORMANCE.source_doctype], NON_CONFORMANCE),
	}
	for team in rows[TEAM.source_doctype]:
		team_records = {kind: grouped.get(team["name"], []) for kind, grouped in records.items()}
		with each_partner(get_label(TEAM, team["name"]), report):
			_migrate_team(team, team_records, report)


def get_expected_names(rows: dict[str, list[dict]]) -> dict[str, list[str]]:
	"""The source records a clean run migrates, by DocType: every record read, except the older
	copies of a certificate."""
	expected = {
		mapping.source_doctype: [row["name"] for row in rows[mapping.source_doctype]] for mapping in MAPPINGS
	}
	newest = _get_newest_certificates(rows[CERTIFICATE.source_doctype])
	expected[CERTIFICATE.source_doctype] = [row["name"] for row in newest]
	return expected


def _group(rows: list[dict], mapping: Mapping) -> dict[str, list[dict]]:
	grouped = defaultdict(list)
	for row in sorted(rows, key=lambda row: row.get("creation") or ""):
		grouped[row[_TEAM_FIELDS[mapping.source_doctype]]].append(row)
	return grouped


def _get_newest_certificates(rows: list[dict]) -> list[dict]:
	"""Connect keeps one certificate per holder and course, so only the newest of each comes over."""
	kept, certificates = set(), []
	for row in sorted(rows, key=lambda row: row.get("issue_date") or "", reverse=True):
		key = (row.get("partner_member_email"), row.get("course"))
		if key not in kept:
			kept.add(key)
			certificates.append(row)
	return certificates


def _migrate_team(team: dict, records: dict[str, list[dict]], report: Report) -> None:
	migrated = get_migrated(SOURCE, TEAM.source_doctype, team["name"])
	if is_deleted("Partner", migrated):
		# Removed in Connect on purpose: its Press records aren't brought back either.
		report.add("partners_deleted_in_Connect", f"Press {team['name']} → {migrated}")
		return

	partner = _get_partner(team, records["onboardings"], report)
	if not partner:
		emails = ", ".join(dict.fromkeys(filter(None, (team.get("partner_email"), team.get("user")))))
		counts = ", ".join(f"{len(rows)} {kind}" for kind, rows in records.items() if rows)
		report.add(
			"unmatched",
			f"Team {team['name']} ({emails}): no partner in Connect has this email, so its "
			f"{counts or 'records'} weren't brought over. If its frappe.io partner failed, fix that first.",
		)
		return

	add_owner(partner, team.get("user"), None, None, report)
	for onboarding in records["onboardings"]:
		_migrate_application(onboarding, partner, report)

	for certificate in records["certificates"]:
		_migrate_certificate(certificate, partner, report)
	recount_certificates(partner)

	for audit in records["audits"]:
		_migrate_audit(audit, partner, report)
	for row in records["non_conformances"]:
		_migrate_non_conformance(row, partner, report)


def _get_partner(team: dict, onboardings: list[dict], report: Report) -> str | None:
	"""The team's Connect partner: the one an earlier run linked, else the frappe.io partner with the
	team's email, else a new partner for a team that applied."""
	partner = get_migrated(SOURCE, TEAM.source_doctype, team["name"])
	if partner:
		report.add("partners_already_migrated", f"Press {team['name']} → {partner}")
		return partner

	partner = _get_partner_by_email(team)
	if partner:
		remember(TEAM, team["name"], partner)
		report.add("partners_matched", f"Press {team['name']} → {partner}")
		return partner

	if not onboardings:
		return None
	latest = onboardings[-1]
	file_urls = {"logo": latest["company_logo"]} if latest.get("company_logo") else None
	partner, _outcome = save(TEAM, team["name"], _get_applicant_values(team, latest), file_urls=file_urls)
	report.add("partners_created", f"Press {team['name']} → {partner}")
	return partner


def _get_applicant_values(team: dict, onboarding: dict) -> dict:
	return {
		"company_name": (onboarding.get("company_name") or team["name"]).strip(),
		"country": onboarding.get("registered_country"),
		"state": onboarding.get("registered_state"),
		"city": onboarding.get("headquarter_city"),
		"email": team.get("partner_email") or team.get("user") or onboarding.get("company_email"),
		# A team that applied starts where a Connect signup does.
		"tier": NEW_PARTNER_TIER,
	}


def _get_partner_by_email(team: dict) -> str | None:
	"""The partner whose email is the team's partner email, else its owner's: how frappe.io finds a
	partner's team."""
	for email in filter(None, (team.get("partner_email"), team.get("user"))):
		partners = frappe.get_all("Partner", filters={"email": email}, pluck="name")
		if len(partners) > 1:
			raise MigrationProblem(_("Partners {0} share the email {1}.").format(", ".join(partners), email))
		if partners:
			return partners[0]
	return None


def _migrate_application(onboarding: dict, partner: str, report: Report) -> None:
	values = {**ONBOARDING.get_values(onboarding), "partner": partner}
	name, outcome = save(
		ONBOARDING, onboarding["name"], values, file_urls=ONBOARDING.get_file_urls(onboarding)
	)
	report.add(f"applications_{outcome.replace(' ', '_')}", f"{onboarding['name']} → {name}")


def _get_existing_user(user: str | None) -> str | None:
	return user if user and frappe.db.exists("User", user) else None


def _migrate_certificate(certificate: dict, partner: str, report: Report) -> None:
	"""Connect finds a certificate by holder and course, so one already here is linked to the partner
	instead of copied again, unless another partner holds it."""
	email, course = certificate.get("partner_member_email"), certificate.get("course")
	label = f"{certificate['name']}: {email} / {course}"
	existing = frappe.db.get_value(
		"Partner Certificate",
		{"partner_member_email": email, "course": course},
		["name", "partner"],
		as_dict=True,
	)

	if existing and existing.partner and existing.partner != partner:
		report.add("conflicts", f"{label} belongs to {existing.partner}")
		return
	if existing:
		frappe.db.set_value("Partner Certificate", existing.name, "partner", partner)
		remember(CERTIFICATE, certificate["name"], existing.name)
		report.add("certificates_linked", f"{label} → {existing.name}")
		return

	values = {
		**CERTIFICATE.get_values(certificate),
		"school_certificate_id": _get_school_certificate_id(certificate.get("certificate_link")),
		"partner": partner,
	}
	name, outcome = save(CERTIFICATE, certificate["name"], values)
	report.add(f"certificates_{outcome.replace(' ', '_')}", f"{label} → {name}")


def _get_school_certificate_id(certificate_link: str | None) -> str | None:
	"""The Frappe School certificate's name: the last part of its link on Press."""
	if not certificate_link:
		return None
	return certificate_link.split("?")[0].rstrip("/").rsplit("/", 1)[-1]


def _migrate_audit(audit: dict, partner: str, report: Report) -> None:
	values = {
		**AUDIT.get_values(audit),
		"partner": partner,
		"conducted_by": _get_existing_user(audit.get("conducted_by")),
	}
	name, outcome = save(AUDIT, audit["name"], values, file_urls=AUDIT.get_file_urls(audit))
	report.add(f"audits_{outcome.replace(' ', '_')}", f"{audit['name']} → {name}")


def _migrate_non_conformance(row: dict, partner: str, report: Report) -> None:
	"""Connect keeps a non-conformance on its audit, and takes the partner, auditor and date from it."""
	audit = get_migrated(SOURCE, AUDIT.source_doctype, row.get("partner_audit") or "")
	if not audit:
		report.add("conflicts", f"Non-conformance {row['name']} of {partner}: its audit isn't migrated")
		return
	if is_deleted("Partner Audit", audit):
		report.add("non_conformances_deleted_in_Connect", f"{row['name']}: its audit {audit} was deleted")
		return

	values = {
		**NON_CONFORMANCE.get_values(row),
		"partner_audit": audit,
		"closed_by": _get_existing_user(row.get("closed_by")),
	}
	name, outcome = save(NON_CONFORMANCE, row["name"], values, file_urls=NON_CONFORMANCE.get_file_urls(row))
	report.add(f"non_conformances_{outcome.replace(' ', '_')}", f"{row['name']} → {name}")
