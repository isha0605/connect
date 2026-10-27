// The Connect button on a partner's profile and on their directory and Shortlisted cards: the
// New project dialog, sent to that partner (connect.api.projects.start_project_with_partner),
// then their chat in Messaging. A guest signs in on Connect's page first and comes back to the
// same page with ?connect=<partner>, which opens the dialog; an account without a company (a
// partner's) is told why it can't.
//
// The page spreads this into its setup() return and renders the Projects page's dialog blocks,
// with {{ projectSaveLabel }} on the last button.

import { watch } from "vue"
import { projectDialog } from "@app/utils/projectDialog"
import { goToSignIn } from "@app/utils/signIn"

// Carry the partner through sign-in: their name, and the name to show in the dialog's title.
const CONNECT_QUERY = "connect"
const CONNECT_NAME_QUERY = "connect_name"

const NO_COMPANY = "Sign in with your company account to connect with a partner."

function isGuest(me) {
	return !me.user || me.user === "Guest"
}

export function partnerConnect(context) {
	const { route, router, myContext, toast } = context

	const dialog = projectDialog(context, {
		onSaved: (project, thread) => router.push({ path: "/messaging", query: { thread } }),
	})

	// partner: { name, partner_name }
	function connectWith(partner) {
		const me = myContext.data
		if (!me) {
			// Who they are hasn't loaded yet: ask, then carry on.
			myContext.reload().then(() => myContext.data && connectWith(partner))
			return
		}
		if (isGuest(me)) {
			const back = new URL(window.location.href)
			back.searchParams.set(CONNECT_QUERY, partner.name)
			back.searchParams.set(CONNECT_NAME_QUERY, partner.partner_name || "")
			goToSignIn({ next: back.pathname + back.search })
			return
		}
		if (!me.customer) {
			toast.error(NO_COMPANY)
			return
		}
		dialog.openNewProject(partner)
	}

	// Back from signing in: open the dialog they asked for, once, and take it off the URL so a
	// reload doesn't open it again.
	const pending = route.query[CONNECT_QUERY]
	if (pending) {
		let done = false
		watch(
			() => myContext.data,
			(me) => {
				if (done || !me) return
				done = true
				const { [CONNECT_QUERY]: _partner, [CONNECT_NAME_QUERY]: partnerName, ...rest } = route.query
				router.replace({ query: rest })
				if (isGuest(me)) return
				if (!me.customer) toast.error(NO_COMPANY)
				else dialog.openNewProject({ name: String(pending), partner_name: String(partnerName || "") })
			},
			{ immediate: true },
		)
	}

	return { ...dialog, connectWith }
}
