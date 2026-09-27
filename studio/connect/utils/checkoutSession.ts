// The Starter Pack buyer and their orders' access keys, kept in this browser tab only.
//
// Sign-in is a mock: the login and signup screens check nothing and create nothing on the
// server. What someone types there is kept here for the rest of the tab's life (reloads
// included, gone when the tab closes), carried into the checkout form, and only reaches
// the server as the buyer's name and email on the order they place.
//
// An order placed without a real account can only be read back with the access key
// checkout returns, so the key is kept here too — Razorpay sends the buyer back to this
// same tab. sessionStorage can be missing or throw (private modes, blocked storage);
// every read and write here survives that.

const BUYER = "connect.starterPack.buyer"
const ORDER_KEYS = "connect.starterPack.orderKeys"

function read(name) {
	try {
		return JSON.parse(window.sessionStorage.getItem(name) || "null")
	} catch {
		return null
	}
}

function write(name, value) {
	try {
		window.sessionStorage.setItem(name, JSON.stringify(value))
	} catch {
		// Nothing to fall back to: without storage, the buyer is asked again.
	}
}

// { full_name, email, country } as entered on the sign-in screens, or null if this tab
// hasn't been through them.
export function readBuyer() {
	return read(BUYER)
}

export function saveBuyer(buyer) {
	write(BUYER, {
		full_name: String(buyer?.full_name || "").trim(),
		email: String(buyer?.email || "").trim(),
		country: String(buyer?.country || "").trim(),
	})
}

// Checkout's reply: { order, payment_request, key }. The key is filed under both names,
// since the return from Razorpay only knows the payment request.
export function rememberOrderKey(result) {
	if (!result?.key) return
	const keys = read(ORDER_KEYS) || {}
	if (result.order) keys[result.order] = result.key
	if (result.payment_request) keys[result.payment_request] = result.key
	write(ORDER_KEYS, keys)
}

export function orderKey(name) {
	return (read(ORDER_KEYS) || {})[name] || undefined
}
