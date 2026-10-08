var e=`connect-scroll-fade`,t=800;function n(){if(document.getElementById(e))return;let n=document.createElement(`style`);n.id=e,n.textContent=`
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
	`,document.head.appendChild(n);let r=new WeakMap;document.addEventListener(`scroll`,e=>{let n=e.target;!(n instanceof Element)||!n.classList.contains(`scroll-fade`)||(n.classList.add(`is-scrolling`),clearTimeout(r.get(n)),r.set(n,setTimeout(()=>n.classList.remove(`is-scrolling`),t)))},{capture:!0,passive:!0})}export{n as t};
//# sourceMappingURL=scrollFade-BkZEJ_Om.js.map