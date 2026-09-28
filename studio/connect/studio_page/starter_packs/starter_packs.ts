// Starter Packs: what a pack is, the packs themselves (tick to add, "View details" for
// scope), and a basket that hands over to checkout. The recommendation page shows the
// same packs and basket, with the questionnaire's reasons on top.

import { CUSTOM_IF, HOW_IT_WORKS, INCLUDED, NOT_INCLUDED, OUR_NEEDS } from "@app/utils/recommendation"
import { packBasket } from "@app/utils/packBasket"

const VALUE_PROPS = [
	{ icon: "lucide-circle-dollar-sign", title: "Standardized pricing", body: "Based on region" },
	{ icon: "lucide-clock", title: "Faster implementation", body: "3x faster to get started" },
	{ icon: "lucide-circle-check", title: "Frappe oversees", body: "Quality at every step" },
]

export default function setup(context) {
	const { router } = context

	function getQuotes() {
		router.push("/partner-directory-redesign")
	}

	return {
		...packBasket(context),
		valueProps: VALUE_PROPS,
		howItWorks: HOW_IT_WORKS,
		included: INCLUDED,
		notIncluded: NOT_INCLUDED,
		customIf: CUSTOM_IF,
		ourNeeds: OUR_NEEDS,
		getQuotes,
	}
}
