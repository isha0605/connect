// Shortlisted: as on the Partner Directory, Connect on a card opens the New project dialog for
// that partner (partnerConnect.ts), and a guest's shortlist is added to their account once they
// sign in.

import { carryGuestShortlist } from "@app/utils/guestShortlist"
import { hourlyRate, viewerCurrency } from "@app/utils/money"
import { partnerConnect } from "@app/utils/partnerConnect"
import { useMyContext } from "@app/utils/myContext"

export default function setup(context) {
	const myContext = useMyContext()
	carryGuestShortlist(context, {
		localShortlist: context.localShortlist,
		onAdded: () => {
			context.localShortlistDetails.update({ params: { names: "[]" } })
			context.myShortlistFull.reload()
		},
	})
	// The cards show each partner's rate in their own currency, with a rough amount in the customer's.
	const rateFor = (amount, currency) => hourlyRate(amount, currency, viewerCurrency(myContext.data))
	return { myContext, ...partnerConnect(context), hourlyRate: rateFor }
}
