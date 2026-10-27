// The Starter Packs landing page: the three packs, each added to the cart from its card,
// and what the cart comes to, then the Contact us form. The cart itself lives in
// @app/utils/starterPackCart.

import { computed, ref, watch } from "vue"
import { call, toast } from "frappe-ui"
import { STATE_OPTIONS } from "@app/utils/billing"
import { keyboardAccess } from "@app/utils/keyboard"
import { INDUSTRY_OPTIONS } from "@app/utils/recommendation"
import { starterPackCart } from "@app/utils/starterPackCart"
import { startTracking } from "@app/utils/tracking"

export default function setup(context) {
	startTracking(context)
	const { myContext } = context
	keyboardAccess()

	// "Talk to our team": down to the contact form at the end of the page, ready to type in
	function talkToTeam() {
		const section = document.querySelector('[data-component-id="spl-contact"]')
		if (!section) return
		const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches
		section.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" })
		section.querySelector("input, textarea")?.focus({ preventScroll: true })
	}

	// ---- Contact us: saved as an Enquiry, and the team is emailed ----
	const enquiry = {
		enquiryFirstName: ref(""),
		enquiryLastName: ref(""),
		enquiryEmail: ref(""),
		enquiryPhone: ref(""),
		enquiryCompany: ref(""),
		enquiryDesignation: ref(""),
		enquiryEmployees: ref(""),
		enquirySoftware: ref(""),
		enquiryIndustry: ref(""),
		enquiryState: ref(""),
		enquiryMessage: ref(""),
	}
	const sendingEnquiry = ref(false)
	const enquirySent = ref(false)

	// A signed-in visitor doesn't type their name and email again
	watch(
		() => myContext?.data,
		(account) => {
			if (!account || account.user === "Guest") return
			const [first, ...rest] = String(account.full_name || "").split(" ")
			if (!enquiry.enquiryFirstName.value) enquiry.enquiryFirstName.value = first || ""
			if (!enquiry.enquiryLastName.value) enquiry.enquiryLastName.value = rest.join(" ")
			if (!enquiry.enquiryEmail.value && String(account.user).includes("@")) enquiry.enquiryEmail.value = account.user
		},
		{ immediate: true },
	)

	const canSendEnquiry = computed(() => Object.values(enquiry).every((field) => String(field.value || "").trim()))

	function sendEnquiry() {
		if (!canSendEnquiry.value || sendingEnquiry.value) return
		sendingEnquiry.value = true
		call("connect.api.customer.submit_enquiry", {
			first_name: enquiry.enquiryFirstName.value,
			last_name: enquiry.enquiryLastName.value,
			email: enquiry.enquiryEmail.value,
			phone: enquiry.enquiryPhone.value,
			company_name: enquiry.enquiryCompany.value,
			designation: enquiry.enquiryDesignation.value,
			employees: enquiry.enquiryEmployees.value,
			current_software: enquiry.enquirySoftware.value,
			industry: enquiry.enquiryIndustry.value,
			state: enquiry.enquiryState.value,
			message: enquiry.enquiryMessage.value,
			source: "Starter Pack Landing",
		})
			.then(() => {
				enquirySent.value = true
			})
			.catch((err) => {
				toast.error((err && err.messages && err.messages.join(", ")) || "Couldn't send your message. Try again.")
			})
			.finally(() => {
				sendingEnquiry.value = false
			})
	}

	return {
		...starterPackCart(context),
		talkToTeam,
		...enquiry,
		industryOptions: INDUSTRY_OPTIONS,
		stateOptions: STATE_OPTIONS,
		canSendEnquiry,
		sendingEnquiry,
		enquirySent,
		sendEnquiry,
	}
}
