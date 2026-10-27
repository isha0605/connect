// Keyboard use on the Starter Pack pages.
//
// Some clickable things are laid out as plain boxes in Studio (an FAQ question, a step's row,
// Remove), which a keyboard never reaches. Their blocks carry tabindex="0" and role="button"
// (or "link") as attributes; keyboardAccess() makes Enter, and Space for buttons, click them as
// on a real button, and shows a focus ring when they're reached with Tab. Studio gives every
// block outline-none, so without the ring nobody can see where they are.
//
// focusFirstField() puts the cursor in a form's first field when it opens, as most sites do.

import { watch } from "vue"

const FOCUS_RING = `
[role="button"][tabindex="0"]:not(button):focus-visible,
[role="link"][tabindex="0"]:not(a):focus-visible {
	outline: 2px solid var(--outline-gray-4, #999) !important;
	outline-offset: 2px;
}`

let installed = false

function onKeydown(event) {
	if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return
	const el = event.target
	if (!(el instanceof HTMLElement) || el.getAttribute("tabindex") !== "0") return
	if (el.matches("button, a, input, textarea, select, [contenteditable]")) return
	const role = el.getAttribute("role")
	if (event.key === "Enter" ? role === "button" || role === "link" : event.key === " " && role === "button") {
		event.preventDefault() // Space would scroll the page
		el.click()
	}
}

// Once per tab: every Starter Pack page calls it, and they share one app.
export function keyboardAccess() {
	if (installed) return
	installed = true
	document.addEventListener("keydown", onKeydown)
	const style = document.createElement("style")
	style.dataset.connect = "keyboard"
	style.textContent = FOCUS_RING
	document.head.appendChild(style)
}

const FIELDS = 'input:not([type="hidden"]):not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled])'

// The first field inside a block. A dialog renders a moment after it's opened and puts focus
// on its own close button, so this waits for the block to appear and then moves focus.
export function focusFirstField(componentId, { tries = 20 } = {}) {
	const field = document.querySelector(`[data-component-id="${componentId}"]`)?.querySelector(FIELDS)
	if (field) {
		field.focus()
		return
	}
	if (tries > 0) setTimeout(() => focusFirstField(componentId, { tries: tries - 1 }), 30)
}

// focusFirstField() each time a dialog's open flag turns on.
export function focusFirstFieldOnOpen(openRef, componentId) {
	watch(openRef, (open) => {
		if (open) setTimeout(() => focusFirstField(componentId), 50)
	})
}
