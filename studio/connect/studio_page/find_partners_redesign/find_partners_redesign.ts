// "Tell us about your business": three steps of questions, then a hand-off to either
// the Starter Pack recommendation or a partner directory filtered to the answers.
//
// ?intent=contact is Get started's "Contact partners" instead: step 2 also asks what else they
// use, step 3 is the brief (budget, what they need) in place of what they want fixed, and the
// end is the Share requirements dialog, which sends the brief to every matching partner. A guest signs
// up first and comes back here (?details=1) with their answers kept in this tab.
// The answers themselves are Studio variables so the form controls can v-model them;
// what they mean lives in @app/utils/recommendation, shared with the recommendation page.

import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { avatarTheme } from "@app/utils/avatarTheme"
import { blankCriteria, criteriaSummary, partnerCriteria } from "@app/utils/partnerCriteria"
import {
	BUDGET_RANGES,
	COUNTRY_OPTIONS,
	EMPLOYEE_OPTIONS,
	INDUSTRY_OPTIONS,
	SYSTEM_OPTIONS,
	answersFromQuery,
	answersToQuery,
	directoryQuery,
	recommend,
	regionOf,
} from "@app/utils/recommendation"
import { startTracking } from "@app/utils/tracking"
import { useMyContext } from "@app/utils/myContext"

export default function setup(context) {
	startTracking(context)
	const {
		route,
		router,
		wizardStep,
		showErrors,
		businessCountry,
		employeeCount,
		industries,
		operations,
		currentSystems,
		painPoints,
		partnerCountries,
	} = context
	const myContext = useMyContext()

	// Back from "Change my answers": start from what they said last time.
	const previous = answersFromQuery(route.query)
	if (previous) {
		businessCountry.value = previous.country || businessCountry.value
		employeeCount.value = previous.employees
		industries.value = previous.industries
		operations.value = previous.operations
		currentSystems.value = previous.systems
		painPoints.value = previous.problems
	}

	function answers() {
		return {
			country: businessCountry.value,
			employees: employeeCount.value,
			industries: industries.value || [],
			operations: operations.value,
			systems: currentSystems.value || [],
			problems: painPoints.value || [],
		}
	}

	function mapRegions(country) {
		const region = regionOf(country)
		return region ? [region] : []
	}

	function usesOtherSystems(value) {
		return !!value && value !== "spreadsheets"
	}

	function hasPain(key) {
		return (painPoints.value || []).includes(key)
	}

	function togglePain(key) {
		const current = painPoints.value || []
		painPoints.value = hasPain(key) ? current.filter((k) => k !== key) : [...current, key]
	}

	function goToStep(step) {
		showErrors.value = false
		wizardStep.value = step
	}

	function continueFromBusiness() {
		if (!businessCountry.value || !employeeCount.value || !(industries.value || []).length) {
			showErrors.value = true
			return
		}
		goToStep(2)
	}

	// The recommendation needs how they run today; a brief to partners can go without it.
	function continueFromOperations() {
		if (!contactMode && !operations.value) {
			showErrors.value = true
			return
		}
		goToStep(3)
	}

	function seeRecommendation() {
		if (!(painPoints.value || []).length) {
			showErrors.value = true
			return
		}
		if (recommend(answers()).verdict === "packs") {
			router.push({ path: "/starter-pack-recommendation", query: answersToQuery(answers()) })
		} else {
			router.push({
				path: "/partner-directory",
				query: directoryQuery(answers(), partnerCountries.data || []),
			})
		}
	}

	// ---- Contact partners (?intent=contact) ----
	const contactMode = route.query.intent === "contact"
	const signedIn = computed(() => {
		const user = myContext?.data?.user
		return !!user && user !== "Guest"
	})
	const briefBudget = ref("")
	const briefDescription = ref("")
	const otherSystem = ref("")

	// Kept in this tab across signing up — the sign-up page reloads the app.
	const BRIEF_KEY = "connect.contactPartners.brief"
	function keepBrief() {
		try {
			window.sessionStorage.setItem(
				BRIEF_KEY,
				JSON.stringify({
					...answers(),
					other_system: otherSystem.value,
					budget: briefBudget.value,
					description: briefDescription.value,
				}),
			)
		} catch {
			// Without storage they answer again after signing up.
		}
	}
	function restoreBrief() {
		let kept = null
		try {
			kept = JSON.parse(window.sessionStorage.getItem(BRIEF_KEY) || "null")
		} catch {
			kept = null
		}
		if (!kept) return false
		businessCountry.value = kept.country || businessCountry.value
		employeeCount.value = kept.employees || ""
		industries.value = kept.industries || []
		operations.value = kept.operations || ""
		currentSystems.value = kept.systems || []
		otherSystem.value = kept.other_system || ""
		briefBudget.value = kept.budget || ""
		briefDescription.value = kept.description || ""
		return true
	}

	// What the brief goes out with: the questions' answers, then whatever Edit criteria adds.
	const shareCriteria = ref(blankCriteria())
	const shareOpen = ref(false)
	const editingCriteria = ref(false)
	const recipients = ref(null)
	const sharing = ref(false)
	const chips = partnerCriteria(context, { saved: () => shareCriteria.value })
	const shareSummary = computed(() => criteriaSummary(shareCriteria.value))

	// The partners the brief goes to, from the same query the send uses.
	function loadRecipients() {
		recipients.value = null
		call("connect.api.projects.partner_criteria", {
			criteria: JSON.stringify(shareCriteria.value),
			include_recipients: 1,
		})
			.then((data) => {
				recipients.value = data.recipients || []
			})
			.catch(() => {
				recipients.value = []
			})
	}

	// The same partners the send reaches (get_partner_criteria in questions.py): in their
	// country when partners are there, else anywhere, with their industries.
	function openShare() {
		shareCriteria.value = {
			...blankCriteria(),
			countries: partnersCountry(),
			industries: [...(industries.value || [])],
		}
		editingCriteria.value = false
		loadRecipients()
		shareOpen.value = true
	}

	// Edit criteria shows the chips in place; Done keeps what was picked.
	function toggleEditCriteria() {
		if (editingCriteria.value) {
			shareCriteria.value = chips.draftFilters()
			editingCriteria.value = false
			loadRecipients()
		} else {
			chips.startEditing()
			editingCriteria.value = true
		}
	}

	const noMatches = computed(() =>
		editingCriteria.value ? chips.criteriaFacets.value.total === 0 : recipients.value?.length === 0,
	)

	const recipientCount = computed(() => recipients.value?.length || 0)
	const recipientAvatars = computed(() => stackAvatars(recipients.value || []))
	const partnersWord = computed(() => (recipientCount.value === 1 ? "partner" : "partners"))
	const recipientHeadline = computed(() => {
		if (recipients.value === null) return "Finding matched partners…"
		if (!recipientCount.value) return "No partners match yet"
		return `Sharing with ${recipientCount.value} matched ${partnersWord.value}`
	})
	const recipientReach = computed(() => reachSentence(shareCriteria.value))
	const seenByLabel = computed(() =>
		recipientCount.value ? `What these ${recipientCount.value} ${partnersWord.value} will see` : "What partners will see",
	)
	const shareButtonLabel = computed(() =>
		recipientCount.value ? `Share with ${recipientCount.value} ${partnersWord.value}` : "Share requirements",
	)
	const shareFootnote = computed(() =>
		recipientCount.value
			? `Only ${recipientCount.value === 1 ? "this partner" : `these ${recipientCount.value} partners`} will see your brief. They reply in Messages with a quote.`
			: "Widen your criteria to reach more partners.",
	)
	// What the Requirement card carries to each partner, beyond the criteria listed above.
	const sharedDetails = computed(() =>
		[
			{ label: "Budget", value: briefBudget.value },
			{ label: "Project details", value: openingWords(briefDescription.value, 40) },
			{ label: "Company", value: companyLine() },
			{ label: "Sent as", value: myContext?.data?.full_name || myContext?.data?.user || "" },
		].map((row, i) => ({ ...row, first: i === 0 })),
	)

	function companyLine() {
		const company = myContext?.data?.customer?.customer_name
		const size = EMPLOYEE_OPTIONS.find((o) => o.value === employeeCount.value)?.label
		return [company, size && `${size} employees`].filter(Boolean).join(" · ")
	}

	function continueFromBrief() {
		if (!briefBudget.value || !briefDescription.value.trim()) {
			showErrors.value = true
			return
		}
		showErrors.value = false
		if (!signedIn.value) {
			keepBrief()
			const next = router.resolve({ path: route.path, query: { intent: "contact", details: "1" } }).fullPath
			router.push({ path: "/login-signup", query: { next } })
			return
		}
		openShare()
	}

	function shareBrief() {
		if (sharing.value) return
		if (editingCriteria.value) toggleEditCriteria()
		sharing.value = true
		const systems = usesOtherSystems(operations.value) ? currentSystems.value || [] : []
		call("connect.api.projects.share_requirements", {
			answers: JSON.stringify({
				country: businessCountry.value,
				company_size: employeeCount.value,
				industries: industries.value || [],
				operations: operations.value,
				systems,
				other_system: systems.includes("Something else") ? otherSystem.value.trim() : "",
				budget: briefBudget.value,
				description: briefDescription.value.trim(),
				criteria: { cities: shareCriteria.value.cities, tiers: shareCriteria.value.tiers },
			}),
			// This wizard doesn't ask what they want fixed or the apps.
			contact_partners: 1,
		})
			.then((project) => {
				try {
					window.sessionStorage.removeItem(BRIEF_KEY)
				} catch {
					// Nothing kept, nothing to clear.
				}
				const n = project.shared_count || 0
				toast.success(`Sent to ${n} partner${n === 1 ? "" : "s"}. Their replies come back as quotes.`, {
					action: project.brief_thread && {
						label: "View",
						onClick: () => router.push({ path: "/messaging", query: { thread: project.brief_thread } }),
					},
				})
				shareOpen.value = false
				router.push({ path: "/custom-implementation", query: { project: project.name } })
			})
			.catch((error) => {
				toast.error(error?.messages?.[0] || "Couldn't send your requirements. Try again.")
			})
			.finally(() => {
				sharing.value = false
			})
	}

	// Same test Studio's own isEditor() uses. The editor never runs the flow that fills this
	// dialog, so it gets a sample brief and the real partners in India (enough for a "+N").
	const inEditor = window.location.pathname.startsWith("/studio/")
	if (inEditor) {
		briefBudget.value = BUDGET_RANGES.INR[1]
		briefDescription.value = "Dealer orders, billing and stock across three warehouses."
		employeeCount.value = "11-50"
		shareCriteria.value = { ...blankCriteria(), countries: ["India"] }
		loadRecipients()
	}

	// A signed-in customer's company facts fill step 1, as in the New project dialog: they are
	// the company's, and once set only its Owner or an Admin can change them.
	if (contactMode) {
		watch(
			() => myContext?.data?.customer,
			(company) => {
				if (!company) return
				if (company.country) businessCountry.value = company.country
				if (company.company_size) employeeCount.value = company.company_size
				if ((company.industries || []).length) industries.value = company.industries
			},
			{ immediate: true },
		)
	}

	// Back from signing up: their answers again, on the brief, with the dialog open.
	// ?details stays in the URL: changing the route remounts the page, which would undo this.
	if (contactMode && route.query.details && restoreBrief()) {
		wizardStep.value = 3
		watch(
			() => myContext?.data,
			(data) => {
				if (data && signedIn.value && !shareOpen.value) openShare()
			},
			{ immediate: true },
		)
	}

	// ---- Partners that match, under the map ----
	// Their own country when partners are there, and their industry — the same matching the
	// brief is sent with. Re-counted a moment after the answers settle.
	const liveMatchCount = ref(null)
	let countTimer = null
	function matchCriteria() {
		return { ...blankCriteria(), countries: partnersCountry(), industries: [...(industries.value || [])] }
	}
	watch(
		() => JSON.stringify(matchCriteria()),
		(criteria) => {
			clearTimeout(countTimer)
			countTimer = setTimeout(() => {
				call("connect.api.projects.partner_criteria", { criteria })
					.then((data) => {
						liveMatchCount.value = data.total
					})
					.catch(() => {})
			}, 250)
		},
		{ immediate: true },
	)
	const matchCountLabel = computed(() => (liveMatchCount.value === null ? "–" : String(liveMatchCount.value)))
	const matchCountCaption = computed(() =>
		liveMatchCount.value === 1 ? "Partner that matches your answers" : "Partners that match your answers",
	)
	function viewAllPartners() {
		router.push({ path: "/partner-directory", query: directoryQuery(answers(), partnerCountries.data || []) })
	}

	// Their country as the partners' country names it, when partners are there; the server
	// matches it the same way, ignoring case.
	function partnersCountry() {
		const country = String(businessCountry.value || "").toLowerCase()
		const match = (partnerCountries.data || []).find((name) => name.toLowerCase() === country)
		return match ? [match] : []
	}

	function finishStep3() {
		if (contactMode) continueFromBrief()
		else seeRecommendation()
	}

	return {
		myContext,
		matchCountLabel,
		matchCountCaption,
		viewAllPartners,
		contactMode,
		signedIn,
		briefBudget,
		briefDescription,
		otherSystem,
		finishStep3,
		shareOpen,
		shareSummary,
		recipientAvatars,
		recipientHeadline,
		recipientReach,
		seenByLabel,
		shareButtonLabel,
		shareFootnote,
		sharedDetails,
		editingCriteria,
		toggleEditCriteria,
		noMatches,
		sharing,
		shareBrief,
		cityChips: chips.cityChips,
		tierChips: chips.tierChips,
		toggleCriterion: chips.toggleCriterion,
		countryOptions: COUNTRY_OPTIONS,
		employeeOptions: EMPLOYEE_OPTIONS,
		industryOptions: INDUSTRY_OPTIONS,
		systemOptions: SYSTEM_OPTIONS,
		mapRegions,
		usesOtherSystems,
		hasPain,
		togglePain,
		goToStep,
		continueFromBusiness,
		continueFromOperations,
		seeRecommendation,
	}
}

// "Based in India, serving Manufacturing": where and what the brief is aimed at.
function reachSentence(criteria) {
	const place = criteria.cities?.length ? criteria.cities : criteria.countries || []
	const parts = []
	if (place.length) parts.push(`based in ${either(place)}`)
	if (criteria.industries?.length) parts.push(`serving ${either(criteria.industries)}`)
	const sentence = parts.join(", ") || "any partner listed on Connect"
	return sentence[0].toUpperCase() + sentence.slice(1)
}

// The table has one line per row: the start of the brief, cut at a word.
function openingWords(text, maxLength) {
	const clean = (text || "").trim().replace(/\s+/g, " ")
	if (clean.length <= maxLength) return clean
	const cut = clean.slice(0, maxLength)
	const lastSpace = cut.lastIndexOf(" ")
	return `${(lastSpace > maxLength / 2 ? cut.slice(0, lastSpace) : cut).replace(/[,.;:]$/, "")}…`
}

function either(values) {
	return values.length === 1 ? values[0] : `${values.slice(0, -1).join(", ")} or ${values.at(-1)}`
}

const MAX_AVATARS = 5

function partnerAvatar(partner, i) {
	return {
		key: partner.name,
		image: partner.logo,
		label: partner.company_name,
		tooltip: partner.company_name,
		theme: avatarTheme(partner.company_name),
		first: i === 0,
		more: false,
	}
}

// The avatar row at the top of Share requirements. Each item renders as an Avatar
// (image, label, theme) or, when `more` is set, a "+N" circle showing `label`;
// `tooltip` shows on hover and `first` drops the overlap margin.
// The tooltip bubble doesn't wrap, so name a few and count the rest.
function hiddenNames(partners) {
	const names = partners.slice(0, 2).map((p) => p.company_name)
	const rest = partners.length - names.length
	if (rest) return `${names.join(", ")} and ${rest} more`
	return names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`
}

// Five slots at most: past five, the fifth becomes "+N" and its tooltip names the rest.
function stackAvatars(partners) {
	if (partners.length <= MAX_AVATARS) return partners.map(partnerAvatar)

	const shown = partners.slice(0, MAX_AVATARS - 1)
	const hidden = partners.slice(MAX_AVATARS - 1)
	return [
		...shown.map(partnerAvatar),
		{
			key: "more",
			label: `+${hidden.length}`,
			tooltip: hiddenNames(hidden),
			first: false,
			more: true,
		},
	]
}
