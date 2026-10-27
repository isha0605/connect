// frappe-ui Avatar's initials theme for a name. Hashed, so the same person or company
// gets the same colour on every page.
const AVATAR_THEMES = ["blue", "green", "amber", "red", "violet"]

export function avatarTheme(key: unknown): string {
	const name = String(key || "")
	let hash = 0
	for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) % AVATAR_THEMES.length
	return AVATAR_THEMES[hash]
}
