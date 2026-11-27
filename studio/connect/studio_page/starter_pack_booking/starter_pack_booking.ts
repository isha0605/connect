import { useMyContext } from "@app/utils/myContext"

export default function setup() {
	return { myContext: useMyContext() }
}
