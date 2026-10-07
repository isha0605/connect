import { onScopeDispose, ref } from "vue"
import { call } from "frappe-ui"

const OTP_PREFIX = "otp-digit-"
const STYLE_ID = "connect-otp-input-style"
const RESEND_WAIT_SECONDS = 30

function isOtpBox(el) {
	return !!(el && el.dataset && String(el.dataset.componentId || "").startsWith(OTP_PREFIX))
}

function otpBoxes() {
	return Array.from(document.querySelectorAll(`input[data-component-id^="${OTP_PREFIX}"]`))
}

// The server's message for a failed call, as the person should read it.
function errorText(err, fallback) {
	const messages = (err && err.messages) || []
	return messages.join(" ") || fallback
}

// Sign in and sign up with an emailed code (connect.api.auth): email (and, to sign up, name,
// company and country) -> send_code -> the 6-digit code -> verify_code, which signs the person
// in and says where to go. A new email that came through "Log in" is asked for its profile
// (name and company) before its account is made, with the same code.
export default function setup(context) {
	const {
		route,
		authStep,
		otpOrigin,
		fullName,
		signupEmail,
		signupCountry,
		loginEmail,
		otp1,
		otp2,
		otp3,
		otp4,
		otp5,
		otp6,
		partnershipWizardOpen,
		partnershipEmail,
		partnershipCountry,
	} = context
	const digits = [otp1, otp2, otp3, otp4, otp5, otp6]

	// Where to go afterwards. Pages hand over their own path (the app's router path, or the
	// full /connect/… one); only a path on this site is followed — the server checks again.
	const next = normalizeNext(String(route.query.next || ""))
	function normalizeNext(path) {
		if (!path.startsWith("/") || path.startsWith("//")) return ""
		return path.startsWith("/connect/") || path === "/connect" ? path : `/connect${path}`
	}
	// The sidebar's Log in asks for that screen; anything else sent here with a page to go
	// back to (checkout, the sidebar's Sign up) starts on Create your account.
	if (route.query.screen === "login") authStep.value = "login"
	else if (next || route.query.screen === "signup") authStep.value = "signup"

	const signupCompany = ref("")
	// "Become a partner" signs up a partner: no company here (the wizard has it), and Partner
	// Onboarding is next.
	const signupFlow = ref(route.query.flow === "partner" ? "partner" : "buyer")
	const partnerNext = ref("")
	const profileName = ref("")
	const profileCompany = ref("")
	const authError = ref("")
	const sending = ref(false)
	const verifying = ref(false)
	const resendIn = ref(0)
	let resendTimer = null

	const email = () => String(otpOrigin.value === "signup" ? signupEmail.value : loginEmail.value).trim()
	const code = () => digits.map((d) => String(d.value || "").trim()).join("")

	function startResendWait() {
		resendIn.value = RESEND_WAIT_SECONDS
		clearInterval(resendTimer)
		resendTimer = setInterval(() => {
			resendIn.value = Math.max(0, resendIn.value - 1)
			if (!resendIn.value) clearInterval(resendTimer)
		}, 1000)
	}

	function clearDigits() {
		digits.forEach((d) => (d.value = ""))
	}

	function focusFirstDigit() {
		setTimeout(() => otpBoxes()[0]?.focus(), 50)
	}

	// Continue on "Create your account" or "Log in to your account".
	function sendCode(origin) {
		if (sending.value) return
		otpOrigin.value = origin
		authError.value = ""
		const params = { email: email() }
		if (origin === "signup") {
			Object.assign(params, {
				full_name: String(fullName.value || "").trim(),
				country: signupCountry.value || undefined,
				flow: signupFlow.value,
			})
			if (signupFlow.value === "buyer") params.company_name = String(signupCompany.value || "").trim()
			const missing = !params.full_name
				? "Enter your full name."
				: !params.email
					? "Enter your work email."
					: signupFlow.value === "buyer" && !params.company_name
						? "Enter your company name."
						: !params.country
							? "Select your country."
							: ""
			if (missing) {
				authError.value = missing
				return
			}
		} else if (!params.email) {
			authError.value = "Enter your work email."
			return
		}

		sending.value = true
		call("connect.api.auth.send_code", params)
			.then(() => {
				clearDigits()
				authStep.value = "otp"
				startResendWait()
				focusFirstDigit()
			})
			.catch((err) => {
				authError.value = errorText(err, "We couldn't send a code. Try again.")
			})
			.finally(() => {
				sending.value = false
			})
	}

	function resendCode() {
		if (resendIn.value || sending.value) return
		authError.value = ""
		sending.value = true
		call("connect.api.auth.send_code", { email: email() })
			.then(() => {
				clearDigits()
				startResendWait()
				focusFirstDigit()
			})
			.catch((err) => {
				authError.value = errorText(err, "We couldn't send a code. Try again.")
			})
			.finally(() => {
				sending.value = false
			})
	}

	// "Verify and continue", and "Create account" on Set up your profile (the same code).
	function verifyCode() {
		if (verifying.value) return
		authError.value = ""
		const params = { email: email(), code: code(), next: partnerNext.value || next || undefined }
		if (!/^\d{6}$/.test(params.code)) {
			authError.value = "Enter the 6-digit code from your email."
			return
		}
		if (authStep.value === "profile") {
			params.full_name = String(profileName.value || "").trim()
			params.company_name = String(profileCompany.value || "").trim() || undefined
			if (!params.full_name) {
				authError.value = "Enter your full name."
				return
			}
		}

		verifying.value = true
		call("connect.api.auth.verify_code", params)
			.then((res) => {
				if (res && res.needs_profile) {
					profileName.value = profileName.value || String(fullName.value || "")
					authStep.value = "profile"
					verifying.value = false
					return
				}
				// A full reload, so every page sees the new session.
				window.location.href = (res && res.redirect) || "/connect/partner-directory-redesign"
			})
			.catch((err) => {
				verifying.value = false
				authError.value = errorText(err, "That code didn't work. Try again.")
			})
	}

	function useDifferentEmail() {
		authError.value = ""
		authStep.value = otpOrigin.value
	}

	function showScreen(step) {
		authError.value = ""
		authStep.value = step
	}

	// From the "Become a partner" wizard, for a visitor without an account: sign up as a
	// partner, then on to Partner Onboarding, which registers the stashed details.
	function startPartnerSignup(target) {
		signupFlow.value = "partner"
		partnerNext.value = normalizeNext(new URL(target, window.location.origin).pathname)
		signupEmail.value = signupEmail.value || partnershipEmail.value || ""
		signupCountry.value = signupCountry.value || partnershipCountry.value || ""
		partnershipWizardOpen.value = false
		showScreen("signup")
	}

	// frappe-ui's TextInput puts `class` and `style` on its wrapper div and forwards every
	// *other* attr to the inner <input> (see attrsWithoutClassStyle in TextInput.vue). So a
	// block's textAlign can never reach the input, and text-align isn't inherited into form
	// controls — a stylesheet is the only way to centre the digits. data-component-id does land
	// on the input, which gives the selector to hang it off.
	if (!document.getElementById(STYLE_ID)) {
		const style = document.createElement("style")
		style.id = STYLE_ID
		// TextInput's tallest size is h-10 (40px) and its radius comes from the same size
		// class, but the reference boxes are 48px with an ~8px radius — both have to be set
		// here too, for the same reason the alignment does.
		style.textContent = `
			input[data-component-id^="${OTP_PREFIX}"] {
				text-align: center;
				padding-left: 0;
				padding-right: 0;
				height: 48px;
				border-radius: 8px;
			}
		`
		document.head.appendChild(style)
	}

	// Typing a digit advances to the next box; backspace in an empty box steps back; pasting
	// the whole code fills every box.
	function onInput(event) {
		const el = event.target
		if (!isOtpBox(el) || !el.value) return
		const boxes = otpBoxes()
		const next = boxes[boxes.indexOf(el) + 1]
		if (next) next.focus()
	}

	function onKeydown(event) {
		const el = event.target
		if (!isOtpBox(el)) return
		if (event.key === "Enter") {
			verifyCode()
			return
		}
		if (event.key !== "Backspace" || el.value) return
		const boxes = otpBoxes()
		const prev = boxes[boxes.indexOf(el) - 1]
		if (prev) prev.focus()
	}

	function onPaste(event) {
		if (!isOtpBox(event.target)) return
		const pasted = (event.clipboardData?.getData("text") || "").replace(/\D/g, "").slice(0, 6)
		if (pasted.length < 2) return
		event.preventDefault()
		pasted.split("").forEach((digit, i) => (digits[i].value = digit))
		otpBoxes()[Math.min(pasted.length, 6) - 1]?.focus()
	}

	document.addEventListener("input", onInput)
	document.addEventListener("keydown", onKeydown)
	document.addEventListener("paste", onPaste)

	onScopeDispose(() => {
		document.removeEventListener("input", onInput)
		document.removeEventListener("keydown", onKeydown)
		document.removeEventListener("paste", onPaste)
		clearInterval(resendTimer)
	})

	return {
		signupCompany,
		signupFlow,
		profileName,
		profileCompany,
		authError,
		sending,
		verifying,
		resendIn,
		sendCode,
		resendCode,
		verifyCode,
		useDifferentEmail,
		showScreen,
		startPartnerSignup,
	}
}
