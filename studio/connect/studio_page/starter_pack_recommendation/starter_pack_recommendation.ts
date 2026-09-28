// The Starter Pack recommendation: which packs the questionnaire's answers point to
// and why, the packs themselves (tick to add, "View details" for scope), and a basket
// that hands over to the checkout page. The answers arrive in the URL;
// the rules that read them live in @app/utils/recommendation.

import { computed } from "vue"
import {
	CUSTOM_IF,
	HOW_IT_WORKS,
	INCLUDED,
	NOT_INCLUDED,
	OUR_NEEDS,
	answersFromQuery,
	answersToQuery,
	directoryQuery,
	recommend,
} from "@app/utils/recommendation"
import { packBasket } from "@app/utils/packBasket"

export default function setup(context) {
	const { route, router, partnerCountries, pickedPacks } = context
	const basket = packBasket(context)
	const { packs } = basket

	const answers = answersFromQuery(route.query)
	const recommendation = answers ? recommend(answers) : null
	const recommended = recommendation?.verdict === "packs" ? recommendation.packs : []

	// Start with the recommended packs ticked; the customer can change that freely.
	pickedPacks.value = recommended.map((p) => p.key)

	const headline = computed(() => {
		if (!recommended.length) return "Starter Packs"
		return recommended.length > 1 ? "We recommend these Starter Packs" : "We recommend a Starter Pack"
	})

	// A "Recommended" badge only means something when it singles packs out.
	function isRecommended(key) {
		return recommended.length < packs.value.length && recommended.some((p) => p.key === key)
	}

	const whyReasons = recommendation?.verdict === "packs" ? recommendation.reasons : []
	const packReasons = computed(() =>
		recommended.map((r) => ({
			key: r.key,
			name: packs.value.find((p) => p.pack_key === r.key)?.pack_name || "",
			reason: `${r.reason}.`,
		})),
	)
	const packReasonsTitle = recommended.length > 1 ? "Why we recommend these packs" : "Why we recommend this pack"

	function changeAnswers() {
		router.push({ path: "/find-partners-redesign", query: answersToQuery(answers || {}) })
	}

	function getQuotes() {
		router.push({
			path: "/partner-directory-redesign",
			query: directoryQuery(answers || {}, partnerCountries.data || []),
		})
	}

	return {
		...basket,
		howItWorks: HOW_IT_WORKS,
		included: INCLUDED,
		notIncluded: NOT_INCLUDED,
		customIf: CUSTOM_IF,
		ourNeeds: OUR_NEEDS,
		hasAnswers: !!answers,
		headline,
		isRecommended,
		whyReasons,
		packReasons,
		packReasonsTitle,
		changeAnswers,
		getQuotes,
	}
}
