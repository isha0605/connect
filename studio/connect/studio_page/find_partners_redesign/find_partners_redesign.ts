// "Tell us about your business": three steps of questions, then a hand-off to either
// the Starter Pack recommendation or a partner directory filtered to the answers.
// The answers themselves are Studio variables so the form controls can v-model them;
// what they mean lives in @app/utils/recommendation, shared with the recommendation page.

import { computed, ref, watch } from "vue"
import { call } from "frappe-ui"
import { avatarTheme } from "@app/utils/avatarTheme"
import { blankCriteria } from "@app/utils/partnerCriteria"
import {
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

	// ---- Partners that match, under the map ----
	// Their own country, when partners are there, and their industry — the same matching the
	// brief is sent with. Re-counted a moment after the answers settle.
	const liveMatchCount = ref(null)
	let countTimer = null
	function matchCriteria() {
		const countries = (partnerCountries.data || []).includes(businessCountry.value) ? [businessCountry.value] : []
		return { ...blankCriteria(), countries: [...countries], industries: [...(industries.value || [])] }
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

	return {
		matchCountLabel,
		matchCountCaption,
		viewAllPartners,
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
		label: partner.partner_name,
		tooltip: partner.partner_name,
		theme: avatarTheme(partner.partner_name),
		first: i === 0,
		more: false,
	}
}

// The avatar row at the top of Share requirements. Each item renders as an Avatar
// (image, label, theme) or, when `more` is set, a "+N" circle showing `label`;
// `tooltip` shows on hover and `first` drops the overlap margin.
// The tooltip bubble doesn't wrap, so name a few and count the rest.
function hiddenNames(partners) {
	const names = partners.slice(0, 2).map((p) => p.partner_name)
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
