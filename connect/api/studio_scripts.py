import frappe

# Studio's own get_studio_page_scripts is @frappe.whitelist() with no allow_guest, so a
# logged-out visitor gets 403 for it. Without the bundle, the renderer fetches page
# scripts over that endpoint at runtime — so a published allow_guest page renders its
# blocks but none of its script state, and every repeater falls back to "No data".
#
# This override lets guests fetch scripts, but only for pages they are already allowed
# to read: published AND allow_guest. Everything else is dropped from their copy, so the
# endpoint can't be used to enumerate private pages. Signed-in users get it unchanged.


@frappe.whitelist(allow_guest=True)
def get_studio_page_scripts(frappe_app: str) -> list[dict]:
	from studio.api import get_studio_page_scripts as studio_page_scripts

	scripts = studio_page_scripts(frappe_app)
	if frappe.session.user != "Guest":
		return scripts

	public = set(
		frappe.get_all(
			"Studio Page",
			filters={"published": 1, "allow_guest": 1},
			pluck="name",
		)
	)
	return [script for script in scripts if script.get("page_name") in public]


@frappe.whitelist(allow_guest=True)
def get_custom_vue_components(frappe_app: str) -> list[dict]:
	"""Same story for the custom .vue components a page's blocks render (e.g. WorldMapPins
	on Find Partners). Without these a guest's page renders every custom block as missing.

	Nothing here is per-page: the list is the app's own component sources, which ship to
	every visitor in a built bundle anyway, so guests get it unfiltered.
	"""
	from studio.api import get_custom_vue_components as studio_custom_vue_components

	return studio_custom_vue_components(frappe_app)
