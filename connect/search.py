from frappe.search.sqlite_search import SQLiteSearch


class PartnerSearch(SQLiteSearch):
	"""FTS5-backed relevance search over Partner — replaces the old MariaDB-only
	FULLTEXT + difflib fuzzy fallback in partner.py, so search keeps working (with
	built-in spelling correction) regardless of the site's DB backend. Registered
	in hooks.py's `sqlite_search` list, so Frappe core builds/rebuilds the index
	automatically (after_migrate, a 3-hourly cron check) and keeps it live via
	doc_events on Partner insert/update/delete — no manual indexing calls needed.
	"""

	INDEX_NAME = "connect_partner_search.db"

	INDEX_SCHEMA = {
		# "content" is aliased to partner_name (see INDEXABLE_DOCTYPES below) rather
		# than description, because SQLiteSearch silently drops a document from the
		# index if its content field is empty — and part of the Partner directory is
		# bulk-imported with no description yet (see the is_featured comment in
		# search_partners). partner_name is never empty, so no partner can vanish
		# from search purely for being sparsely profiled; tagline/description/
		# industry/city/country are still indexed as plain (empty-safe) text fields.
		"text_fields": ["title", "content", "tagline", "description", "industry", "city", "country"],
		"tokenizer": "unicode61 remove_diacritics 2",
	}

	INDEXABLE_DOCTYPES = {
		"Partner": {
			"fields": [
				"name",
				{"title": "partner_name"},
				{"content": "partner_name"},
				"tagline", "description", "industry", "city", "country",
			],
		},
	}

	def get_search_filters(self):
		# Partner search is public (allow_guest) — there's no per-user access to
		# restrict. Structured filtering (industry/region/tier/child-table
		# membership/etc.) already happens in SQL before ranking even starts (see
		# search_partners); the caller passes the resulting candidate names in as
		# a `name` filter to search() directly.
		return {}
