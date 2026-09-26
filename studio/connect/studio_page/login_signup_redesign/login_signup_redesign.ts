import { onScopeDispose } from "vue"

const OTP_PREFIX = "otp-digit-"
const STYLE_ID = "connect-otp-input-style"

function isOtpBox(el) {
	return !!(el && el.dataset && String(el.dataset.componentId || "").startsWith(OTP_PREFIX))
}

function otpBoxes() {
	return Array.from(document.querySelectorAll(`input[data-component-id^="${OTP_PREFIX}"]`))
}

export default function setup(context) {
	const { route, router, authStep } = context

	// Sent here from Starter Pack checkout: start on "Create your account", and carry on to
	// checkout after the (mock) code. Only an in-app path is followed, never another site.
	const next = String(route.query.next || "")
	const nextPath = next.startsWith("/") && !next.startsWith("//") ? next : ""
	if (nextPath) authStep.value = "signup"

	// Signup and the emailed code are UI only for now: nothing is created or checked, and
	// the visitor is still a guest afterwards.
	function continueAfterVerify() {
		if (nextPath) router.push(nextPath)
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

	// Typing a digit advances to the next box; backspace in an empty box steps back.
	function onInput(event) {
		const el = event.target
		if (!isOtpBox(el) || !el.value) return
		const boxes = otpBoxes()
		const next = boxes[boxes.indexOf(el) + 1]
		if (next) next.focus()
	}

	function onKeydown(event) {
		const el = event.target
		if (!isOtpBox(el) || event.key !== "Backspace" || el.value) return
		const boxes = otpBoxes()
		const prev = boxes[boxes.indexOf(el) - 1]
		if (prev) prev.focus()
	}

	document.addEventListener("input", onInput)
	document.addEventListener("keydown", onKeydown)

	onScopeDispose(() => {
		document.removeEventListener("input", onInput)
		document.removeEventListener("keydown", onKeydown)
	})

	return { continueAfterVerify }
}
