const FLAG_BASE = "/assets/connect/images/flags/"

// Country name -> ISO 3166-1 alpha-2, for the flag swatch on the location pill. Includes
// the short forms the partner records actually use (UK, USA, UAE) alongside full names.
const COUNTRY_CODES = {
	"Afghanistan": "af",
	"Albania": "al",
	"Algeria": "dz",
	"Andorra": "ad",
	"Angola": "ao",
	"Argentina": "ar",
	"Armenia": "am",
	"Australia": "au",
	"Austria": "at",
	"Azerbaijan": "az",
	"Bahamas": "bs",
	"Bahrain": "bh",
	"Bangladesh": "bd",
	"Barbados": "bb",
	"Belarus": "by",
	"Belgium": "be",
	"Belize": "bz",
	"Benin": "bj",
	"Bhutan": "bt",
	"Bolivia": "bo",
	"Bosnia and Herzegovina": "ba",
	"Botswana": "bw",
	"Brazil": "br",
	"Brunei": "bn",
	"Bulgaria": "bg",
	"Burkina Faso": "bf",
	"Burundi": "bi",
	"Cambodia": "kh",
	"Cameroon": "cm",
	"Canada": "ca",
	"Chad": "td",
	"Chile": "cl",
	"China": "cn",
	"Colombia": "co",
	"Congo - Kinshasa": "cd",
	"Congo Kinshasa": "cd",
	"DR Congo": "cd",
	"Congo - Brazzaville": "cg",
	"Costa Rica": "cr",
	"Croatia": "hr",
	"Cuba": "cu",
	"Cyprus": "cy",
	"Czechia": "cz",
	"Czech Republic": "cz",
	"Denmark": "dk",
	"Djibouti": "dj",
	"Dominican Republic": "do",
	"Ecuador": "ec",
	"Egypt": "eg",
	"El Salvador": "sv",
	"Estonia": "ee",
	"Ethiopia": "et",
	"Fiji": "fj",
	"Finland": "fi",
	"France": "fr",
	"Gabon": "ga",
	"Gambia": "gm",
	"Georgia": "ge",
	"Germany": "de",
	"Ghana": "gh",
	"Greece": "gr",
	"Guatemala": "gt",
	"Guyana": "gy",
	"Haiti": "ht",
	"Honduras": "hn",
	"Hong Kong": "hk",
	"Hungary": "hu",
	"Iceland": "is",
	"India": "in",
	"Indonesia": "id",
	"Iran": "ir",
	"Iraq": "iq",
	"Ireland": "ie",
	"Israel": "il",
	"Italy": "it",
	"Ivory Coast": "ci",
	"Jamaica": "jm",
	"Japan": "jp",
	"Jordan": "jo",
	"Kazakhstan": "kz",
	"Kenya": "ke",
	"Kuwait": "kw",
	"Kyrgyzstan": "kg",
	"Laos": "la",
	"Latvia": "lv",
	"Lebanon": "lb",
	"Lesotho": "ls",
	"Liberia": "lr",
	"Libya": "ly",
	"Liechtenstein": "li",
	"Lithuania": "lt",
	"Luxembourg": "lu",
	"Madagascar": "mg",
	"Malawi": "mw",
	"Malaysia": "my",
	"Maldives": "mv",
	"Mali": "ml",
	"Malta": "mt",
	"Mauritania": "mr",
	"Mauritius": "mu",
	"Mexico": "mx",
	"Moldova": "md",
	"Monaco": "mc",
	"Mongolia": "mn",
	"Montenegro": "me",
	"Morocco": "ma",
	"Mozambique": "mz",
	"Myanmar": "mm",
	"Namibia": "na",
	"Nepal": "np",
	"Netherlands": "nl",
	"New Zealand": "nz",
	"Nicaragua": "ni",
	"Niger": "ne",
	"Nigeria": "ng",
	"North Macedonia": "mk",
	"Norway": "no",
	"Oman": "om",
	"Pakistan": "pk",
	"Panama": "pa",
	"Papua New Guinea": "pg",
	"Paraguay": "py",
	"Peru": "pe",
	"Philippines": "ph",
	"Poland": "pl",
	"Portugal": "pt",
	"Qatar": "qa",
	"Romania": "ro",
	"Russia": "ru",
	"Rwanda": "rw",
	"Saudi Arabia": "sa",
	"Senegal": "sn",
	"Serbia": "rs",
	"Seychelles": "sc",
	"Sierra Leone": "sl",
	"Singapore": "sg",
	"Slovakia": "sk",
	"Slovenia": "si",
	"South Africa": "za",
	"South Korea": "kr",
	"South Sudan": "ss",
	"Spain": "es",
	"Sri Lanka": "lk",
	"Sudan": "sd",
	"Suriname": "sr",
	"Sweden": "se",
	"Switzerland": "ch",
	"Syria": "sy",
	"Taiwan": "tw",
	"Tajikistan": "tj",
	"Tanzania": "tz",
	"Thailand": "th",
	"Togo": "tg",
	"Trinidad and Tobago": "tt",
	"Tunisia": "tn",
	"Turkey": "tr",
	"Turkmenistan": "tm",
	"Uganda": "ug",
	"Ukraine": "ua",
	"United Arab Emirates": "ae",
	"UAE": "ae",
	"United Kingdom": "gb",
	"UK": "gb",
	"United States": "us",
	"USA": "us",
	"Uruguay": "uy",
	"Uzbekistan": "uz",
	"Venezuela": "ve",
	"Vietnam": "vn",
	"Yemen": "ye",
	"Zambia": "zm",
	"Zimbabwe": "zw",
}

function countryCode(partnerDoc) {
	return COUNTRY_CODES[(partnerDoc && partnerDoc.country) || ""] || ""
}

// One formatter for the whole page. Building an Intl formatter is expensive and
// formatRelativeTime runs once per visible review on every re-render.
const RELATIVE_TIME = new Intl.RelativeTimeFormat("en-US", { numeric: "always" })

const DAY_MS = 86400000

export default function setup(context) {
	// Review timestamps render inside the reviews list, so this is called once per visible
	// row on every re-render. That is exactly why it belongs here rather than in a `{{ }}`
	// binding — a binding would rebuild the whole expression for every row, every time.
	//
	// Months and years are the same rough 30-day / 12-month buckets the page used before;
	// Intl handles the pluralisation ("1 day ago" vs "5 days ago") that used to be spelled
	// out by hand.
	function formatRelativeTime(value) {
		const reviewedOn = value ? new Date(value) : null
		if (!reviewedOn || Number.isNaN(reviewedOn.getTime())) return ""

		const days = Math.floor((Date.now() - reviewedOn.getTime()) / DAY_MS)
		if (days < 1) return "Today"
		if (days < 30) return RELATIVE_TIME.format(-days, "day")

		const months = Math.floor(days / 30)
		if (months < 12) return RELATIVE_TIME.format(-months, "month")

		return RELATIVE_TIME.format(-Math.floor(months / 12), "year")
	}

	// The flag lived in two style bindings that each inlined the whole COUNTRY_CODES
	// literal — 8.4KB of expression re-parsed on every render to resolve one country.
	function countryFlagUrl(partnerDoc) {
		const code = countryCode(partnerDoc)
		return code ? `url("${FLAG_BASE}${code}.svg")` : 'url("")'
	}

	function hasCountryFlag(partnerDoc) {
		return Boolean(countryCode(partnerDoc))
	}

	return { formatRelativeTime, countryFlagUrl, hasCountryFlag }
}
