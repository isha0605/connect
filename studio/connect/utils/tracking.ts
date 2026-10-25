// Product analytics for the customer pages. Pulse's client, loaded once per tab, sends a
// pageview for each page and how long the page was looked at. Cookieless: nothing is kept
// in the browser. Analytics must never break a page, so every failure is swallowed.

import { call } from "frappe-ui"

const APP = "connect"
const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign"]
// Under a second is a bounce, not reading. Past 30 minutes the tab was most likely left open,
// and one forgotten tab would outweigh many real visits.
const MIN_PAGE_SECONDS = 1
const MAX_PAGE_SECONDS = 30 * 60

let started = false
let client = null
// the page being looked at: { route, visibleMs, visibleSince } (visibleSince is null while hidden)
let page = null

// Call from each customer page's setup(). The first call starts tracking for the whole tab,
// and the router hook it adds follows every page after it.
export function startTracking(context) {
	if (started || typeof window === "undefined") return
	started = true
	call("connect.api.analytics.get_config")
		.then((config) => config?.enabled && loadClient(config, context.router))
		.catch(() => {})
}

export function track(event, properties = {}) {
	client?.capture(event, APP, properties)
}

// This visitor's id for today, sent with sign-up so the visit before it joins their account
export function visitorId() {
	return client?.getDistinctId?.() || ""
}

async function loadClient(config, router) {
	const { PulseClient } = await import(/* @vite-ignore */ config.client_url)
	client = new PulseClient({
		host: config.host,
		apiKey: config.key,
		site: config.site,
		enabled: true,
		getContext: () => ({ user: config.user, team: config.team }),
	})
	// Added before init(): the client sends its queue when the tab hides, and the time on
	// the page has to be in that queue by then.
	document.addEventListener("visibilitychange", onVisibilityChange)
	await client.init()
	followPages(router)
}

function followPages(router) {
	router.isReady().then(() => enterPage(router.currentRoute.value, landingDetails(router.currentRoute.value)))
	router.afterEach((to, from) => {
		if (to.path === from.path) return
		leavePage()
		enterPage(to)
	})
}

function enterPage(to, details = {}) {
	const route = routePattern(to)
	// Studio can run setup() before the first navigation lands, so both hooks may see it
	if (page?.route === route) return
	page = { route, visibleMs: 0, visibleSince: Date.now() }
	track("pageview", { route, ...details })
}

function onVisibilityChange() {
	if (!page) return
	if (document.visibilityState === "hidden") leavePage()
	else page.visibleSince = Date.now()
}

// Sends how long this page was visible since it was entered or last sent, then starts the
// count again: a tab that's hidden and shown again sends a second page_left for the same page.
function leavePage() {
	if (!page) return
	if (page.visibleSince) page.visibleMs += Date.now() - page.visibleSince
	page.visibleSince = null

	const seconds = Math.min(Math.round(page.visibleMs / 1000), MAX_PAGE_SECONDS)
	page.visibleMs = 0
	if (seconds >= MIN_PAGE_SECONDS) track("page_left", { route: page.route, seconds })
}

// Where the visit came from. Only the first page has it: later pages are moves inside Connect.
function landingDetails(to) {
	const details = {
		referrer: document.referrer || null,
		timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
	}
	for (const key of UTM_KEYS) {
		if (to.query?.[key]) details[key] = String(to.query[key])
	}
	return details
}

// "/partner-profile-redesign/:partner_id", not one route per partner
function routePattern(to) {
	return to.matched?.[to.matched.length - 1]?.path || to.path
}
