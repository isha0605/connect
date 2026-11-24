// A shared project (Customer Project): its quotes, the hire and going live. Opened as
// /custom-implementation?project=CP-…, which is where the project questions land once shared.

import { computed, h, onScopeDispose, ref } from "vue"
import { formatMoney } from "@app/utils/money"
import { startTracking } from "@app/utils/tracking"
import { tierSeal } from "@app/utils/tierSeal"

export default function setup(context) {
	startTracking(context)
	const { route, router, call, toast } = context

	// Same test Studio's own isEditor() uses. The editor opens pages with no query string,
	// so there the page shows the newest custom-implementation project instead, and lets
	// itself grow to its full height (see `inEditor` in the blocks) so the canvas shows it all.
	const inEditor = window.location.pathname.startsWith("/studio/")

	// Studio's tablet styles stop at 768px, but beside the sidebar and the side panel the quote
	// table needs 1280px. Below that the blocks take their stacked (tablet) layout through this flag.
	const compactQuery = window.matchMedia("(max-width: 1279px)")
	const isCompact = ref(compactQuery.matches)
	const onCompactChange = (event) => (isCompact.value = event.matches)
	compactQuery.addEventListener("change", onCompactChange)
	onScopeDispose(() => compactQuery.removeEventListener("change", onCompactChange))

	// Below 640px a quote row has two columns: the price moves under the city, and Message into More.
	const narrowQuery = window.matchMedia("(max-width: 639px)")
	const isNarrow = ref(narrowQuery.matches)
	const onNarrowChange = (event) => (isNarrow.value = event.matches)
	narrowQuery.addEventListener("change", onNarrowChange)
	onScopeDispose(() => narrowQuery.removeEventListener("change", onNarrowChange))

	let projectName = String(route.query.project || "")
	const project = ref(null)
	const loadError = ref(false)

	function loadProject(name) {
		projectName = name
		call("connect.api.projects.get_project", { name })
			.then((data) => {
				project.value = data
				if (data.status === "Shared") loadQuotes()
			})
			.catch(() => {
				loadError.value = true
			})
	}

	// ---- Hire a Partner: every quote in one list, narrowed by a filter ----
	// Not interested sets a quote aside, with Restore. Partners who got the brief and have not
	// quoted follow the quotes.
	const INVITED_STATUS_LABELS = {
		Awaiting: "",
		"Partner Declined": "Not available to take on new clients",
	}
	const quotes = ref([])
	const quotesLoaded = ref(false)
	function loadQuotes() {
		if (!projectName) return
		call("connect.api.projects.list_quotes", { name: projectName })
			.then((rows) => {
				quotes.value = rows || []
				quotesLoaded.value = true
			})
			.catch(() => {})
	}

	// With no column chosen, quotes keep the order they arrived in, shared ones first: arrival
	// order is neutral and rewards replying promptly, where a tier-first order favours a few firms.
	const SORTS = [
		{ key: null, label: "Arrived first" },
		{ key: "quote", label: "Lowest quote" },
		{ key: "timeline", label: "Shortest timeline" },
		{ key: "partner", label: "Partner A–Z" },
	]
	const COMPARE = {
		partner: (a, b) => (a.company_name || "").localeCompare(b.company_name || ""),
		quote: (a, b) => a.amount - b.amount,
		timeline: (a, b) => a.timeline_weeks - b.timeline_weeks || a.amount - b.amount,
	}
	const sortKey = ref(null)
	const sortLabel = computed(() => SORTS.find((option) => option.key === sortKey.value).label)
	const sortOptions = computed(() =>
		SORTS.map((option) => ({
			label: option.label,
			selected: sortKey.value === option.key,
			onClick: () => (sortKey.value = option.key),
		})),
	)
	// A quote with no date yet sorts after the dated ones.
	const quotedAt = (row) => (row.quoted_on ? new Date(row.quoted_on).getTime() : Infinity)
	const arrivedFirst = (a, b) => quotedAt(a) - quotedAt(b)

	const VIEWS = {
		all: { label: "All quotes", match: (row) => row.status !== "Not Interested" },
		declined: { label: "Not interested", match: (row) => row.status === "Not Interested" },
	}
	const EMPTY_VIEWS = {
		all: { icon: "lucide-inbox", title: "No quotes yet", text: "" },
		declined: { icon: "lucide-ban", title: "No one marked not interested", text: "" },
	}
	const view = ref("all")
	const viewLabel = computed(() => VIEWS[view.value].label)
	const quoteRows = computed(() => {
		const rows = quotes.value.filter((row) => !(row.status in INVITED_STATUS_LABELS))
		return rows.sort(sortKey.value ? COMPARE[sortKey.value] : arrivedFirst)
	})
	const viewOptions = computed(() =>
		Object.entries(VIEWS).map(([key, option]) => ({
			label: option.label,
			selected: view.value === key,
			onClick: () => (view.value = key),
			slots: { suffix: () => h("span", { class: "text-base tabular-nums text-ink-gray-5" }, viewCount(key)) },
		})),
	)
	const viewCount = (key) => String(quoteRows.value.filter(VIEWS[key].match).length)

	const invitedPartners = computed(() =>
		quotes.value
			.filter((row) => row.status in INVITED_STATUS_LABELS)
			.map((row) => ({ ...row, isInvited: true, statusLabel: INVITED_STATUS_LABELS[row.status] })),
	)
	const visibleQuotes = computed(() => quoteRows.value.filter(VIEWS[view.value].match))
	const hasQuoteRows = computed(() => quoteRows.value.length > 0)
	const hasQuotes = computed(() => quotes.value.length > 0)
	const shownQuotes = computed(() => {
		const invited = view.value === "all" ? invitedPartners.value : []
		if (!invited.length) return visibleQuotes.value
		const label = `${invited.length} partner${invited.length === 1 ? "" : "s"} invited`
		return [...visibleQuotes.value, { name: "invited-heading", isHeading: true, label }, ...invited]
	})
	const showQuoteHead = computed(() => visibleQuotes.value.length > 0)
	const emptyView = computed(() => {
		if (!quotesLoaded.value || visibleQuotes.value.length) return null
		const empty = EMPTY_VIEWS[view.value]
		return view.value === "all" ? { ...empty, text: sentLine.value } : empty
	})

	function quoteAmount(row) {
		if (row?.isInvited) return ""
		return formatMoney(row?.amount, row?.currency)
	}
	function quoteTimeline(row) {
		if (row?.isInvited) return ""
		const weeks = row?.timeline_weeks || 0
		return `${weeks} week${weeks === 1 ? "" : "s"}`
	}
	// The line under a partner's name: where they are (their country when no city is on file),
	// and whether they have the customer's details.
	function quoteSubline(row) {
		return row?.statusLabel || row?.city || row?.country || ""
	}

	function setQuoteStatus(row, status, answer = {}) {
		const before = row.status
		row.status = status
		return call("connect.api.projects.set_quote_status", { quote: row.name, status, ...answer })
			.then((counts) => {
				if (project.value) project.value = { ...project.value, ...counts }
			})
			.catch((error) => {
				row.status = before
				toast.error(error?.messages?.[0] || "Couldn't update that quote. Try again.")
				throw error
			})
	}

	// ---- Not interested: the customer says why; the partner is emailed and their lead closes ----
	// The dialog is the confirmation, so there's no Undo: Restore brings a quote back.
	const declineOpen = ref(false)
	const declineRow = ref(null)
	const declineReason = ref("")
	const declineNote = ref("")
	const declining = ref(false)
	const declineReasons = computed(() => (project.value?.not_interested_reasons || []).map((value) => ({ value })))
	const declineTitle = computed(() => `Not interested in ${declineRow.value?.company_name || "this quote"}?`)

	function notInterested(row) {
		declineRow.value = row
		declineReason.value = ""
		declineNote.value = ""
		declineOpen.value = true
	}

	function pickDeclineReason(reason) {
		declineReason.value = reason
	}

	function confirmNotInterested() {
		const row = declineRow.value
		if (!row || !declineReason.value || declining.value) return
		declining.value = true
		setQuoteStatus(row, "Not Interested", { reason: declineReason.value, note: declineNote.value })
			.then(() => {
				declineOpen.value = false
				toast.success(`${row.company_name} will be told you're not interested`)
			})
			.catch(() => {})
			.finally(() => {
				declining.value = false
			})
	}

	function restoreQuote(row) {
		setQuoteStatus(row, "Quoted")
			.then(() => toast.success(`${row.company_name} restored`))
			.catch(() => {})
	}

	function readThread(row) {
		router.push({ path: "/messaging", query: { thread: row.thread } })
	}

	function openPartnerProfile(row) {
		router.push(`/partner-profile-redesign/${encodeURIComponent(row.partner)}`)
	}

	// Message is on every row, so More holds the brochure and Not interested.
	// On a narrow screen Message moves into More too.
	function quoteMenu(row) {
		return [
			isNarrow.value && { label: "Message", icon: "lucide-message-square", onClick: () => readThread(row) },
			row.brochure && { label: "Open brochure", icon: "lucide-file-text", onClick: () => openBrochure(row) },
			row.status !== "Not Interested" && { label: "Not interested", icon: "lucide-ban", onClick: () => notInterested(row) },
		].filter(Boolean)
	}

	// The brochure the partner attached to their quote, in a new tab: it is a private file the
	// customer can open as a member of the chat.
	function openBrochure(row) {
		window.open(row.brochure, "_blank", "noopener")
	}

	// ---- Hire: the shared dialog (HireDialog.vue) agrees the terms, then asks why them ----
	const hireOpen = ref(false)
	const hireRow = ref(null)

	function hirePartner(row) {
		hireRow.value = row
		hireOpen.value = true
	}

	function onHired(data) {
		project.value = data
	}

	// Demo only: partners can't send quotes yet, so this makes every partner the brief went
	// to reply with one (connect.api.projects.simulate_quotes).
	const simulating = ref(false)
	function simulateQuotes() {
		if (simulating.value || !projectName) return
		simulating.value = true
		call("connect.api.projects.simulate_quotes", { name: projectName })
			.then((result) => {
				if (project.value) project.value = { ...project.value, quotes: result.quotes, shortlisted: result.shortlisted }
				toast.success(
					result.sent
						? `${result.sent} partner${result.sent === 1 ? "" : "s"} replied with a quote.`
						: "Every partner has already quoted.",
				)
				loadQuotes()
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't get quotes. Try again."))
			.finally(() => {
				simulating.value = false
			})
	}

	if (projectName) {
		loadProject(projectName)
	} else if (inEditor) {
		call("connect.api.projects.list_projects")
			.then((rows) => {
				const first = (rows || []).find((row) => row.kind === "project")
				if (first) loadProject(first.project)
				else loadError.value = true
			})
			.catch(() => {
				loadError.value = true
			})
	} else {
		loadError.value = true
	}


	const projectTitle = computed(() => project.value?.project_name || "Project")
	const breadcrumbItems = computed(() => [
		{ label: "Projects", route: { path: "/projects" } },
		{ label: projectTitle.value },
	])


	// ---- Choosing a partner, step 1 of 2 ----
	const isShared = computed(() => !!project.value)

	// ---- Hiring: the partner has 7 days to accept the request ----
	// `hired` is set from the request on; `isHired` only once the partner accepts.
	const hired = computed(() => project.value?.hired || null)
	const isAwaitingPartner = computed(() => project.value?.status === "Hiring")
	const isHired = computed(() => !!hired.value?.confirmed)
	const declinedHire = computed(() => project.value?.declined_hire || null)
	// While quotes are listed, the heading, tabs and column header stay put and only the rows scroll.
	const isChoosing = computed(() => isShared.value && !isHired.value && !isAwaitingPartner.value)
	const pinsQuoteList = computed(() => hasQuotes.value && isChoosing.value)
	const stageTitle = computed(() => {
		if (isHired.value) return "Set up hosting"
		if (isAwaitingPartner.value) return `Waiting for ${hired.value?.company_name || "your partner"}`
		return "Choosing a partner"
	})
	const stageStep = computed(() => (isHired.value ? "Step 2 of 2" : "Step 1 of 2"))
	const awaitingLine = computed(() => {
		const name = hired.value?.company_name || "Your partner"
		return `${name} has 7 days to accept or decline your hire request. You'll get a notification either way.`
	})
	const declinedLine = computed(() => {
		if (!declinedHire.value) return ""
		const reason = (declinedHire.value.reason || "").trim().replace(/[.!]+$/, "")
		return `${declinedHire.value.company_name} declined: ${reason}. Choose another partner to work with.`
	})

	const cancelling = ref(false)
	function cancelHireRequest() {
		if (cancelling.value) return
		cancelling.value = true
		call("connect.api.projects.cancel_hire_request", { name: projectName })
			.then((data) => {
				project.value = data
				loadQuotes()
				toast.success(`Hire request to ${data.company_name} cancelled`)
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't cancel the request. Try again."))
			.finally(() => {
				cancelling.value = false
			})
	}

	// ---- Hired: hired, built, live — with the one optional thing to do on the middle step ----
	// The partner marks the project live from their customer record; the customer confirms it.
	const FRAPPE_CLOUD_PARTNER_URL = "https://frappecloud.com/dashboard/settings/partner"
	const FRAPPE_CLOUD_DOCS_URL = "https://docs.frappe.io/cloud"
	const shortDate = (at) => (at ? new Date(at).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : "")
	const isCompleted = computed(() => project.value?.status === "Completed")
	const isLive = computed(() => !!project.value?.live_on && !isCompleted.value)
	const isHostingLinked = computed(() => hired.value?.cloud_link_status === "Active")

	// The path shows from the hire request on: until the partner accepts, its first step is the
	// request itself, and the work after it is still to come.
	const hiredCardTitle = computed(() => {
		const name = hired.value?.company_name || "your partner"
		return isAwaitingPartner.value ? `Hiring ${name}` : `Working with ${name}`
	})

	function hireStepOf(name, current) {
		if (isAwaitingPartner.value) {
			return {
				key: "hired",
				state: "now",
				text: `Hire request sent to ${name}`,
				sub: `Waiting for ${name} to accept. You’ll get a notification either way`,
				date: shortDate(hired.value?.requested_on),
				isRequest: true,
			}
		}
		return {
			key: "hired",
			state: "done",
			text: `You hired ${name}`,
			sub: `Terms agreed. You pay ${name} directly`,
			date: shortDate(current.hired_on),
		}
	}

	const hiredSteps = computed(() => {
		const name = hired.value?.company_name || "your partner"
		const done = isCompleted.value
		const built = isLive.value || done
		const waiting = isAwaitingPartner.value
		const current = project.value || {}
		return [
			hireStepOf(name, current),
			{
				key: "build",
				state: built ? "done" : waiting ? "next" : "now",
				text: built ? "Implementation complete" : "Implementation ongoing",
				sub: done ? `By ${name}` : isHostingLinked.value ? `${name} manages your hosting` : `Let ${name} manage your hosting`,
				hosting: !done && !waiting && !isHostingLinked.value,
				date: built ? shortDate(current.live_on || current.completed_on) : "",
			},
			{
				key: "live",
				state: done ? "done" : isLive.value ? "now" : "next",
				text: done ? "Live" : isLive.value ? `${name} marked it live` : "Going live",
				sub: done
					? "You confirmed it’s working"
					: isLive.value
						? "Check your site, then confirm it’s working"
						: `You confirm once ${name} marks it live`,
				date: done ? shortDate(current.completed_on) : isLive.value ? shortDate(current.live_on) : "",
				isLast: true,
			},
		]
	})

	// Set up opens the customer's one-time Frappe Cloud link once there is one; until then the
	// partner settings page, where the copied code links them.
	function setUpHosting() {
		window.open(hired.value?.central_setup_url || FRAPPE_CLOUD_PARTNER_URL, "_blank", "noopener")
	}

	function openHostingDocs() {
		window.open(FRAPPE_CLOUD_DOCS_URL, "_blank", "noopener")
	}

	function copyReferralCode() {
		const code = hired.value?.referral_code
		if (!code) return
		navigator.clipboard
			.writeText(code)
			.then(() => toast.success("Partner code copied", { description: code }))
			.catch(() =>
				toast.info(`Your partner code is ${code}`, {
					description: "Your browser blocked the clipboard. Copy it from here.",
				}),
			)
	}

	const answeringLive = ref(false)
	function notLiveYet() {
		if (answeringLive.value) return
		answeringLive.value = true
		call("connect.api.projects.not_live_yet", { name: projectName })
			.then((data) => {
				project.value = data
				toast.success(`Note sent to ${hired.value?.company_name || "your partner"}`)
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't send that. Try again."))
			.finally(() => {
				answeringLive.value = false
			})
	}

	const completing = ref(false)
	function markComplete() {
		if (completing.value) return
		completing.value = true
		call("connect.api.projects.complete_project", { name: projectName })
			.then((data) => {
				project.value = data
				if (data.hired && !data.hired.is_reviewed) reviewAskOpen.value = true
				else toast.success("Project completed")
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't complete the project. Try again."))
			.finally(() => {
				completing.value = false
			})
	}

	// A completed project asks for a review of the partner, written in the profile's review form.
	const reviewAskOpen = ref(false)
	function reviewPartner() {
		reviewAskOpen.value = false
		if (hired.value) router.push({ path: `/partner-profile-redesign/${encodeURIComponent(hired.value.partner)}`, query: { review: "1" } })
	}

	// The Partner panel: who was hired, and on what quote.
	const hiredCost = computed(() => (hired.value ? quoteAmount(hired.value) : ""))
	function messagePartner() {
		if (hired.value?.thread) router.push({ path: "/messaging", query: { thread: hired.value.thread } })
	}
	function viewPartnerProfile() {
		if (hired.value) router.push(`/partner-profile-redesign/${encodeURIComponent(hired.value.partner)}`)
	}
	// The Requirement card as partners got it, in the first thread it went to.
	const briefThread = computed(() => project.value?.brief_thread || "")
	function viewBriefInMessages() {
		if (briefThread.value) router.push({ path: "/messaging", query: { thread: briefThread.value } })
	}
	const sentLine = computed(() => {
		const n = project.value?.shared_count || 0
		return `Sent to ${n} partner${n === 1 ? "" : "s"}`
	})
	// The hired partner's quoted timeline.
	const timelineLabel = computed(() => (hired.value?.timeline_weeks ? quoteTimeline(hired.value) : ""))
	const createdOn = computed(() => {
		const at = project.value?.created_on
		return at ? new Date(at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : ""
	})

	function openFeedback() {
		toast.info("Feedback form is coming soon.")
	}

	// ---- View requirements: everything the brief says, read back ----
	const requirementsOpen = ref(false)
	function viewRequirements() {
		requirementsOpen.value = true
	}

	// After an edit is sent: the new version, with its "Updated" line and the quotes' flags.
	function onRequirementsUpdated(updated) {
		project.value = updated
		loadQuotes()
	}
	const requirementsUpdatedLine = computed(() => {
		const at = project.value?.requirements_updated_on
		return at ? `Updated ${new Date(at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}` : ""
	})

	return {
		quotes,
		hasQuotes,
		hasQuoteRows,
		showQuoteHead,
		isCompact,
		isNarrow,
		shownQuotes,
		emptyView,
		sortLabel,
		sortOptions,
		viewLabel,
		viewOptions,
		quoteAmount,
		quoteTimeline,
		quoteSubline,
		restoreQuote,
		declineOpen,
		declineRow,
		declineReason,
		declineNote,
		declining,
		declineReasons,
		declineTitle,
		pickDeclineReason,
		confirmNotInterested,
		readThread,
		openPartnerProfile,
		tierSeal,
		hirePartner,
		hireOpen,
		hireRow,
		onHired,
		quoteMenu,
		simulating,
		simulateQuotes,
		inEditor,
		project,
		loadError,
		projectTitle,
		breadcrumbItems,
		isShared,
		hired,
		isHired,
		isAwaitingPartner,
		isChoosing,
		pinsQuoteList,
		awaitingLine,
		declinedHire,
		declinedLine,
		cancelling,
		cancelHireRequest,
		stageTitle,
		stageStep,
		hiredSteps,
		hiredCardTitle,
		isLive,
		setUpHosting,
		openHostingDocs,
		copyReferralCode,
		notLiveYet,
		answeringLive,
		isCompleted,
		completing,
		reviewAskOpen,
		reviewPartner,
		markComplete,
		hiredCost,
		messagePartner,
		viewPartnerProfile,
		sentLine,
		briefThread,
		viewBriefInMessages,
		timelineLabel,
		createdOn,
		openFeedback,
		requirementsOpen,
		viewRequirements,
		onRequirementsUpdated,
		requirementsUpdatedLine,
	}
}
