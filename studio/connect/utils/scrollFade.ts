// The prototype's scrollbar: a thin --outline-gray-3 thumb on no track, shown only while the
// user is scrolling. Studio blocks can't style ::-webkit-scrollbar, so it's a stylesheet keyed
// off the `scroll-fade` class, plus one scroll listener (capture phase, so it hears scrolls on
// any element) that marks the scrolling element for a moment. Both are installed once per
// document, so every page can call installScrollFade() and give its scroll area the class.
const SCROLL_STYLE_ID = "connect-scroll-fade"
const SCROLL_IDLE_MS = 800

export function installScrollFade() {
	if (document.getElementById(SCROLL_STYLE_ID)) return
	const style = document.createElement("style")
	style.id = SCROLL_STYLE_ID
	style.textContent = `
		.scroll-fade::-webkit-scrollbar { width: 7px; height: 7px; }
		.scroll-fade::-webkit-scrollbar-track { background: transparent; }
		/* the transparent border insets a 5px thumb 1px from the edge, as in the prototype */
		.scroll-fade::-webkit-scrollbar-thumb {
			background: transparent;
			background-clip: padding-box;
			border: 1px solid transparent;
			border-radius: 999px;
		}
		.scroll-fade.is-scrolling::-webkit-scrollbar-thumb { background-color: var(--outline-gray-3); }
		@supports not selector(::-webkit-scrollbar) {
			.scroll-fade { scrollbar-width: thin; scrollbar-color: transparent transparent; }
			.scroll-fade.is-scrolling { scrollbar-color: var(--outline-gray-3) transparent; }
		}
	`
	document.head.appendChild(style)

	const timers = new WeakMap()
	document.addEventListener(
		"scroll",
		(event) => {
			const el = event.target
			if (!(el instanceof Element) || !el.classList.contains("scroll-fade")) return
			el.classList.add("is-scrolling")
			clearTimeout(timers.get(el))
			timers.set(el, setTimeout(() => el.classList.remove("is-scrolling"), SCROLL_IDLE_MS))
		},
		{ capture: true, passive: true },
	)
}
