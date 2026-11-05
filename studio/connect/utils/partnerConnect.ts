// The Connect button on a partner's profile and on their directory and Shortlisted cards. A
// customer with projects picks one in the Contact dialog (ContactPartnerDialog.vue); one with
// none answers the New project dialog. Either way it goes to that partner
// (connect.api.projects.start_project_with_partner), then their chat in Messaging. A guest signs in on Connect's page first and comes back to the
// same page with ?connect=<partner>, which opens the dialog; an account without a company (a
// partner's) is told why it can't.
//
// The page spreads this into its setup() return and renders the Projects page's dialog blocks,
// with {{ projectSaveLabel }} on the last button, and the ContactPartnerDialog block.

import { ref, watch } from "vue"
import { projectDialog } from "@app/utils/projectDialog"
import { goToSignIn } from "@app/utils/signIn"

// Carry the partner through sign-in: their name, and the name to show in the dialog's title.
const CONNECT_QUERY = "connect"
const CONNECT_NAME_QUERY = "connect_name"

const NO_COMPANY = "Sign in with your company account to connect with a partner."

function isGuest(me) {
	return !me.user || me.user === "Guest"
}

// Projects still looking for a partner: not hired, nor waiting on a hire answer. A Starter Pack
// is bought as a fixed scope, so it is not requirements to ask a partner to quote on.
function isContactable(row) {
	return row.kind === "project" && row.verdict !== "packs" && !row.hired && !row.awaiting_partner
}

export function partnerConnect(context) {
	const { call, route, router, myContext, toast } = context

	const dialog = projectDialog(context, {
		onSaved: (project, thread) => router.push({ path: "/messaging", query: { thread } }),
	})

	const contactDialogOpen = ref(false)
	const contactPartner = ref(null)
	const contactProjects = ref([])

	function openContact(partner) {
		call("connect.api.projects.list_projects")
			.then((rows) => {
				const projects = (rows || []).filter(isContactable)
				if (!projects.length) {
					dialog.openNewProject(partner)
					return
				}
				contactPartner.value = partner
				contactProjects.value = projects
				contactDialogOpen.value = true
			})
			.catch(() => toast.error("Couldn't load your projects. Try again."))
	}

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
		openContact(partner)
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
				else openContact({ name: String(pending), partner_name: String(partnerName || "") })
			},
			{ immediate: true },
		)
	}

	return { ...dialog, connectWith, contactDialogOpen, contactPartner, contactProjects }
}
