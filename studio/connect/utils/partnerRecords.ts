// What a partner's lead and customer pages share: dates, follow-up and activity rows, notes,
// and the meeting invite form. The records themselves come from connect.api.leads and
// connect.api.partner_customers.

const DAY = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" })
export const shortDate = (iso) => DAY.format(new Date(iso))

// Today's messages show the time, older ones the date, as Frappe CRM's lists do.
export function clockOrDate(time) {
	const date = new Date(time)
	return new Date().toDateString() === date.toDateString()
		? date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()
		: date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

export function timeAgo(time) {
	const minutes = Math.round((Date.now() - time) / 60000)
	const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" })
	if (minutes < 60) return format.format(-Math.max(minutes, 1), "minute")
	if (minutes < 60 * 24) return format.format(-Math.round(minutes / 60), "hour")
	if (minutes < 60 * 24 * 30) return format.format(-Math.round(minutes / 1440), "day")
	if (minutes < 60 * 24 * 365) return format.format(-Math.round(minutes / 43200), "month")
	return format.format(-Math.round(minutes / 525600), "year")
}

// Frappe sends "2026-10-30 20:16:18.138995"; Safari only parses it with a "T".
export const toTime = (value) => (value ? new Date(String(value).replace(" ", "T")).getTime() : 0)

export async function copyText(text, toast, done) {
	try {
		await navigator.clipboard.writeText(text)
		toast.success(done)
	} catch {
		toast.error("Couldn't copy. Select the text and copy it instead.")
	}
}

// ── Follow-ups and activity ─────────────────────────────────────────────────
export const FOLLOW_UP_ICONS = { Call: "lucide-phone", Demo: "lucide-presentation", Email: "lucide-mail", Meeting: "lucide-users" }
export const FOLLOW_UP_MODES = Object.keys(FOLLOW_UP_ICONS).map((mode) => ({ label: mode, value: mode }))
const ACTIVITY_ICONS = { created: "lucide-sparkles", change: "lucide-pencil", note: "lucide-link" }

// Consecutive changes by one person fold into one entry with "Show +N changes".
function groupActivity(entries) {
	const groups = []
	for (const entry of entries) {
		const last = groups.at(-1)
		if (entry.kind === "change" && last?.kind === "change" && last.by === entry.by) last.rest.push(entry)
		else groups.push({ ...entry, rest: [] })
	}
	return groups
}

const describe = (entry) =>
	entry.kind === "change" ? { verb: "changed ", field: entry.field, from: entry.from, to: entry.to } : { verb: entry.text }

// The timeline's rows; `expanded` holds the group ids whose folded changes are shown.
export function activityRows(entries, expanded) {
	const groups = groupActivity(entries)
	return groups.map((group, index) => {
		const isOpen = Boolean(expanded[group.id])
		const shown = [group, ...(isOpen ? group.rest : [])]
		const count = group.rest.length
		return {
			id: group.id,
			icon: ACTIVITY_ICONS[group.kind],
			isLast: index === groups.length - 1,
			lines: shown.map((entry) => ({ id: entry.id, by: entry.by, ago: timeAgo(entry.at), ...describe(entry) })),
			toggleLabel: count ? `${isOpen ? "Hide" : "Show"} +${count} ${count === 1 ? "change" : "changes"} from ${group.by}` : "",
		}
	})
}

// Log a follow-up: the dialog's form, starting today with a call to `contact`.
export const TODAY = new Date().toISOString().slice(0, 10)
export const emptyFollowUp = (contact = "") => ({ date: TODAY, mode: "Call", spokeTo: contact, notes: "" })

// ── Saved records (connect.partner.doctype.partner_customer.customer_records) ──
// The same shapes as the sample ones above, so a lead's and a customer's tabs read them alike.
export const toActivityEntries = (activity) => activity.map((entry) => ({ ...entry, at: toTime(entry.at) }))

export const toNoteRows = (notes) =>
	notes.map((note) => ({ id: note.id, text: note.text, byName: note.by_name || note.by, time: clockOrDate(toTime(note.at)) }))

export const toFollowUpRows = (followUps) => followUps.map((followUp) => (followUp.meeting_link ? toInviteRow(followUp) : toLoggedRow(followUp)))

const toLoggedRow = (followUp) => ({
	id: followUp.id,
	notes: followUp.notes,
	icon: FOLLOW_UP_ICONS[followUp.mode],
	title: followUp.spoke_to ? `${followUp.mode} with ${followUp.spoke_to}` : followUp.mode,
	byName: followUp.by_name || followUp.by,
	dateLabel: shortDate(String(followUp.at).slice(0, 10)),
})

// A meeting invite, with Join while it's still to come.
function toInviteRow(followUp) {
	const startsAt = toTime(followUp.at)
	return {
		...toLoggedRow(followUp),
		icon: "lucide-video",
		title: followUp.title,
		isInvite: true,
		link: followUp.meeting_link,
		dateLabel: meetingTimeLabel(startsAt, followUp.duration_minutes),
		canJoin: startsAt > Date.now(),
	}
}

// "Thu, Nov 6, 3:00 PM · 30 min"
export function meetingTimeLabel(time, minutes) {
	if (!time) return ""
	const when = new Date(time).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
	return minutes ? `${when} · ${minutes} min` : when
}

// Schedule a meeting: the dialog's form, starting tomorrow at 11. frappe-ui's DateTimePicker
// reads and writes "YYYY-MM-DD HH:mm:ss" in the site's time zone, as the server stores it.
export const MEETING_DURATIONS = [15, 30, 45, 60, 90].map((minutes) => ({ label: `${minutes} min`, value: String(minutes) }))

export const isoDay = (date) => {
	const pad = (n) => String(n).padStart(2, "0")
	return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export const emptyMeeting = () => ({
	title: "Intro call",
	startsAt: `${isoDay(new Date(Date.now() + 86400000))} 11:00:00`,
	duration: "30",
	link: "",
	agenda: "",
})

export const meetingValues = (form) => ({
	mode: "Meeting",
	title: form.title.trim(),
	followed_up_on: form.startsAt,
	duration_minutes: Number(form.duration),
	meeting_link: form.link.trim(),
	notes: form.agenda.trim(),
})

// The Log a follow-up dialog's form as log_*_follow_up takes it: today's is now, an earlier one midday.
export function followUpValues(form) {
	const pad = (n) => String(n).padStart(2, "0")
	const now = new Date()
	const clock = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
	return {
		followed_up_on: `${form.date} ${form.date === TODAY ? clock : "12:00:00"}`,
		mode: form.mode,
		spoke_to: form.spokeTo.trim(),
		notes: form.notes.trim(),
	}
}
