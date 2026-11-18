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

// Each page's code is its own hashed file, and a deploy (or a local build) replaces them all. A tab
// opened before it still asks for the old files when it moves to another page, gets a 404, and
// Studio renders the page without its script: empty. Vite reports the failed file, so once the
// navigation lands, reload into that page with the new build.
const RELOADED_AT_KEY = "connect:reloaded-for-new-build"
const RELOAD_GUARD_MS = 10_000
let isPageFileMissing = false

function noticeMissingPageFile() {
	isPageFileMissing = true
}

function reloadIntoNewBuild(to) {
	if (!isPageFileMissing || reloadedRecently()) return
	isPageFileMissing = false
	try {
		sessionStorage.setItem(RELOADED_AT_KEY, String(Date.now()))
	} catch {
		// Without storage the guard can't hold, so don't risk a reload loop.
		return
	}
	window.location.assign(`/${window.app_route}${to.fullPath}`)
}

// A file still missing right after a reload is really gone; reloading again wouldn't help.
function reloadedRecently() {
	try {
		return Date.now() - Number(sessionStorage.getItem(RELOADED_AT_KEY) || 0) < RELOAD_GUARD_MS
	} catch {
		return true
	}
}

export default {
	setup(router) {
		router.beforeEach(sendGuestToConnect)
		window.addEventListener("vite:preloadError", noticeMissingPageFile)
		router.afterEach(reloadIntoNewBuild)
	},
}
