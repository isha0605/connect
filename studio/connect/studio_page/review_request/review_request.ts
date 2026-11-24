// Where a past customer lands from a partner's review request email. The card does the work
// (ReviewRequestCard.vue); the page only hands it the link's token.

import { useColorScheme } from "frappe-ui"

export default function setup(context) {
	// Pages with the sidebar apply the person's Light, Dark or System choice through its Theme menu;
	// this page has no sidebar, so it applies the choice itself.
	useColorScheme()

	return { token: String(context.route.query.token || "") }
}
