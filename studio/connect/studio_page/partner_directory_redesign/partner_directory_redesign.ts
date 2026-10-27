// Partner Directory: Connect on a card opens the New project dialog for that partner
// (partnerConnect.ts), and a guest's shortlist is added to their account once they sign in.

import { carryGuestShortlist } from "@app/utils/guestShortlist"
import { partnerConnect } from "@app/utils/partnerConnect"

export default function setup(context) {
	carryGuestShortlist(context, {
		localShortlist: context.localShortlist,
		onAdded: () => context.myShortlist.reload(),
	})
	return partnerConnect(context)
}
