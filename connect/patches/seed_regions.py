# Copyright (c) 2026
# For license information, please see license.txt

import frappe

# Region -> (countries shown in the directory filter, in display order; every other country).
# The regions are frappe.io's own (frappe.io/partners/regions). Names are Frappe Country names.
REGIONS = {
	"Asia Pacific": (
		[
			"India", "Philippines", "Indonesia", "Myanmar", "Pakistan", "Singapore", "Australia",
			"Bangladesh", "China", "Sri Lanka", "Thailand", "Vietnam",
		],
		[
			"Afghanistan", "American Samoa", "Antarctica", "Armenia", "Azerbaijan", "Bhutan",
			"British Indian Ocean Territory", "Brunei Darussalam", "Cambodia", "Christmas Island",
			"Cocos (Keeling) Islands", "Cook Islands", "Fiji", "French Polynesia",
			"French Southern Territories", "Georgia", "Guam", "Heard Island and McDonald Islands",
			"Hong Kong", "Japan", "Kazakhstan", "Kiribati", "Korea, Democratic Peoples Republic of",
			"Korea, Republic of", "Kyrgyzstan", "Lao Peoples Democratic Republic", "Macao",
			"Malaysia", "Maldives", "Marshall Islands", "Micronesia, Federated States of",
			"Mongolia", "Nauru", "Nepal", "New Caledonia", "New Zealand", "Niue", "Norfolk Island",
			"Northern Mariana Islands", "Palau", "Papua New Guinea", "Pitcairn", "Samoa",
			"Solomon Islands", "Taiwan", "Tajikistan", "Timor-Leste", "Tokelau", "Tonga",
			"Turkmenistan", "Tuvalu", "United States Minor Outlying Islands", "Uzbekistan",
			"Vanuatu", "Wallis and Futuna",
		],
	),
	"Middle East": (
		[
			"Saudi Arabia", "United Arab Emirates", "Egypt", "Qatar", "Kuwait", "Oman", "Bahrain",
			"Iraq", "Jordan", "Libya", "Yemen",
		],
		[
			"Iran", "Israel", "Lebanon", "Palestinian Territory, Occupied", "Syria",
		],
	),
	"Africa": (
		[
			"Kenya", "Tanzania", "Congo, The Democratic Republic of the", "Ghana", "Mauritius",
			"Nigeria", "South Africa", "Uganda",
		],
		[
			"Algeria", "Angola", "Benin", "Botswana", "Bouvet Island", "Burkina Faso", "Burundi",
			"Cameroon", "Cape Verde", "Central African Republic", "Chad", "Comoros", "Congo",
			"Djibouti", "Equatorial Guinea", "Eritrea", "Ethiopia", "Gabon", "Gambia", "Guinea",
			"Guinea-Bissau", "Ivory Coast", "Lesotho", "Liberia", "Madagascar", "Malawi", "Mali",
			"Mauritania", "Mayotte", "Morocco", "Mozambique", "Namibia", "Niger", "Rwanda",
			"Réunion", "Saint Helena, Ascension and Tristan da Cunha", "Sao Tome and Principe",
			"Senegal", "Seychelles", "Sierra Leone", "Somalia", "South Sudan", "Sudan", "Swaziland",
			"Togo", "Tunisia", "Western Sahara", "Zambia", "Zimbabwe",
		],
	),
	"Europe": (
		[
			"Germany", "France", "Italy", "Malta", "Netherlands", "Spain", "Switzerland",
			"United Kingdom",
		],
		[
			"Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina",
			"Bulgaria", "Croatia", "Cyprus", "Czech Republic", "Denmark", "Estonia",
			"Faroe Islands", "Finland", "Gibraltar", "Greece", "Guernsey",
			"Holy See (Vatican City State)", "Hungary", "Iceland", "Ireland", "Isle of Man",
			"Jersey", "Kosovo", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg", "Macedonia",
			"Moldova, Republic of", "Monaco", "Montenegro", "Norway", "Poland", "Portugal",
			"Romania", "Russian Federation", "San Marino", "Serbia", "Slovakia", "Slovenia",
			"Svalbard and Jan Mayen", "Sweden", "Türkiye", "Ukraine", "Åland Islands",
		],
	),
	"Americas": (
		[
			"United States", "Canada",
		],
		[
			"Anguilla", "Antigua and Barbuda", "Argentina", "Aruba", "Bahamas", "Barbados",
			"Belize", "Bermuda", "Bolivia, Plurinational State of",
			"Bonaire, Sint Eustatius and Saba", "Brazil", "Cayman Islands", "Chile", "Colombia",
			"Costa Rica", "Cuba", "Curaçao", "Dominica", "Dominican Republic", "Ecuador",
			"El Salvador", "Falkland Islands (Malvinas)", "French Guiana", "Greenland", "Grenada",
			"Guadeloupe", "Guatemala", "Guyana", "Haiti", "Honduras", "Jamaica", "Martinique",
			"Mexico", "Montserrat", "Nicaragua", "Panama", "Paraguay", "Peru", "Puerto Rico",
			"Saint Barthélemy", "Saint Kitts and Nevis", "Saint Lucia",
			"Saint Martin (French part)", "Saint Pierre and Miquelon",
			"Saint Vincent and the Grenadines", "Sint Maarten (Dutch part)",
			"South Georgia and the South Sandwich Islands", "Suriname", "Trinidad and Tobago",
			"Turks and Caicos Islands", "Uruguay", "Venezuela, Bolivarian Republic of",
			"Virgin Islands, British", "Virgin Islands, U.S.",
		],
	),
}


def execute():
	"""Creates the regions and their countries. Skips a region that exists, so it never undoes edits made in Desk."""
	for region_name, (filter_countries, other_countries) in REGIONS.items():
		if frappe.db.exists("Region", region_name):
			continue

		region = frappe.new_doc("Region")
		region.region_name = region_name
		for country in filter_countries:
			region.append("countries", {"country": country, "show_in_filter": 1})
		for country in other_countries:
			region.append("countries", {"country": country})
		region.insert(ignore_permissions=True)
