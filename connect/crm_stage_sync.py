"""Partner leads' stages, kept in step with the partner's own Frappe CRM.

A Connect lead is a Lead on the CRM until its stage is one only a Deal status matches; then the
Lead is converted to a Deal there. Each partner matches their CRM's statuses to Connect's stages
in Settings → CRM (Partner CRM Settings' status map), and both directions follow that map.
"""

from urllib.parse import quote

import frappe
from frappe import _

from connect.crm_integration import CRMRequestError, crm_request, crm_settings

CRM_LEAD = "CRM Lead"
CRM_DEAL = "CRM Deal"
STATUS_DOCTYPES = {CRM_LEAD: "CRM Lead Status", CRM_DEAL: "CRM Deal Status"}
CONVERT_TO_DEAL = "/api/method/crm.fcrm.doctype.crm_lead.crm_lead.convert_to_deal"
# On Connect a lead is won only when the customer hires the partner there, so the CRM's Won
# never wins one, and a won lead never moves back.
WON = "Won"
LOST = "Lost"
OTHER_REASON = "Other"


def lead_stages() -> list[str]:
	"""Connect's lead stages, in order, as the Partner Lead DocType defines them."""
	return _options("stage")


def _options(fieldname: str) -> list[str]:
	options = frappe.get_meta("Partner Lead").get_field(fieldname).options or ""
	return [option for option in options.split("\n") if option]


# ---- The map, read from the partner's CRM ----


def refresh_status_map(doc, settings) -> None:
	"""Rows for the CRM's statuses as they are now, in the CRM's order. A status keeps the stage
	chosen for it before; a new one starts on its default stage."""
	chosen = {(row.crm_doctype, row.crm_status): row.stage for row in doc.status_map}
	defaults = default_stages()
	doc.status_map = []
	for crm_doctype, status in _crm_statuses(settings):
		key = (crm_doctype, status)
		stage = chosen[key] if key in chosen else defaults(crm_doctype, status)
		doc.append("status_map", {"crm_doctype": crm_doctype, "crm_status": status, "stage": stage})


def default_stages():
	"""The stage a CRM status starts on: its CRM Status Default, else the Connect stage with the
	status's own name, else none."""
	stages = set(lead_stages())
	rows = frappe.get_all("CRM Status Default", fields=["crm_doctype", "crm_status", "stage"])
	defaults = {(row.crm_doctype, row.crm_status): row.stage for row in rows}

	def stage_for(crm_doctype: str, status: str) -> str | None:
		return defaults.get((crm_doctype, status)) or (status if status in stages else None)

	return stage_for


def validate_status_map(doc) -> None:
	stages = set(lead_stages())
	for row in doc.status_map:
		if row.stage and row.stage not in stages:
			frappe.throw(_('"{0}" isn\'t a lead stage on Connect.').format(row.stage))


def _crm_statuses(settings) -> list[tuple[str, str]]:
	statuses = []
	for crm_doctype, status_doctype in STATUS_DOCTYPES.items():
		rows = crm_request(
			settings,
			"GET",
			f"/api/resource/{quote(status_doctype)}",
			params={"fields": '["name"]', "order_by": "position asc", "limit_page_length": 0},
		).json()["data"]
		statuses += [(crm_doctype, row["name"]) for row in rows]
	return statuses


def _status_map(partner: str) -> list:
	# Partner CRM Settings is named after its partner.
	return frappe.get_all(
		"Partner CRM Status Map",
		filters={"parent": partner, "parenttype": "Partner CRM Settings"},
		fields=["crm_doctype", "crm_status", "stage"],
		order_by="idx asc",
	)


def _status_for(rows: list, crm_doctype: str, stage: str) -> str | None:
	"""The CRM status to send for a stage: the first one matched to it, in the CRM's order."""
	matches = (row.crm_status for row in rows if row.crm_doctype == crm_doctype and row.stage == stage)
	return next(matches, None)


def _stage_for(rows: list, crm_doctype: str, status: str) -> str | None:
	matches = (row.stage for row in rows if row.crm_doctype == crm_doctype and row.crm_status == status)
	return next(matches, None)


# ---- Connect → CRM ----


def queue_stage_sync(lead) -> None:
	"""on_update on Partner Lead, when its stage changed on Connect: sends it to the CRM in the
	background. A lead whose chat has no CRM Lead yet has nothing to move."""
	if not crm_settings(lead.partner) or not frappe.db.get_value("Connect Thread", lead.thread, "crm_lead_id"):
		return
	frappe.enqueue(
		"connect.crm_stage_sync.sync_stage",
		queue="short",
		# Without this, the worker can run before the change is saved, and miss it.
		enqueue_after_commit=True,
		lead=lead.name,
	)


def sync_stage(lead: str) -> None:
	"""Background job: sets the lead's stage on its CRM Lead or Deal, converting the Lead first
	when only a Deal status matches the stage. Notes on the lead why when it couldn't."""
	doc = frappe.get_doc("Partner Lead", lead)
	settings = crm_settings(doc.partner)
	fields = ["name", "crm_lead_id", "crm_deal_id"]
	thread = frappe.db.get_value("Connect Thread", doc.thread, fields, as_dict=True)
	if not settings or not thread or not thread.crm_lead_id:
		return

	try:
		note = _send_stage(doc, settings, thread)
	except Exception:
		frappe.log_error(title=f"CRM stage sync failed for Partner Lead {lead}")
		note = _("“{0}” didn't reach your CRM: it couldn't be updated. The next stage change tries again.")
		note = note.format(doc.stage)
	if note != doc.crm_stage_note:
		doc.db_set("crm_stage_note", note, update_modified=False)


def _send_stage(doc, settings, thread) -> str | None:
	"""Sends the stage; returns a note for the lead when it wasn't sent, else None."""
	rows = _status_map(doc.partner)
	if not thread.crm_deal_id:
		status = _status_for(rows, CRM_LEAD, doc.stage)
		if status:
			_set_status(settings, CRM_LEAD, thread.crm_lead_id, {"status": status})
			return None

	status = _status_for(rows, CRM_DEAL, doc.stage)
	if not status:
		note = _("“{0}” isn't matched to a status on your CRM, so the CRM wasn't changed. Match it in Settings → CRM.")
		return note.format(doc.stage)
	deal = thread.crm_deal_id or _convert_to_deal(settings, thread)
	_set_status(settings, CRM_DEAL, deal, {"status": status, **_lost_fields(settings, status, doc)})
	return None


def _convert_to_deal(settings, thread) -> str:
	"""Converts the CRM Lead with Frappe CRM's own conversion, which keeps its emails on the Deal."""
	deal = crm_request(settings, "POST", CONVERT_TO_DEAL, json={"lead": thread.crm_lead_id}).json()["message"]
	frappe.db.set_value("Connect Thread", thread.name, "crm_deal_id", deal, update_modified=False)
	return deal


def _set_status(settings, crm_doctype: str, name: str, values: dict) -> None:
	crm_request(settings, "PUT", f"/api/resource/{quote(crm_doctype)}/{quote(name)}", json=values)


def _lost_fields(settings, status: str, doc) -> dict:
	"""A Deal marked lost on Frappe CRM must say why: Connect's reason when the CRM has one by
	that name, else Other with Connect's reason as its note."""
	path = f"/api/resource/{quote(STATUS_DOCTYPES[CRM_DEAL])}/{quote(status)}"
	if crm_request(settings, "GET", path).json()["data"].get("type") != LOST:
		return {}
	reason = doc.lost_reason or doc.stage
	try:
		crm_request(settings, "GET", f"/api/resource/CRM Lost Reason/{quote(reason)}")
		return {"lost_reason": reason}
	except CRMRequestError as e:
		if e.status_code != 404:
			raise
		return {"lost_reason": OTHER_REASON, "lost_notes": reason}


# ---- CRM → Connect ----


def stage_webhooks(partner: str, integration_user: str, secret: str) -> list[dict]:
	"""The Webhooks that tell Connect when a Lead's or Deal's status changes on the partner's
	CRM, and when a Lead is converted there.

	A status change is sent whoever made it: the partner's CRM user can be the API user Connect
	signs in as. A change Connect made comes back as the stage the lead is already on, which
	record_crm_status ignores. A Deal Connect converted is left out: Connect already knows it."""
	status_changed = "doc.has_value_changed('status')"
	deal_fields = ("name", "status", "lead", "lost_reason")
	webhooks = [
		(f"Connect Lead Stage Sync - {partner}", CRM_LEAD, "on_change", status_changed, ("name", "status")),
		(f"Connect Deal Stage Sync - {partner}", CRM_DEAL, "on_change", status_changed, deal_fields),
		# Converting a Lead on the CRM makes its Deal: Connect follows the Deal from then on.
		(
			f"Connect Deal Conversion Sync - {partner}",
			CRM_DEAL,
			"after_insert",
			f"doc.lead and doc.owner!={integration_user!r}",
			deal_fields,
		),
	]
	return [_webhook(partner, secret, *webhook) for webhook in webhooks]


def _webhook(partner, secret, name, crm_doctype, event, condition, fields) -> dict:
	method = "receive_crm_lead_status" if crm_doctype == CRM_LEAD else "receive_crm_deal_status"
	callback_url = frappe.utils.get_url(f"/api/method/connect.api.crm_webhook.{method}?partner={quote(partner)}")
	return {
		"name": name,
		"webhook_doctype": crm_doctype,
		"webhook_docevent": event,
		"condition": condition,
		"request_url": callback_url,
		"request_method": "POST",
		"request_structure": "Form URL-Encoded",
		"webhook_data": [{"fieldname": field, "key": field} for field in fields],
		"webhook_headers": [{"key": "Content-Type", "value": "application/json"}],
		"enable_security": 1,
		"webhook_secret": secret,
		"enabled": 1,
	}


def record_crm_status(
	partner: str, crm_doctype: str, name: str | None, status: str | None, crm_lead=None, lost_reason=None
) -> None:
	"""A Lead's or Deal's status changed on the partner's CRM: the Connect lead moves to the stage
	the partner matched it to. A Deal made from a Connect Lead is remembered on its thread."""
	thread = _thread_for(partner, crm_doctype, name, crm_lead)
	lead = thread and frappe.db.get_value("Partner Lead", {"thread": thread}, "name")
	if not lead or not status:
		return  # not a Connect lead

	stage = _stage_for(_status_map(partner), crm_doctype, status)
	doc = frappe.get_doc("Partner Lead", lead)
	if not stage or stage == WON or doc.stage in (WON, stage):
		return
	doc.stage = stage
	if stage == LOST:
		doc.lost_reason = lost_reason if lost_reason in _options("lost_reason") else OTHER_REASON
	doc.flags.from_crm = True
	# The CRM's signed webhook, with no Connect login; the partner's own CRM decided this.
	doc.save(ignore_permissions=True, ignore_version=False)


def _thread_for(partner: str, crm_doctype: str, name: str | None, crm_lead: str | None) -> str | None:
	if not name:
		return None
	if crm_doctype == CRM_LEAD:
		return frappe.db.get_value("Connect Thread", {"partner": partner, "crm_lead_id": name}, "name")
	thread = frappe.db.get_value("Connect Thread", {"partner": partner, "crm_deal_id": name}, "name")
	if thread or not crm_lead:
		return thread
	thread = frappe.db.get_value("Connect Thread", {"partner": partner, "crm_lead_id": crm_lead}, "name")
	if thread:
		frappe.db.set_value("Connect Thread", thread, "crm_deal_id", name, update_modified=False)
	return thread
