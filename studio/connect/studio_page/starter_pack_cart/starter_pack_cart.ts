// The Starter Pack cart: the packs picked on the landing and details pages, what they come
// to with GST, and the way on to checkout. The cart itself lives in @app/utils/starterPackCart.

import { STARTER_PACK_TERMS, starterPackCart } from "@app/utils/starterPackCart"
import { keyboardAccess } from "@app/utils/keyboard"
import { startTracking } from "@app/utils/tracking"

const HOW_IT_WORKS = [
	{ text: "Pay Frappe upfront, at one fixed price" },
	{ text: "Tell us about your company" },
	{ text: "Join live sessions with Frappe onboarding specialists" },
]

export default function setup(context) {
	startTracking(context)
	keyboardAccess()
	return { ...starterPackCart(context), howItWorks: HOW_IT_WORKS, terms: STARTER_PACK_TERMS }
}
