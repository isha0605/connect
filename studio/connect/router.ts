// Connect's additions to Studio's router. A signed-out person who opens a page that needs signing
// in goes to Connect's landing page, or, for a link to one thing (a thread, a project, a lead), to
// Connect's sign-in page, which brings them back to it. Never to Frappe's /login, which is Desk's.
// Studio adds its own guest guard after `setup`, so this one runs first.

import { signInUrl } from "@app/utils/signIn"

const LANDING_PAGE = "/"

// A link to one record: it carries a query (?thread=…) or names the record in its path (/lead/…).
function isDeepLink(to) {
	return Object.keys(to.query).length > 0 || to.path.split("/").filter(Boolean).length > 1
}

function sendGuestToConnect(to) {
	// A guest's page list leaves out pages that need signing in, so those show as not found.
	if (!window.is_guest || !to.meta.notFound) return true
	if (!isDeepLink(to)) return LANDING_PAGE

	window.location.href = signInUrl({ screen: "login", next: `/${window.app_route}${to.fullPath}` })
	return false
}

export default {
	setup(router) {
		router.beforeEach(sendGuestToConnect)
	},
}
