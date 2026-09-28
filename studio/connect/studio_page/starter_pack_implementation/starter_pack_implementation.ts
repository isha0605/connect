import { ref } from "vue"
import { toast, call } from "frappe-ui"

// Static mockup for the "Starter Pack implementation" checklist (Figma: Frappe Connect > Starter
// pack implementation). Every field on the right panel and every step's copy is hardcoded here --
// there's no backing DocType yet. When one exists, replace the literal strings below with a
// resource load (see partner_onboarding.ts's context.partnerApplication for the pattern) and this
// template's {{ }} bindings won't need to change.

const STEP_ORDER = ["pay-upfront", "terms", "login", "billing", "site", "share-url"]

export default function setup(context) {
	// ---- Steps accordion ----
	// Unlike partner_onboarding.ts, completion here is static (only "pay-upfront" is ever done),
	// so there's no watch() re-deriving openStep as the backend changes -- it just starts on
	// "terms" and stays wherever the visitor last clicked.
	function stepStatus(key) {
		return key === "pay-upfront" ? "completed" : "pending"
	}

	const openStep = ref("terms")

	function isStepOpen(key) {
		return openStep.value === key
	}

	// One step open at a time, like the Figma reference.
	function toggleStep(key) {
		openStep.value = openStep.value === key ? "" : key
	}

	// ---- Hosted site URL (last step's input) ----
	const hostedSiteUrl = ref("")

	function submitHostedSiteUrl() {
		const url = String(hostedSiteUrl.value || "").trim()
		if (!/^https?:\/\/.+/.test(url)) {
			toast.error("Enter a valid URL, starting with http:// or https://")
			return
		}
		toast.success("Thanks! We'll take it from here.")
	}

	// ---- Placeholder actions (no backend behind them yet) ----
	function viewTermsDetails() {
		toast.info("Terms & Conditions details are coming soon.")
	}

	function openFeedback() {
		toast.info("Feedback form is coming soon.")
	}

	// ---- Rail: logo account menu (same as the messaging page) ----
	function accountMenuOptions() {
		return [
			{
				icon: "lucide-log-out",
				label: "Log out",
				onClick: () => {
					call("logout").then(() => {
						window.location.href = "/login"
					})
				},
			},
		]
	}

	return {
		stepStatus,
		openStep,
		isStepOpen,
		toggleStep,
		hostedSiteUrl,
		submitHostedSiteUrl,
		viewTermsDetails,
		openFeedback,
		accountMenuOptions,
	}
}
