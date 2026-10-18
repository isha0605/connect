// The Starter Packs landing page: the three packs, each added to the cart from its card,
// and what the cart comes to. The cart itself lives in @app/utils/starterPackCart.

import { starterPackCart } from "@app/utils/starterPackCart"

export default function setup(context) {
	return { ...starterPackCart(context) }
}
