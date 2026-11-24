// Money as the partner pages show it: each amount in the currency it comes in. A rate in another
// currency than the viewer's also gives a rough amount in theirs, so customers can compare partners.

// A partner with no country yet has no currency.
export const DEFAULT_CURRENCY = "INR"

// Rupees group as 1,00,000; dollars as 100,000.
const LOCALES = { INR: "en-IN", USD: "en-US" }

// The company rate Frappe Cloud uses (USD_TO_INR in connect/partner/press_integration.py), for the
// sample pages written in rupees and for the rough amounts beside a rate.
const INR_PER_USD = 83

function localeOf(currency) {
	return LOCALES[currency] || LOCALES[DEFAULT_CURRENCY]
}

// "₹" or "$", for a field's label.
export function currencySymbol(currency = DEFAULT_CURRENCY) {
	const parts = new Intl.NumberFormat(localeOf(currency), { style: "currency", currency }).formatToParts(0)
	return parts.find((part) => part.type === "currency")?.value || currency
}

export function formatMoney(amount, currency = DEFAULT_CURRENCY) {
	const format = new Intl.NumberFormat(localeOf(currency), { style: "currency", currency, maximumFractionDigits: 0 })
	return format.format(amount || 0)
}

// India pays in rupees; every other country in dollars, as for a partner's own currency.
export function currencyOfCountry(country) {
	return country === "India" ? "INR" : "USD"
}

// The signed-in customer's currency, from their company's country. Empty for a guest, a partner, or a
// customer with no country, who see each rate as it is.
export function viewerCurrency(myContext) {
	const country = myContext?.customer?.country
	return country ? currencyOfCountry(country) : ""
}

function convert(amount, from, to) {
	if (from === "USD" && to === "INR") return Math.round(amount * INR_PER_USD)
	if (from === "INR" && to === "USD") return Math.round(amount / INR_PER_USD)
	return null
}

// A partner's hourly rate, in their currency: "From ₹2,000/hr" or "From $25/hr". For a viewer who pays
// in the other currency it adds a rough amount in theirs: "From ₹3,700/hr (≈ $45)".
export function hourlyRate(amount, currency, inCurrency = "") {
	const rate = `From ${formatMoney(amount, currency)}/hr`
	const rough = inCurrency && inCurrency !== currency ? convert(amount, currency, inCurrency) : null
	return rough === null ? rate : `${rate} (≈ ${formatMoney(rough, inCurrency)})`
}

// The example in a quote box: about the same project in either currency.
const EXAMPLE_QUOTES = { INR: 400000, USD: 5000 }

export function exampleQuote(currency = DEFAULT_CURRENCY) {
	return String(EXAMPLE_QUOTES[currency] || EXAMPLE_QUOTES[DEFAULT_CURRENCY])
}

// Short enough to read at a glance on a card: ₹5.05L and ₹45k, or $7.5k and $1.2M.
export function compactMoney(amount, currency = DEFAULT_CURRENCY) {
	if (currency === "INR") {
		if (amount >= 100000) return `₹${Number((amount / 100000).toFixed(2))}L`
		if (amount >= 1000) return `₹${Math.round(amount / 1000)}k`
		return `₹${amount}`
	}

	const symbol = formatMoney(0, currency).replace(/[\d.,\s]/g, "")
	if (amount >= 1000000) return `${symbol}${Number((amount / 1000000).toFixed(2))}M`
	if (amount >= 1000) return `${symbol}${Number((amount / 1000).toFixed(1))}k`
	return `${symbol}${amount}`
}

// A sample amount, written in rupees, in the partner's currency.
export function sampleAmount(rupees, currency) {
	return currency === "USD" ? Math.round(rupees / INR_PER_USD) : rupees
}
