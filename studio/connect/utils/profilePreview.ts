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
	const { founder, apps, migrations, photos, success_stories, ...fields } = draft
	const others = (doc.team || []).filter((member) => !member.is_founder)
	return {
		...doc,
		...fields,
		apps: (apps || []).map((app) => ({ app })),
		migrations: (migrations || []).map((path) => ({ migration_path: path })),
		team: founder?.member_name ? [{ ...founder, is_founder: 1 }, ...others] : others,
		photos: photos || [],
		success_stories: (success_stories || []).map((story) => ({
			...story,
			client_logo_display: story.client_logo,
		})),
	}
}
