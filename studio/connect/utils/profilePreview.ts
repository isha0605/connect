// Preview for the partner's Profile builder: the builder keeps its unsaved profile in this
// browser, and the public partner profile (?preview=1) shows it over the saved record, live as
// the partner types in the other tab. Nothing leaves the browser until they press Save.

const KEY_PREFIX = "connect:profile-preview:"

export function writePreview(partner, draft) {
	try {
		window.localStorage.setItem(KEY_PREFIX + partner, JSON.stringify(draft))
	} catch {
		// Storage blocked: the preview shows the saved profile instead.
	}
}

export function readPreview(partner) {
	try {
		return JSON.parse(window.localStorage.getItem(KEY_PREFIX + partner) || "null")
	} catch {
		return null
	}
}

// Calls back with the new draft whenever the builder's tab changes it.
export function onPreviewChange(partner, callback) {
	const listener = (event) => {
		if (event.key === KEY_PREFIX + partner) callback(readPreview(partner))
	}
	window.addEventListener("storage", listener)
	return () => window.removeEventListener("storage", listener)
}

// The saved record (get_partner_document's shape) with the builder's draft laid over it.
export function withPreview(doc, draft) {
	const { founder, apps, migrations, industries, photos, success_stories, ...fields } = draft
	const others = (doc.team || []).filter((member) => !member.is_founder)
	return {
		...doc,
		...fields,
		apps: (apps || []).map((app) => ({ app })),
		migrations: (migrations || []).map((path) => ({ migration_path: path })),
		industries: (industries || []).map((industry) => ({ industry })),
		industry_badges: industryBadges(industries || [], success_stories || []),
		display_industries: industries || [],
		team: founder?.member_name ? [{ ...founder, is_founder: 1 }, ...others] : others,
		photos: photos || [],
		// Stories are only read here (they're written on frappe.io), so each keeps its cleaned logo.
		success_stories: success_stories || [],
	}
}

// The same tick rule as connect.partner.industries.industry_badges, for the unsaved draft.
const STORIES_FOR_TICK = 2

function industryBadges(industries, stories) {
	return industries.map((industry) => {
		const count = stories.filter((story) => story.category === industry).length
		return { industry, stories: count, verified: count >= STORIES_FOR_TICK }
	})
}
