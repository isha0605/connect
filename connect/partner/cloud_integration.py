import frappe
from frappe import _
from frappe.utils import add_days, escape_html, get_url, now_datetime

from connect.permissions import _get_partner_admin, _is_partner_admin

# Frappe Cloud's registration link stays open this long (its Invitation Expiry). A new link
# replaces the old one, so the partner's admin is emailed again only after the old one closes.
REGISTRATION_RESEND_DAYS = 14

# The link states Connect still has to ask Frappe Cloud about, every hour until it answers.
RETRY_STATUSES = ("Pending", "Waiting for Partner")

# The link states the customer or Frappe Cloud can still change.
SYNCED_STATUSES = ("Requested", "Active")

# Where the partner's admin comes back to after picking their Frappe Cloud team.
ONBOARDING_PATH = "/connect/partner-onboarding"


def is_cloud_enabled() -> bool:
	return bool(frappe.db.get_single_value("Integration Settings", "cloud_enabled"))


def _get_cloud_client():
	"""Returns a FrappeClient signed in to Frappe Cloud as its Connect Integration user."""
	from frappe.frappeclient import FrappeClient

	settings = frappe.get_cached_doc("Integration Settings")
	if not settings.cloud_enabled or not (
		settings.cloud_site_url and settings.cloud_api_key and settings.cloud_api_secret
	):
		frappe.throw(_("Frappe Cloud integration isn't configured yet. Contact an administrator."))

	return FrappeClient(
		settings.cloud_site_url,
		api_key=settings.cloud_api_key,
		api_secret=settings.get_password("cloud_api_secret"),
	)


def queue_cloud_link(project) -> None:
	"""Marks a newly hired project for linking on Frappe Cloud and asks right after the commit.
	The hourly retry picks it up if Frappe Cloud is off or doesn't answer."""
	project.db_set({"cloud_link_status": "Pending", "cloud_setup_url": None, "cloud_link_error": None})
	if is_cloud_enabled():
		frappe.enqueue(
			"connect.partner.cloud_integration.request_cloud_link",
			queue="short",
			enqueue_after_commit=True,
			project=project.name,
		)


def request_cloud_link(project: str) -> None:
	"""Background job: asks Frappe Cloud to link the hired partner with the customer. Frappe Cloud
	returns a one-time link that only the customer's email can open, which step 2 shows them."""
	doc = frappe.get_doc("Customer Project", project)
	if doc.status not in ("Hired", "Completed") or doc.cloud_link_status not in RETRY_STATUSES:
		return

	registered = None
	try:
		client = _get_cloud_client()
		registered = _ensure_registration(client, doc.partner)
		result = client.post_api(
			"central.api.connect.create_partner_link",
			{
				"connect_partner_id": doc.partner,
				"engagement_id": doc.name,
				"customer_email": frappe.db.get_value("User", doc.user, "email") or doc.user,
				"project_title": doc.project_name,
				"return_url": get_url(f"/connect/custom-implementation?project={doc.name}"),
			},
		)
	except Exception:
		# Frappe Cloud is down, or the partner hasn't picked its team yet: the hourly retry asks again.
		doc.db_set(
			{
				"cloud_link_status": "Waiting for Partner" if registered is False else "Pending",
				"cloud_link_error": frappe.get_traceback(with_context=False)[-2000:],
			}
		)
		return

	if not registered:
		frappe.db.set_value("Partner", doc.partner, "cloud_registration", "Completed")
	doc.db_set(
		{
			"cloud_link_status": result["status"],
			"cloud_setup_url": result.get("url"),
			"cloud_link_error": None,
		}
	)


def retry_cloud_links() -> None:
	"""Hourly: asks again for the links Frappe Cloud hasn't created yet."""
	if not is_cloud_enabled():
		return

	for name in frappe.get_all(
		"Customer Project",
		filters={"status": ["in", ("Hired", "Completed")], "cloud_link_status": ["in", RETRY_STATUSES]},
		pluck="name",
	):
		try:
			request_cloud_link(name)
			frappe.db.commit()  # nosemgrep: one project's failure shouldn't undo the others
		except Exception:
			frappe.db.rollback()
			frappe.log_error(title=f"Could not request the Frappe Cloud link for {name}")


def sync_cloud_links() -> None:
	"""Every 10 minutes: reads back what customers answered on Frappe Cloud, and the links that
	ended there, so step 2 shows where the link stands."""
	if not is_cloud_enabled():
		return

	names = frappe.get_all(
		"Customer Project", filters={"cloud_link_status": ["in", SYNCED_STATUSES]}, pluck="name"
	)
	client = _get_cloud_client() if names else None
	for name in names:
		try:
			result = client.post_api("central.api.connect.get_partner_link", {"engagement_id": name})
		except Exception:
			frappe.log_error(title=f"Could not read the Frappe Cloud link for {name}")
			continue
		_record_link_status(name, result["status"])
		frappe.db.commit()  # nosemgrep: one project's failure shouldn't undo the others


def _record_link_status(project: str, status: str) -> None:
	values = {"cloud_link_status": status}
	# The setup link works only while it waits for the customer.
	if status != "Requested":
		values["cloud_setup_url"] = None
	frappe.db.set_value("Customer Project", project, values)


def _ensure_registration(client, partner: str) -> bool:
	"""Whether Frappe Cloud already knows the partner's team. If not, asks the partner's admin to
	pick it, at most once per registration link. Partners listed before onboarding asked for
	Frappe Cloud get here on their first hire."""
	row = frappe.db.get_value(
		"Partner", partner, ["partner_name", "cloud_registration", "cloud_registration_sent_on"], as_dict=True
	)
	if row.cloud_registration == "Completed":
		return True
	if row.cloud_registration_sent_on and row.cloud_registration_sent_on > add_days(
		now_datetime(), -REGISTRATION_RESEND_DAYS
	):
		return False

	admin = _get_partner_admin(partner)
	if not admin:
		frappe.throw(_("{0} has no admin to register on Frappe Cloud.").format(row.partner_name))

	email = frappe.db.get_value("User", admin, "email") or admin
	url = _request_registration(client, partner, email)
	if url:
		_send_registration_email(email, row.partner_name, url)
	return not url


def _request_registration(client, partner: str, email: str, return_url: str | None = None) -> str | None:
	"""Asks Frappe Cloud for the link where `email` picks the partner's team. None when Frappe
	Cloud already knows the team."""
	result = client.post_api(
		"central.api.connect.register_partner",
		{
			"connect_partner_id": partner,
			"partner_name": frappe.db.get_value("Partner", partner, "partner_name"),
			"owner_email": email,
			"return_url": return_url,
		},
	)
	if result["status"] == "Completed":
		frappe.db.set_value("Partner", partner, "cloud_registration", "Completed")
		return None

	frappe.db.set_value(
		"Partner", partner, {"cloud_registration": "Pending", "cloud_registration_sent_on": now_datetime()}
	)
	return result["url"]


def get_cloud_account_status() -> dict:
	"""Partner onboarding's Frappe Cloud step for the caller's partner. While Connect doesn't know
	the team yet it asks Frappe Cloud, so an admin back from picking it sees the step done."""
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()
	if not is_cloud_enabled():
		return {"enabled": False, "completed": False}
	if frappe.db.get_value("Partner", partner, "cloud_registration") == "Completed":
		return {"enabled": True, "completed": True}

	try:
		result = _get_cloud_client().post_api(
			"central.api.connect.get_partner_registration", {"connect_partner_id": partner}
		)
	except Exception:
		frappe.log_error(title=f"Could not read the Frappe Cloud registration for {partner}")
		return {"enabled": True, "completed": False}

	if result["status"] == "Completed":
		frappe.db.set_value("Partner", partner, "cloud_registration", "Completed")
	return {"enabled": True, "completed": result["status"] == "Completed"}


def connect_cloud_account() -> dict:
	"""Partner onboarding's Connect Frappe Cloud: the link where the partner's admin picks or
	creates the partner's Frappe Cloud team now. No link when Frappe Cloud already knows it."""
	from connect.partner.doctype.partner.partner import _my_partner

	partner = _my_partner()
	user = frappe.session.user
	if not _is_partner_admin(partner, user):
		frappe.throw(_("Only your company's admin can connect Frappe Cloud."), frappe.PermissionError)

	email = frappe.db.get_value("User", user, "email") or user
	url = _request_registration(_get_cloud_client(), partner, email, get_url(ONBOARDING_PATH))
	return {"completed": not url, "url": url}


def _send_registration_email(email: str, partner_name: str, url: str) -> None:
	frappe.sendmail(
		recipients=[email],
		subject=_("Set up {0} on Frappe Cloud").format(partner_name),
		message=(
			f"<p>{_('A customer hired {0} on Frappe Connect.').format(escape_html(partner_name))}</p>"
			f"<p>{_('Pick the Frappe Cloud team that is {0}, so your customers can add you to their accounts.').format(escape_html(partner_name))}</p>"
			f"<p><a href='{url}'>{_('Pick your Frappe Cloud team')}</a></p>"
			f"<p>{_('The link works only for {0} and stays open for {1} days.').format(escape_html(email), REGISTRATION_RESEND_DAYS)}</p>"
		),
	)
