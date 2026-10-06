import{rn as e}from"./studioRenderer-BWQDbASr.js";import{i as t}from"./checkoutSession-BUzOy3KT.js";var n=`otp-digit-`,r=`connect-otp-input-style`;function i(e){return!!(e&&e.dataset&&String(e.dataset.componentId||``).startsWith(n))}function a(){return Array.from(document.querySelectorAll(`input[data-component-id^="${n}"]`))}function o(o){let{route:s,router:c,authStep:l,otpOrigin:u,fullName:d,signupEmail:f,signupCountry:p,loginEmail:m}=o,h=String(s.query.next||``),g=h.startsWith(`/`)&&!h.startsWith(`//`)?h:``;g&&(l.value=`signup`);function _(){let e=u.value===`signup`;t({full_name:e?d.value:``,email:e?f.value:m.value,country:e?p.value:``}),g&&c.push(g)}if(!document.getElementById(r)){let e=document.createElement(`style`);e.id=r,e.textContent=`
			input[data-component-id^="${n}"] {
				text-align: center;
				padding-left: 0;
				padding-right: 0;
				height: 48px;
				border-radius: 8px;
			}
		`,document.head.appendChild(e)}function v(e){let t=e.target;if(!i(t)||!t.value)return;let n=a(),r=n[n.indexOf(t)+1];r&&r.focus()}function y(e){let t=e.target;if(!i(t)||e.key!==`Backspace`||t.value)return;let n=a(),r=n[n.indexOf(t)-1];r&&r.focus()}return document.addEventListener(`input`,v),document.addEventListener(`keydown`,y),e(()=>{document.removeEventListener(`input`,v),document.removeEventListener(`keydown`,y)}),{continueAfterVerify:_}}export{o as default};
//# sourceMappingURL=login_signup_redesign-BXQrGcFK.js.map