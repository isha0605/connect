// Partner Directory: Connect on a card opens the New project dialog for that partner
// (partnerConnect.ts), and a guest's shortlist is added to their account once they sign in.

import { carryGuestShortlist } from "@app/utils/guestShortlist"
import { hourlyRate, viewerCurrency } from "@app/utils/money"
import { partnerConnect } from "@app/utils/partnerConnect"
import { useMyContext } from "@app/utils/myContext"

// Partners added each time the visitor scrolls near the end of the list. The filter scripts start
// the list over at the same size.
const PARTNERS_PER_LOAD = 9

export default function setup(context) {
	const myContext = useMyContext()
	carryGuestShortlist(context, {
		localShortlist: context.localShortlist,
		onAdded: () => context.myShortlist.reload(),
	})
	// The cards show each partner's rate in their own currency, with a rough amount in the customer's.
	const rateFor = (amount, currency) => hourlyRate(amount, currency, viewerCurrency(myContext.data))
	return {
		myContext,
		...partnerConnect(context),
		hourlyRate: rateFor,
		loadMorePartners: () => loadMorePartners(context),
	}
}

// A full list means the last load filled its limit, so more partners may follow.
function hasMorePartners(context) {
	return (context.directoryPartners.data || []).length >= context.directoryLimit.value
}

// Asks for a longer list with the same filters, so the order the server ranks stays the same.
function loadMorePartners(context) {
	const partners = context.directoryPartners
	if (partners.loading || !hasMorePartners(context)) return

	context.directoryLimit.value += PARTNERS_PER_LOAD
	partners.update({ params: { ...partners.params, limit: context.directoryLimit.value } })
	partners.reload().then(() => {
		if (!hasMorePartners(context)) reloadFallbacks(context)
	})
}

// The "Proven in other …" sections leave out every partner the main list shows, so they load again
// once the main list has all of its partners.
function reloadFallbacks(context) {
	const exclude = JSON.stringify((context.directoryPartners.data || []).map((partner) => partner.name))
	const fallbacks = [context.categoryFallback, context.appFallback]
	if ((context.selectedCountries.value || []).length) fallbacks.push(context.countryFallback)

	for (const fallback of fallbacks) {
		fallback.update({ params: { ...fallback.params, exclude } })
		fallback.reload()
	}
}
