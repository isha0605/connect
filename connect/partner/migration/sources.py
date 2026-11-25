import json
from collections.abc import Iterable, Iterator

import frappe
import requests
from frappe import _
from frappe.frappeclient import FrappeClient, FrappeException
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Values per "in" filter: the filter goes in the request's web address, which has a length limit.
VALUES_PER_REQUEST = 100
# Frappe's client waits forever by default: a site that stops answering would hold a step for hours.
REQUEST_TIMEOUT_SECONDS = 60
# A busy or restarting site gets a few more tries, waiting 2, 4, 8 and 16 seconds, or as it asks.
RETRIES = Retry(
	total=4,
	backoff_factor=2,
	status_forcelist=(429, 502, 503, 504),
	allowed_methods=("GET",),
	respect_retry_after_header=True,
)


class _PatientAdapter(HTTPAdapter):
	"""Gives every request a time limit, unless the caller sets its own."""

	def send(self, request, **kwargs):
		kwargs["timeout"] = kwargs.get("timeout") or REQUEST_TIMEOUT_SECONDS
		return super().send(request, **kwargs)


class SourceError(Exception):
	"""A source site can't be read: it can't be reached, or it refuses the key."""


def get_frappe_io_client() -> FrappeClient:
	"""A client for frappe.io with the read-only key in Integration Settings."""
	settings = frappe.get_cached_doc("Integration Settings")
	if not (
		settings.frappe_io_enabled
		and settings.frappe_io_site_url
		and settings.frappe_io_api_key
		and settings.frappe_io_api_secret
	):
		frappe.throw(_("Set up the frappe.io connection in Integration Settings first."))

	return FrappeClient(
		settings.frappe_io_site_url,
		api_key=settings.frappe_io_api_key,
		api_secret=settings.get_password("frappe_io_api_secret"),
	)


def make_patient(client: FrappeClient) -> FrappeClient:
	"""The client, with a time limit and retries on every request it makes, file downloads included.
	The migration only reads, so trying a request again is safe."""
	adapter = _PatientAdapter(max_retries=RETRIES)
	client.session.mount("https://", adapter)
	client.session.mount("http://", adapter)
	return client


def read(source, client: FrappeClient) -> dict[str, list[dict]]:
	"""The records `source` migrates, read from its site, by DocType."""
	try:
		return source.fetch_rows(client)
	except (requests.RequestException, FrappeException, ValueError) as error:
		raise SourceError(_("Couldn't read {0}: {1}").format(source.SOURCE, error)) from error


def get_all(client: FrappeClient, doctype: str, fields: list[str], filters=None) -> list[dict]:
	"""Every record of a DocType that matches, oldest first, as the source made them."""
	return client.get_list(
		doctype, fields=fields, filters=filters, order_by="creation asc", limit_page_length=0
	)


def get_child_rows(
	client: FrappeClient, parent_doctype: str, child_doctype: str, parentfield: str, parents: Iterable[str]
) -> list[dict]:
	"""The rows of one table field of these parents, in their order. Frappe reads a child DocType
	only through frappe.client.get_list, which checks the reader may read the parent DocType."""
	rows = []
	for chunk in _chunks(parents):
		filters = [["parentfield", "=", parentfield], ["parent", "in", chunk]]
		rows += client.get_api(
			"frappe.client.get_list",
			{
				"doctype": child_doctype,
				"parent": parent_doctype,
				"fields": json.dumps(["*"]),
				"filters": json.dumps(filters),
				"order_by": "idx asc",
				"limit_page_length": 0,
			},
		)
	return rows


def _chunks(values: Iterable[str]) -> Iterator[list[str]]:
	values = sorted(set(values))
	for start in range(0, len(values), VALUES_PER_REQUEST):
		yield values[start : start + VALUES_PER_REQUEST]
