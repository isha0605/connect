// "Tell us about your business": three steps of questions, then a hand-off to either
// the Starter Pack recommendation or a partner directory filtered to the answers.
// The answers themselves are Studio variables so the form controls can v-model them;
// what they mean lives in @app/utils/recommendation, shared with the recommendation page.

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

export default function setup(context) {
	const {
		route,
		router,
		wizardStep,
		showErrors,
		businessCountry,
		employeeCount,
		industry,
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
		industry.value = previous.industry
		operations.value = previous.operations
		currentSystems.value = previous.systems
		painPoints.value = previous.problems
	}

	function answers() {
		return {
			country: businessCountry.value,
			employees: employeeCount.value,
			industry: industry.value,
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
		if (!businessCountry.value || !employeeCount.value || !industry.value) {
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

	return {
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
