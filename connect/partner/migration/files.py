import json
from collections import defaultdict
from urllib.parse import unquote, urlparse

import frappe
import requests
from frappe.frappeclient import FrappeClient
from pypdf.errors import PyPdfError

from connect.partner.migration.report import Report

# Only Frappe's staff and the partner may see these. Logos show in the directory.
PRIVATE_FIELDS = frozenset({"incorporation_certificate", "audit_report", "evidence"})
_SAVEPOINT = "partner_migration_file"


class NotAFileError(Exception):
	"""The site answered with a web page, such as its sign-in page, instead of the file."""


def copy_files(clients: dict[str, FrappeClient]) -> Report:
	"""Copies every file the migration noted for these sources into the Connect record and field it
	belongs to, using each source's client by source name. A field that already has a file is left as it is, so a
	file someone added in Connect is never replaced, and a second run copies only what is missing.
	Each file is committed as soon as it is copied, so a step that stops keeps what it copied."""
	report = Report()
	records = frappe.get_all(
		"Migration Record",
		filters={"file_urls": ["is", "set"], "source": ["in", list(clients)]},
		fields=["source", "target_doctype", "target_name", "file_urls"],
		order_by="creation asc",
	)
	for record in records:
		for fieldname, file_url in json.loads(record.file_urls).items():
			_copy_file(clients[record.source], record, fieldname, file_url, report)
	return report


def get_files_not_copied(sources: list[str]) -> list[str]:
	"""Each noted file of these sources whose Connect field is still empty, for the check. One query
	per DocType."""
	noted = defaultdict(list)
	records = frappe.get_all(
		"Migration Record",
		filters={"file_urls": ["is", "set"], "source": ["in", sources]},
		fields=["target_doctype", "target_name", "file_urls"],
	)
	for record in records:
		noted[record.target_doctype] += [
			(record.target_name, field) for field in json.loads(record.file_urls)
		]

	missing = []
	for doctype, files in noted.items():
		fieldnames = sorted({fieldname for _name, fieldname in files})
		names = list({name for name, _fieldname in files})
		values = {
			row.name: row
			for row in frappe.get_all(doctype, filters={"name": ["in", names]}, fields=["name", *fieldnames])
		}
		# A record deleted since is the check's "gone", not a missing file.
		missing += [
			f"{doctype} {name}: {field}"
			for name, field in files
			if name in values and not values[name].get(field)
		]
	return missing


def _copy_file(client: FrappeClient, record, fieldname: str, file_url: str, report: Report) -> None:
	label = f"{record.target_doctype} {record.target_name}: {fieldname}"
	if not frappe.db.exists(record.target_doctype, record.target_name):
		report.add("files_failed", f"{label}: the record was deleted")
		return
	if frappe.db.get_value(record.target_doctype, record.target_name, fieldname):
		report.add("files_already_there", label)
		return

	frappe.db.savepoint(_SAVEPOINT)
	try:
		copied = _save_file(record, fieldname, file_url, _download(client, file_url))
	# A file that can't be fetched, is over Connect's upload limit, or is a PDF Frappe can't read to
	# check it for scripts, must not stop the others.
	except (requests.RequestException, NotAFileError, frappe.ValidationError, PyPdfError) as error:
		frappe.db.rollback(save_point=_SAVEPOINT)
		report.add("files_failed", f"{label} from {file_url}: {error}")
		return

	frappe.db.set_value(record.target_doctype, record.target_name, fieldname, copied, update_modified=False)
	frappe.db.commit()
	report.add("files_copied", label)


def _download(client: FrappeClient, file_url: str) -> bytes:
	"""The file's content. The source site's key goes only to the source site: a file kept on another
	host is fetched without it."""
	if urlparse(file_url).scheme:
		url = file_url
	else:
		url = f"{client.url.rstrip('/')}/{file_url.lstrip('/')}"

	is_source_site = urlparse(url).netloc == urlparse(client.url).netloc
	response = client.session.get(
		url, headers=client.headers if is_source_site else None, verify=client.verify, timeout=60
	)
	response.raise_for_status()
	# A site that wants the visitor to sign in answers with its sign-in page, and a status of OK.
	is_page = "text/html" in response.headers.get("Content-Type", "")
	if is_page and not urlparse(url).path.lower().endswith((".html", ".htm")):
		raise NotAFileError("the site sent a web page, not the file: check the key can read it")
	return response.content


def _save_file(record, fieldname: str, file_url: str, content: bytes) -> str:
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": unquote(urlparse(file_url).path.rsplit("/", 1)[-1]) or fieldname,
			"content": content,
			"attached_to_doctype": record.target_doctype,
			"attached_to_name": record.target_name,
			"attached_to_field": fieldname,
			"is_private": int(fieldname in PRIVATE_FIELDS),
		}
	)
	file.insert(ignore_permissions=True)  # The migration is a system job, not a user.
	return file.file_url
