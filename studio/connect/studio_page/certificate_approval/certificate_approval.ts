// Where a certificate holder lands from the "Confirm your certificate" email: it names the partner
// asking for their certificate, and links it only when they press Confirm (mail scanners open
// links on their own, so loading the page must not approve anything). No sign-in: the key in the
// link is what authorises them.

import { computed, ref } from "vue"

const API = "connect.api.partner"

export default function setup(context) {
	const { call, route } = context

	const key = String(route.query.key || "")
	const request = ref(null)
	// "loading" | "ready" | "approved" | "invalid"
	const state = ref("loading")
	const error = ref("")
	const approving = ref(false)

	call(`${API}.get_certificate_link_request`, { key })
		.then((data) => {
			request.value = data
			state.value = data.status === "Approved" ? "approved" : "ready"
		})
		.catch(() => {
			state.value = "invalid"
		})

	function approve() {
		if (approving.value) return
		approving.value = true
		error.value = ""
		call(`${API}.approve_certificate_link`, { key })
			.then((data) => {
				request.value = data
				state.value = "approved"
			})
			.catch((failure) => {
				error.value = failure?.messages?.[0] || "Couldn't confirm it. Try again."
			})
			.finally(() => {
				approving.value = false
			})
	}

	return {
		state,
		error,
		approving,
		approve,
		question: computed(() =>
			request.value
				? `${request.value.partner_name} wants to add your ${request.value.course} certificate to their team on Frappe Connect.`
				: "",
		),
		holder: computed(() => (request.value ? `Certificate holder: ${request.value.user_email}` : "")),
		done: computed(() =>
			request.value ? `Your ${request.value.course} certificate is now linked to ${request.value.partner_name}.` : "",
		),
	}
}
