// Where a past customer lands from a partner's review request email. The card does the work
// (ReviewRequestCard.vue); the page only hands it the link's token.

export default function setup(context) {
	return { token: String(context.route.query.token || "") }
}
