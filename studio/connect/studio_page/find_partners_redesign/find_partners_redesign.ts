// "Tell us about your business": three steps of questions, then a hand-off to either
// the Starter Pack recommendation or a partner directory filtered to the answers.
//
// ?intent=contact is Get started's "Contact partners" instead: step 1 asks which regions
// partners should be from, step 3 is the brief (budget, what to build), and the end is the
// Share requirements dialog, which sends the brief to every matching partner. A guest signs
// up first and comes back here (?details=1) with their answers kept in this tab.
// The answers themselves are Studio variables so the form controls can v-model them;
// what they mean lives in @app/utils/recommendation, shared with the recommendation page.

import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { blankCriteria, criteriaSummary, partnerCriteria } from "@app/utils/partnerCriteria"
import {
	BUDGET_OPTIONS,
	COUNTRY_OPTIONS,
	MANUFACTURING_INDUSTRIES,
	EMPLOYEE_OPTIONS,
	INDUSTRY_OPTIONS,
	SYSTEM_OPTIONS,
	answersFromQuery,
	answersToQuery,
	directoryQuery,
	recommend,
	regionOf,
} from "@app/utils/recommendation"

export default function setup(context) {
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
		myContext,
	} = context

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
		const whereMissing = contactMode ? !partnerRegions.value.length : !businessCountry.value
		if (whereMissing || !employeeCount.value || !(industries.value || []).length) {
			showErrors.value = true
			return
		}
		goToStep(2)
	}

	function continueFromOperations() {
		if (!operations.value) {
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
				path: "/partner-directory-redesign",
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
	const partnerRegions = ref([])
	const briefBudget = ref("")
	const briefDescription = ref("")

	// Where partners should be from: the countries partners are actually in.
	const regionChips = computed(() =>
		(partnerCountries.data || []).map((country) => ({
			value: country,
			label: country,
			picked: partnerRegions.value.includes(country),
		})),
	)
	function toggleRegion(country) {
		const list = partnerRegions.value
		partnerRegions.value = list.includes(country) ? list.filter((c) => c !== country) : [...list, country]
	}
	// Until they pick, partners from their own country (if there are any there).
	watch(
		() => partnerCountries.data,
		(countries) => {
			if (contactMode && !partnerRegions.value.length && (countries || []).includes(businessCountry.value)) {
				partnerRegions.value = [businessCountry.value]
			}
		},
		{ immediate: true },
	)

	// Kept in this tab across signing up — the sign-up page reloads the app.
	const BRIEF_KEY = "connect.contactPartners.brief"
	function keepBrief() {
		try {
			window.sessionStorage.setItem(
				BRIEF_KEY,
				JSON.stringify({ ...answers(), regions: partnerRegions.value, budget: briefBudget.value, description: briefDescription.value }),
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
		if (!kept) return
		businessCountry.value = kept.country || businessCountry.value
		employeeCount.value = kept.employees || ""
		industries.value = kept.industries || []
		operations.value = kept.operations || ""
		currentSystems.value = kept.systems || []
		partnerRegions.value = kept.regions || []
		briefBudget.value = kept.budget || ""
		briefDescription.value = kept.description || ""
	}

	// The partners' own industry list is coarser than the one asked here.
	function partnerIndustries(picked) {
		const map = {
			Education: "Education",
			Finance: "FinTech",
			Government: "Government",
			Logistics: "Logistics",
			Nonprofit: "Nonprofit",
			"Professional services": "Professional Services",
			Distribution: "Retail",
			"E-commerce": "Retail",
			"Fast Moving Consumer Goods": "Retail",
			Retail: "Retail",
		}
		const out = (picked || []).map((i) =>
			i === "Manufacturing" || MANUFACTURING_INDUSTRIES.includes(i) ? "Manufacturing" : map[i],
		)
		return [...new Set(out.filter(Boolean))]
	}

	// What the brief goes out with: the questions' answers, then whatever Edit criteria adds.
	const shareCriteria = ref(blankCriteria())
	const shareGoLive = ref("no_deadline")
	const shareOpen = ref(false)
	const editingCriteria = ref(false)
	const matchTotal = ref(null)
	const sharing = ref(false)
	const chips = partnerCriteria(context, {
		saved: () => shareCriteria.value,
		goLive: () => shareGoLive.value,
	})
	const shareSummary = computed(() => criteriaSummary(shareCriteria.value, shareGoLive.value))

	function countMatches() {
		call("connect.api.projects.partner_criteria", { criteria: JSON.stringify(shareCriteria.value) })
			.then((data) => {
				matchTotal.value = data.total
			})
			.catch(() => {})
	}

	function openShare() {
		shareCriteria.value = {
			...blankCriteria(),
			countries: [...partnerRegions.value],
			industries: partnerIndustries(industries.value),
		}
		editingCriteria.value = false
		countMatches()
		shareOpen.value = true
	}

	// Edit criteria shows the chips in place; Done keeps what was picked.
	function toggleEditCriteria() {
		if (editingCriteria.value) {
			shareCriteria.value = chips.draftFilters()
			shareGoLive.value = chips.criteriaDraft.value.go_live || shareGoLive.value
			matchTotal.value = chips.criteriaFacets.value.total
			editingCriteria.value = false
		} else {
			chips.startEditing()
			editingCriteria.value = true
		}
	}

	const noMatches = computed(() => (editingCriteria.value ? chips.criteriaFacets.value.total : matchTotal.value) === 0)

	function continueFromBrief() {
		if (!briefBudget.value || !briefDescription.value.trim()) {
			showErrors.value = true
			return
		}
		showErrors.value = false
		if (!signedIn.value) {
			keepBrief()
			const next = router.resolve({ path: route.path, query: { intent: "contact", details: "1" } }).fullPath
			router.push({ path: "/login-signup-redesign", query: { next } })
			return
		}
		openShare()
	}

	function shareBrief() {
		if (sharing.value) return
		if (editingCriteria.value) toggleEditCriteria()
		sharing.value = true
		const company = myContext?.data?.customer?.customer_name
		call("connect.api.projects.save_project", {
			project_name: company ? `ERPNext implementation for ${company}` : "Custom implementation",
			go_live: shareGoLive.value,
			operations: operations.value,
			systems: JSON.stringify(currentSystems.value || []),
			problems: JSON.stringify([]),
			verdict: "custom",
			// as they picked them, for the brief partners receive
			industries: JSON.stringify(industries.value || []),
			company_size: EMPLOYEE_OPTIONS.find((o) => o.value === employeeCount.value)?.label || "",
		})
			.then((project) =>
				call("connect.api.projects.save_criteria", {
					name: project.name,
					criteria: JSON.stringify(shareCriteria.value),
					go_live: shareGoLive.value,
				}),
			)
			.then((project) =>
				call("connect.api.projects.share_requirements", {
					name: project.name,
					budget: briefBudget.value,
					description: briefDescription.value,
				}),
			)
			.then((project) => {
				try {
					window.sessionStorage.removeItem(BRIEF_KEY)
				} catch {
					// Nothing kept, nothing to clear.
				}
				const n = project.shared_count || 0
				toast.success(`Sent to ${n} partner${n === 1 ? "" : "s"}. Their replies come back as quotes.`)
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

	// Back from signing up: their answers again, on the brief, with the dialog open.
	if (contactMode && route.query.details) {
		restoreBrief()
		wizardStep.value = 3
		router.replace({ path: route.path, query: { intent: "contact" } })
		watch(
			() => myContext?.data,
			(data) => {
				if (data && signedIn.value && !shareOpen.value) openShare()
			},
			{ immediate: true },
		)
	}

	// ---- Partners that match, under the map ----
	// Where they want partners from (contact mode's region chips, otherwise their own
	// country when partners are there) and their industry — the same matching the brief
	// is sent with. Re-counted a moment after the answers settle.
	const liveMatchCount = ref(null)
	let countTimer = null
	function matchCriteria() {
		const countries = contactMode
			? partnerRegions.value
			: (partnerCountries.data || []).includes(businessCountry.value)
				? [businessCountry.value]
				: []
		return { ...blankCriteria(), countries: [...countries], industries: partnerIndustries(industries.value) }
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
		router.push({ path: "/partner-directory-redesign", query: directoryQuery(answers(), partnerCountries.data || []) })
	}

	function finishStep3() {
		if (contactMode) continueFromBrief()
		else seeRecommendation()
	}

	return {
		matchCountLabel,
		matchCountCaption,
		viewAllPartners,
		contactMode,
		signedIn,
		regionChips,
		toggleRegion,
		briefBudget,
		briefDescription,
		budgetOptions: BUDGET_OPTIONS,
		finishStep3,
		shareOpen,
		shareSummary,
		editingCriteria,
		toggleEditCriteria,
		noMatches,
		sharing,
		shareBrief,
		cityChips: chips.cityChips,
		tierChips: chips.tierChips,
		workChips: chips.workChips,
		goLiveChips: chips.goLiveChips,
		toggleCriterion: chips.toggleCriterion,
		setGoLive: chips.setGoLive,
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
