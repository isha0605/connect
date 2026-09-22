import{Wt as e}from"./studioRenderer-DW8HOJqS.js";var t=`otp-digit-`,n=`connect-otp-input-style`;function r(e){return!!(e&&e.dataset&&String(e.dataset.componentId||``).startsWith(t))}function i(){return Array.from(document.querySelectorAll(`input[data-component-id^="${t}"]`))}function a(a){if(!document.getElementById(n)){let e=document.createElement(`style`);e.id=n,e.textContent=`
			input[data-component-id^="${t}"] {
				text-align: center;
				padding-left: 0;
				padding-right: 0;
				height: 48px;
				border-radius: 8px;
			}
		`,document.head.appendChild(e)}function o(e){let t=e.target;if(!r(t)||!t.value)return;let n=i(),a=n[n.indexOf(t)+1];a&&a.focus()}function s(e){let t=e.target;if(!r(t)||e.key!==`Backspace`||t.value)return;let n=i(),a=n[n.indexOf(t)-1];a&&a.focus()}return document.addEventListener(`input`,o),document.addEventListener(`keydown`,s),e(()=>{document.removeEventListener(`input`,o),document.removeEventListener(`keydown`,s)}),{}}export{a as default};
//# sourceMappingURL=login_signup_redesign--amDf91s.js.map