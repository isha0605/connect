// Who the signed-in person is (connect.api.account.get_my_context), shared by every page that
// asks for it. Studio rebuilds a page and its own resources on each navigation, so a page-level
// myContext starts empty and the sidebar hides its items until it loads. One cached resource
// keeps the last answer while a new page refreshes it in the background.

import { createResource } from "frappe-ui"

export function useMyContext() {
	return createResource({
		url: "connect.api.account.get_my_context",
		// frappe-ui also stores the answer in IndexedDB, so the key carries the user: after a
		// switch of account, the last person's context must never show.
		cache: ["connect-my-context", signedInUser()],
		auto: true,
	})
}

// Frappe sets the user_id cookie on sign-in and sign-out; it reads "Guest" for a visitor.
function signedInUser() {
	const cookie = document.cookie.split("; ").find((part) => part.startsWith("user_id="))
	return cookie ? decodeURIComponent(cookie.slice("user_id=".length)) : "Guest"
}
