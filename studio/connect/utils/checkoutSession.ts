// Starter Pack orders' access keys, kept in this browser tab only.
//
// An order is read back with the access key checkout returns (its own buyer can also read it
// signed in), so the key is kept here — Razorpay sends the buyer back to this same tab.
// sessionStorage can be missing or throw (private modes, blocked storage); every read and
// write here survives that.

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
