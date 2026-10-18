// The Starter Pack cart: the packs picked on the landing and details pages, what they come
// to with GST, and the way on to checkout. The cart itself lives in @app/utils/starterPackCart.

import { STARTER_PACK_TERMS, starterPackCart } from "@app/utils/starterPackCart"

const HOW_IT_WORKS = [
	{ text: "Pay Frappe upfront, at one fixed price" },
	{ text: "Tell us about your company" },
	{ text: "Join live sessions with Frappe onboarding specialists" },
]

export default function setup(context) {
	return { ...starterPackCart(context), howItWorks: HOW_IT_WORKS, terms: STARTER_PACK_TERMS }
}
