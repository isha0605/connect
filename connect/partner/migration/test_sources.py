# Copyright (c) 2026
# See license.txt

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
import requests
from frappe.frappeclient import FrappeException
from frappe.tests import IntegrationTestCase
from requests.adapters import HTTPAdapter

from connect.partner.migration import frappe_io, press
from connect.partner.migration.sources import (
	SourceError,
	get_frappe_io_client,
	get_where_in,
	make_patient,
	read,
)


class FakeClient:
	"""Answers list reads from records in memory, as a Frappe site's API would, and counts requests."""

	def __init__(self, records: dict[str, list[dict]]):
		self.records = records
		self.requests = 0

	def get_list(self, doctype, fields, filters=None, order_by=None, limit_page_length=None):
		self.requests += 1
		rows = [row for row in self.records.get(doctype, []) if _matches(row, filters)]
		if fields == ["*"]:
			return [dict(row) for row in rows]
		return [{field: row.get(field) for field in fields} for row in rows]

	def get_api(self, method, params):
		"""frappe.client.get_list, the only way to read a child DocType's rows."""
		assert (method, params["parent"]) == ("frappe.client.get_list", "Partner")
		self.requests += 1
		rows = self.records.get(params["doctype"], [])
		return sorted((row for row in rows if _matches(row, json.loads(params["filters"]))), key=_idx)


def _idx(row: dict) -> int:
	return row["idx"]


def _matches(row: dict, filters) -> bool:
	if isinstance(filters, dict):
		filters = [
			[field, *(value if isinstance(value, list) else ["=", value])] for field, value in filters.items()
		]
	for field, operator, value in filters or []:
		if operator == "=" and row.get(field) != value:
			return False
		if operator == "is" and not row.get(field):
			return False
		if operator == "in" and row.get(field) not in value:
			return False
	return True


class TestFrappeIoSource(IntegrationTestCase):
	def test_only_enabled_partners_are_read_with_their_table_rows_in_order(self):
		client = FakeClient(
			{
				"Partner": [
					{"name": "A/B Partner LLP", "enabled": 1},
					{"name": "Disabled LLP", "enabled": 0},
				],
				"Partner Industry Type": [
					{
						"parent": "A/B Partner LLP",
						"parentfield": "industry_type",
						"idx": 2,
						"industry": "Retail",
					},
					{
						"parent": "A/B Partner LLP",
						"parentfield": "industry_type",
						"idx": 1,
						"industry": "Health",
					},
					{
						"parent": "Disabled LLP",
						"parentfield": "industry_type",
						"idx": 1,
						"industry": "Retail",
					},
				],
				"Partner Countries Served": [
					{
						"parent": "A/B Partner LLP",
						"parentfield": "custom_countries_served",
						"idx": 1,
						"country": "India",
					}
				],
			}
		)

		(partner,) = read(frappe_io, client)["Partner"]

		self.assertEqual(partner["name"], "A/B Partner LLP")
		self.assertEqual([row["industry"] for row in partner["industry_type"]], ["Health", "Retail"])
		self.assertEqual([row["country"] for row in partner["custom_countries_served"]], ["India"])
		# The partners, then one request for each table.
		self.assertEqual(client.requests, 3)

	def test_a_missing_connection_stops_before_anything_is_read(self):
		with self.assertRaisesRegex(frappe.ValidationError, "frappe.io connection"):
			get_frappe_io_client()


class TestPressSource(IntegrationTestCase):
	def setUp(self):
		client = FakeClient(
			{
				"Team": [
					{
						"name": "team-partner",
						"user": "x@a.test",
						"partner_email": "a@a.test",
						"billing_name": "A",
					},
					{"name": "team-by-owner", "user": "b@b.test", "partner_email": None},
					{"name": "team-applying", "user": "c@c.test", "partner_email": None},
					{"name": "team-rejected", "user": "d@d.test", "partner_email": None},
					{"name": "team-customer", "user": "e@e.test", "partner_email": None},
				],
				"Partner Onboarding": [
					{"name": "PONB-1", "team": "team-applying", "status": "Pending Review"},
					{"name": "PONB-2", "team": "team-rejected", "status": "Rejected"},
					{"name": "PONB-3", "team": "team-partner", "status": "Approved"},
					{"name": "PONB-4", "team": None, "status": "Pending Review"},
				],
				"Partner Certificate": [
					{"name": "PCERT-1", "team": "team-partner"},
					{"name": "PCERT-2", "team": "team-customer"},
				],
				"Partner Audit": [{"name": "ADT-1", "partner_team": "team-by-owner"}],
				"Partner Non Conformance": [{"name": "NC-1", "partner_team": "team-customer"}],
			}
		)
		self.records = read(press, client, {"a@a.test", "b@b.test"})

	def test_partner_teams_by_either_email_and_applying_teams_are_read_with_three_columns(self):
		teams = sorted(self.records["Team"], key=lambda team: team["name"])

		self.assertEqual(
			teams,
			[
				{"name": "team-applying", "user": "c@c.test", "partner_email": None},
				{"name": "team-by-owner", "user": "b@b.test", "partner_email": None},
				{"name": "team-partner", "user": "x@a.test", "partner_email": "a@a.test"},
			],
		)

	def test_only_onboardings_pending_review_with_a_team_are_read(self):
		self.assertEqual([row["name"] for row in self.records["Partner Onboarding"]], ["PONB-1"])

	def test_only_the_read_teams_records_are_read(self):
		self.assertEqual([row["name"] for row in self.records["Partner Certificate"]], ["PCERT-1"])
		self.assertEqual([row["name"] for row in self.records["Partner Audit"]], ["ADT-1"])
		self.assertEqual(self.records["Partner Non Conformance"], [])


class TestReadingByValues(IntegrationTestCase):
	def test_values_are_sent_100_at_a_time(self):
		names = [f"team-{number}" for number in range(250)]
		client = FakeClient({"Team": [{"name": name} for name in names]})

		rows = get_where_in(client, "Team", ["name"], "name", names)

		self.assertEqual(sorted(row["name"] for row in rows), sorted(names))
		self.assertEqual(client.requests, 3)


class TestUnreadableSource(IntegrationTestCase):
	def test_a_refused_or_unreachable_site_names_the_source(self):
		for error in (FrappeException("PermissionError"), requests.ConnectionError("no route")):
			client = FakeClient({})
			client.get_list = lambda *args, error=error, **kwargs: (_ for _ in ()).throw(error)

			with self.assertRaisesRegex(SourceError, "Couldn't read Press"):
				read(press, client, set())


class TestPatientClient(IntegrationTestCase):
	def test_every_request_has_a_time_limit_and_a_few_retries(self):
		client = make_patient(SimpleNamespace(session=requests.Session()))
		adapter = client.session.get_adapter("https://frappe.io/api/resource/Partner")

		with patch.object(HTTPAdapter, "send") as send:
			adapter.send(requests.Request("GET", "https://frappe.io").prepare())

		self.assertEqual(send.call_args.kwargs["timeout"], 60)
		self.assertEqual(adapter.max_retries.total, 4)
		self.assertIn(429, adapter.max_retries.status_forcelist)
