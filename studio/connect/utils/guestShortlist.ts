// A guest can shortlist partners on the directory and Shortlisted pages: the list is kept in
// this browser until they sign in, and then added to their account here.

import { watch } from "vue"

export const GUEST_SHORTLIST_KEY = "connect_local_shortlist"
// Set by the directory's old stand-in sign-in dialog; nothing reads it now.
const OLD_MOCK_SIGN_IN_KEY = "connect_mock_logged_in"

// localShortlist: the page's ref of the guest's list. onAdded runs once their account has it.
export function carryGuestShortlist(context, { localShortlist, onAdded }) {
	const { myContext, call } = context
	let done = false

	watch(
		() => myContext.data,
		(me) => {
			if (done || !me || !me.customer) return
			done = true
			try {
				localStorage.removeItem(OLD_MOCK_SIGN_IN_KEY)
			} catch (e) {}

			let partners = []
			try {
				partners = JSON.parse(localStorage.getItem(GUEST_SHORTLIST_KEY) || "[]")
			} catch (e) {}
			if (!partners.length) return

			Promise.allSettled(partners.map((partner) => call("connect.api.customer.add_to_shortlist", { partner }))).then(
				() => {
					try {
						localStorage.removeItem(GUEST_SHORTLIST_KEY)
					} catch (e) {}
					localShortlist.value = []
					onAdded?.()
				},
			)
		},
		{ immediate: true },
	)
}
