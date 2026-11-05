// The "Become a partner" registration form, as Press's PartnerRegistration.vue has it. The Login,
// Messaging and Partner Onboarding pages all show it, so its state, checks and the details sent to
// connect.api.partner.save_partner_application live here once. Each page decides what Proceed does
// once the form is valid.

import { computed, ref } from "vue"

type Country = { name: string; isd?: string }
type RegistrationDetails = {
	company_name: string
	registered_country: string
	registered_state: string
	company_email: string
	contact: string
}

const COMPANY_NAME_LENGTH = { min: 2, max: 140 }
const CONTACT_DIGITS = { min: 7, max: 20 }
const EMAIL_PATTERN = /^\S+@\S+\.\S+$/

// `countries` reads the page's partnershipCountries resource: each with its name and dialling code.
export function usePartnerRegistration(countries: () => Country[]) {
	// The returned names are what the shared blocks in each page's JSON read and write.
	const state = {
		partnershipWizardOpen: ref(false),
		partnershipWizardStep: ref("partnerships"),
		partnershipEditMode: ref(false),
		partnershipRegistered: ref(false),
		partnershipSubmitted: ref(false),
		partnershipSubmitError: ref(""),
		partnershipSaving: ref(false),
		partnershipCompanyName: ref(""),
		partnershipCountry: ref(""),
		partnershipState: ref(""),
		partnershipEmail: ref(""),
		partnershipContact: ref(""),
		partnershipIsdCountry: ref(""),
		partnershipIsdSearch: ref(""),
	}

	// The country whose dialling code the contact number uses: the one picked, else the registered one.
	const isdMatch = () =>
		countries().find((c) => c.name === (state.partnershipIsdCountry.value || state.partnershipCountry.value))

	// Stored as "<dialling code>-<number>", e.g. "+91-9876543210".
	function partnershipDetails(): RegistrationDetails {
		const country = state.partnershipCountry.value
		const number = String(state.partnershipContact.value || "").trim()
		const match = isdMatch()
		return {
			company_name: String(state.partnershipCompanyName.value || "").trim(),
			registered_country: country,
			registered_state: country === "India" ? state.partnershipState.value : "",
			company_email: String(state.partnershipEmail.value || "").trim(),
			contact: match && number ? `${match.isd}-${number}` : number,
		}
	}

	function errorsOf(details: RegistrationDetails) {
		return {
			company_name: companyNameError(details.company_name),
			country: details.registered_country ? "" : "Registered country is required.",
			state: details.registered_country === "India" && !details.registered_state ? "Registered state is required." : "",
			email: emailError(details.company_email),
			contact: contactError(state.partnershipContact.value, details.contact),
		}
	}

	// Errors show under their fields only once Proceed has been pressed, as in Press.
	const partnershipErrors = computed(() =>
		state.partnershipSubmitted.value ? errorsOf(partnershipDetails()) : {},
	)

	// Proceed: shows any errors, and says whether the form can be sent.
	function isPartnershipValid(): boolean {
		state.partnershipSubmitted.value = true
		state.partnershipSubmitError.value = ""
		return !Object.values(errorsOf(partnershipDetails())).some(Boolean)
	}

	// Fills the form from saved details; the contact is split back into dialling code and number.
	function fillPartnership(details: Partial<RegistrationDetails>) {
		state.partnershipCompanyName.value = details.company_name || ""
		state.partnershipCountry.value = details.registered_country || ""
		state.partnershipState.value = details.registered_state || ""
		state.partnershipEmail.value = details.company_email || ""
		state.partnershipIsdSearch.value = ""
		const [isd, ...rest] = String(details.contact || "").split("-")
		const match = rest.length ? countries().find((c) => c.isd === isd) : null
		state.partnershipIsdCountry.value = match ? match.name : ""
		state.partnershipContact.value = rest.length ? rest.join("-") : isd
	}

	return { ...state, partnershipErrors, partnershipDetails, isPartnershipValid, fillPartnership }
}

// A logged-out visitor's details wait in this tab while they sign up; Partner Onboarding then
// registers them.
const STASH_KEY = "connect_partner_registration"

export function stashRegistration(details: RegistrationDetails) {
	try {
		window.sessionStorage.setItem(STASH_KEY, JSON.stringify(details))
	} catch {
		// Storage blocked (private mode): they fill the form again on Partner Onboarding.
	}
}

// The stashed details, once: reading them clears them.
export function takeStashedRegistration(): RegistrationDetails | null {
	try {
		const raw = window.sessionStorage.getItem(STASH_KEY)
		window.sessionStorage.removeItem(STASH_KEY)
		return raw ? JSON.parse(raw) : null
	} catch {
		return null
	}
}

// The server sends its error with <strong> around values; the form shows plain text.
export const plainError = (error: any, fallback: string) =>
	String(error?.messages?.[0] || error?.message || fallback).replace(/<[^>]*>/g, "")

function companyNameError(name: string) {
	if (!name) return "Company name is required."
	if (name.length < COMPANY_NAME_LENGTH.min) return `Company name must be at least ${COMPANY_NAME_LENGTH.min} characters.`
	if (name.length > COMPANY_NAME_LENGTH.max) return `Company name must be ${COMPANY_NAME_LENGTH.max} characters or less.`
	return ""
}

function emailError(email: string) {
	if (!email) return "Company email is required."
	return EMAIL_PATTERN.test(email) ? "" : "Enter a valid company email."
}

function contactError(number: string, contact: string) {
	if (!String(number || "").trim()) return "Contact number is required."
	const digits = contact.replace(/\D/g, "").length
	return digits < CONTACT_DIGITS.min || digits > CONTACT_DIGITS.max
		? `Contact number must be ${CONTACT_DIGITS.min}-${CONTACT_DIGITS.max} digits.`
		: ""
}
