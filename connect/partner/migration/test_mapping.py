# Copyright (c) 2026
# See license.txt

from frappe.tests import IntegrationTestCase

from connect.partner.migration.checks import get_problems
from connect.partner.migration.mapping import Mapping, Table

COUNTRIES = Mapping(
	"frappe.io", "Partner Countries Served", "Partner Served Country", fields={"country": "country"}
)
PARTNER = Mapping(
	"frappe.io",
	"Partner",
	"Partner",
	fields={"company_name": "company_name", "partner_type": "tier", "partner_website": "website"},
	convert={"tier": {"Old Gold": "Gold"}, "website": lambda url: f"https://{url}"},
	files={"logo": "logo"},
	tables={"custom_countries_served": Table("served_countries", COUNTRIES)},
	read_by_rules=frozenset({"user"}),
)


class TestMapping(IntegrationTestCase):
	def test_values_are_renamed_and_converted(self):
		row = {
			"name": "P-1",
			"company_name": "Acme",
			"partner_type": "Old Gold",
			"partner_website": "acme.test",
			"custom_countries_served": [{"name": "row-1", "country": "India"}],
		}

		self.assertEqual(
			PARTNER.get_values(row),
			{
				"company_name": "Acme",
				"tier": "Gold",
				"website": "https://acme.test",
				"served_countries": [{"country": "India"}],
			},
		)

	def test_a_field_missing_from_the_source_is_left_out_so_it_blanks_nothing(self):
		self.assertEqual(PARTNER.get_values({"company_name": "Acme"}), {"company_name": "Acme"})

	def test_files_are_only_noted(self):
		row = {"company_name": "Acme", "logo": "/files/acme.png"}

		self.assertNotIn("logo", PARTNER.get_values(row))
		self.assertEqual(PARTNER.get_file_urls(row), {"logo": "/files/acme.png"})

	def test_only_the_fields_it_uses_are_read_from_the_source(self):
		self.assertEqual(
			PARTNER.get_source_fields(),
			[
				"name",
				"creation",
				"company_name",
				"partner_type",
				"partner_website",
				"logo",
				"custom_countries_served",
				"user",
			],
		)


class TestProblems(IntegrationTestCase):
	def test_clean_values_have_no_problems(self):
		values = {"company_name": "Acme", "tier": "Gold", "country": "India", "team_size": "11-50"}

		self.assertEqual(get_problems("Partner", values, is_new=True), [])

	def test_each_bad_value_is_named(self):
		values = {
			"company_name": "Acme",
			"tier": "Platinum",
			"country": "India",
			"team_size": "lots",
			"listed_on": "someday",
			"pmm_level": "high",
			"nickname": "A",
			"served_countries": [{"country": "Atlantis"}],
		}

		problems = [str(problem) for problem in get_problems("Partner", values, is_new=True)]

		self.assertEqual(len(problems), 6, problems)
		for expected in ("Platinum", "lots", "someday", "high", "no field nickname", "Atlantis"):
			self.assertTrue(any(expected in problem for problem in problems), expected)

	def test_a_new_record_needs_its_required_fields(self):
		problems = [
			str(problem) for problem in get_problems("Partner", {"company_name": "Acme"}, is_new=True)
		]

		self.assertEqual(
			sorted(problems),
			["Partner.country is required but blank", "Partner.tier is required but blank"],
		)

	def test_an_update_needs_only_the_values_it_sets(self):
		self.assertEqual(get_problems("Partner", {"phone": "123"}, is_new=False), [])

	def test_a_field_the_source_never_required_may_be_blank(self):
		problems = get_problems(
			"Partner",
			{"company_name": "Acme", "tier": "Gold"},
			is_new=True,
			may_be_blank=frozenset({"country"}),
		)

		self.assertEqual(problems, [])

	def test_formats_frappe_refuses_are_caught_before_saving(self):
		values = {
			"contact_email": "not an email",
			"phone": "call us maybe",
			"website": "javascript:alert(1)",
			"company_name": "A" * 141,
		}

		problems = {problem.field: str(problem) for problem in get_problems("Partner", values, is_new=False)}

		self.assertIn("is not an email address", problems["contact_email"])
		self.assertIn("is not a phone number", problems["phone"])
		self.assertIn("is not a web address", problems["website"])
		self.assertIn("longer than 140 characters", problems["company_name"])

	def test_a_problem_in_a_table_names_its_row(self):
		values = {"served_countries": [{"country": "India"}, {"country": "Atlantis"}]}

		(problem,) = get_problems("Partner", values, is_new=False)

		self.assertEqual((problem.field, problem.row), ("served_countries", 1))
