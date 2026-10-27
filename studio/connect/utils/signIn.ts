// Signing in happens on Connect's own page (Login Signup Redesign), never on Frappe's /login,
// which is Desk's. The sign-in page comes back to `next` afterwards: by default, the page the
// person is on. Block scripts can't import this, so they build the same URL inline.

export const SIGN_IN_PAGE = "/connect/login-signup-redesign"

// screen: "login" or "signup"; left out, the page picks (Create your account, when there's a
// page to go back to).
export function signInUrl({ screen = "", next = currentPath() } = {}) {
	const query = new URLSearchParams()
	if (screen) query.set("screen", screen)
	if (next) query.set("next", next)
	const search = query.toString()
	return search ? `${SIGN_IN_PAGE}?${search}` : SIGN_IN_PAGE
}

export function goToSignIn(options = {}) {
	window.location.href = signInUrl(options)
}

// Signs out, then shows the sign-in page.
export function signOut(call) {
	return call("logout").then(() => {
		window.location.href = signInUrl({ screen: "login", next: "" })
	})
}

function currentPath() {
	return window.location.pathname + window.location.search
}
