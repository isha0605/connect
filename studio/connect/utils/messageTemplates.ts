// The Templates dialog a partner's team opens from the message box on a lead or a customer:
// pick a saved reply to put in the box, or write and edit their own. The same dialog, with the
// same blocks, as the Messages page; this is its logic for pages that are not that page.

import { h, nextTick, ref } from "vue"

// The dialog's inputs keep their own text: Studio re-evaluates every {{ }} on a page whenever a
// returned ref changes, so an input bound to page state lags on every keystroke. We read the
// text from the element, and push it into state after a short pause.
function inputElement(componentId, tag = "textarea") {
	const el = document.querySelector(`[data-component-id="${componentId}"]`)
	return (el?.tagName === tag.toUpperCase() ? el : el?.querySelector(tag)) as HTMLInputElement | HTMLTextAreaElement | null
}

// The dispatched "input" event matters: frappe-ui's inputs keep an internal copy of their value
// and would reset the element to it on the next render.
function setInputText(el, text, caret = null) {
	if (!el) return
	if (el.value !== text) {
		el.value = text
		if (caret != null) el.setSelectionRange(caret, caret)
		el.dispatchEvent(new Event("input", { bubbles: true }))
	} else if (caret != null) {
		el.setSelectionRange(caret, caret)
	}
}

// `me` is the signed-in user (a ref), who alone edits the templates they wrote. `onInsert`
// gets the template the user picked, to put in the message box.
export function useMessageTemplates({ call, toast, me, onInsert }) {
	const showTemplatesDialog = ref(false)
	const savedTemplates = ref([])

	function loadTemplates() {
		return call("connect.api.message_templates.get_my_message_templates")
			.then((rows) => (savedTemplates.value = rows || []))
			.catch(() => {})
	}
	loadTemplates()

	function insertTemplate(template) {
		showTemplatesDialog.value = false
		onInsert(template)
	}

	// ---- Templates dialog ----
	// Modelled on Helpdesk's Saved Replies: one dialog that swaps between the list (search, scope
	// filter, cards) and the "new template" form, instead of stacking a second dialog on top.
	// Scopes: Personal (only me), Team (my company), Global (side-wide, managed in Desk).
	const TEMPLATE_SCOPE_LABELS = { All: "All", Personal: "Personal", Team: "My Team", Global: "Global" }
	const TEMPLATE_SCOPE_ICONS = { Personal: "lucide-user", Team: "lucide-users", Global: "lucide-globe" }

	const templatesView = ref("list")
	const templateSearchQuery = ref("")
	const templateScopeFilter = ref("Personal")
	const newTemplateTitle = ref("")
	const newTemplateContent = ref("")
	const newTemplateScope = ref("Personal")
	// The template the form is editing, or null when it's creating a new one.
	const editingTemplateName = ref(null)
	const creatingTemplate = ref(false)

	function openTemplatesDialog() {
		clearTimeout(templateSearchTimer)
		templatesView.value = "list"
		templateSearchQuery.value = ""
		showTemplatesDialog.value = true
	}

	// The search box keeps its own text; only the query the grid filters by is page state. Studio
	// re-evaluates every {{ }} on the page whenever any returned ref changes (the chat behind the
	// dialog included), so updating it on every keystroke made typing lag ~250ms. Pushing it
	// after a short pause keeps typing at native speed.
	let templateSearchTimer = null
	function onTemplateSearchInput(event) {
		const value = typeof event === "string" ? event : (event?.target?.value ?? "")
		clearTimeout(templateSearchTimer)
		templateSearchTimer = setTimeout(() => {
			templateSearchQuery.value = value
		}, 150)
	}

	function templateScopeLabel(scope) {
		return TEMPLATE_SCOPE_LABELS[scope] || scope
	}

	function templatesInScope(scope) {
		const templates = savedTemplates.value
		return scope === "All" ? templates : templates.filter((t) => (t.scope || "Personal") === scope)
	}

	// Each row carries its count on the right, like Helpdesk's filter ("Personal   2").
	function templateScopeFilterOptions() {
		return ["All", "Personal", "Team", "Global"].map((scope) => ({
			label: templateScopeLabel(scope),
			selected: templateScopeFilter.value === scope,
			onClick: () => {
				templateScopeFilter.value = scope
			},
			slots: {
				suffix: () => h("span", { class: "text-sm text-ink-gray-5" }, String(templatesInScope(scope).length)),
			},
		}))
	}

	function filteredMessageTemplates() {
		const query = templateSearchQuery.value.trim().toLowerCase()
		const templates = templatesInScope(templateScopeFilter.value)
		if (!query) return templates
		return templates.filter(
			(t) => (t.title || "").toLowerCase().includes(query) || (t.content || "").toLowerCase().includes(query),
		)
	}

	function templatesEmptyMessage() {
		if (templateSearchQuery.value.trim()) return "No templates match your search."
		if (templateScopeFilter.value === "All") return "No templates yet."
		return "No " + templateScopeLabel(templateScopeFilter.value).toLowerCase() + " templates yet."
	}

	// Global templates are side-wide, so they're created by an admin in Desk, not from here.
	function newTemplateScopeOptions() {
		return ["Personal", "Team"].map((scope) => ({
			label: templateScopeLabel(scope),
			value: scope,
			icon: TEMPLATE_SCOPE_ICONS[scope],
		}))
	}

	// Only the creator edits a template -- a teammate sees the team template but not the button,
	// and Global ones are managed in Desk. update_message_template enforces the same on the server.
	function canEditTemplate(template) {
		return !!template && template.scope !== "Global" && template.owner === me.value
	}

	function templateFormTitle() {
		return editingTemplateName.value ? "Edit Template" : "New Template"
	}

	function openEditTemplate(template, event) {
		// the card itself inserts the template into the composer on click
		event?.stopPropagation?.()
		if (!canEditTemplate(template)) return
		openNewTemplate()
		editingTemplateName.value = template.name
		newTemplateTitle.value = template.title || ""
		newTemplateContent.value = template.content || ""
		newTemplateScope.value = template.scope || "Personal"
		// the form's inputs keep their own text, so fill them once they've mounted
		nextTick(() => {
			setInputText(inputElement("templates-new-name-input", "input"), newTemplateTitle.value)
			setInputText(responseTextarea(), newTemplateContent.value)
		})
	}

	function openNewTemplate() {
		editingTemplateName.value = null
		clearTimeout(templateTitleTimer)
		clearTimeout(templateContentTimer)
		variableMenu.value = null
		variableMenuDismissedAt = -1
		newTemplateTitle.value = ""
		newTemplateContent.value = ""
		newTemplateScope.value = "Personal"
		templatesView.value = "new"
	}

	function backToTemplateList() {
		templatesView.value = "list"
	}

	// The Response box's example. Returned from a function because Studio would evaluate a
	// literal {{ first_name }} written straight into the placeholder prop.
	function templateResponsePlaceholder() {
		return "Hi {{ first_name }},\n\nThanks for getting in touch, we'll get back to you soon.\n\nRegards,\n{{ my_full_name }}"
	}

	// ---- {{ variable }} picker in the Response box ----
	// Typing "{{" anywhere in the text opens a list of these, like Helpdesk's saved replies. The
	// server fills them in when the template is used (TEMPLATE_VARIABLES in
	// connect_message_template.py, which must stay in step with this list).
	const TEMPLATE_VARIABLES = [
		{ key: "first_name", label: "Recipient first name" },
		{ key: "full_name", label: "Recipient full name" },
		{ key: "email", label: "Recipient email" },
		{ key: "company_name", label: "Recipient company" },
		{ key: "my_first_name", label: "Your first name" },
		{ key: "my_full_name", label: "Your full name" },
		{ key: "my_email", label: "Your email" },
		{ key: "my_company_name", label: "Your company" },
	]
	// Set only while the caret sits just after "{{partial" -- plain typing never touches it, so it
	// doesn't re-render the page (see "Text inputs that keep their own text").
	const variableMenu = ref(null)
	const variableMenuIndex = ref(0)
	const variableMenuPosition = ref({ top: 0, left: 0 })
	let variableMenuDismissedAt = -1
	let templateTitleTimer = null
	let templateContentTimer = null

	function responseTextarea() {
		return inputElement("templates-new-content-input") as HTMLTextAreaElement | null
	}

	function readVariableMatch(el) {
		const before = el.value.slice(0, el.selectionStart ?? 0)
		const match = /\{\{\s*(\w*)$/.exec(before)
		if (!match) return null
		const start = before.length - match[0].length
		return start === variableMenuDismissedAt ? null : { start, query: match[1].toLowerCase() }
	}

	function templateVariableSuggestions() {
		const match = variableMenu.value
		if (!match) return []
		return TEMPLATE_VARIABLES.filter(
			(v) => v.key.includes(match.query) || v.label.toLowerCase().includes(match.query),
		).map((v, index) => ({ ...v, active: index === variableMenuIndex.value }))
	}

	function isVariableMenuOpen() {
		return templateVariableSuggestions().length > 0
	}

	// Where the caret sits inside the textarea, measured with a hidden copy of it that wraps
	// text the same way (a textarea itself can't report caret coordinates).
	function caretCoordinates(el, position) {
		const style = getComputedStyle(el)
		const mirror = document.createElement("div")
		for (const prop of [
			"boxSizing", "width", "fontFamily", "fontSize", "fontWeight", "fontStyle", "letterSpacing",
			"lineHeight", "textTransform", "wordSpacing", "tabSize", "paddingTop", "paddingRight",
			"paddingBottom", "paddingLeft", "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
		]) {
			mirror.style[prop] = style[prop]
		}
		Object.assign(mirror.style, { position: "absolute", visibility: "hidden", top: "0", left: "-9999px", whiteSpace: "pre-wrap", overflowWrap: "break-word" })
		mirror.textContent = el.value.slice(0, position)
		const marker = document.createElement("span")
		marker.textContent = el.value.slice(position) || "."
		mirror.appendChild(marker)
		document.body.appendChild(mirror)
		const coords = { top: marker.offsetTop, left: marker.offsetLeft, lineHeight: parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.5 }
		mirror.remove()
		return coords
	}

	// Called on input/keyup/click in the Response box. Touches state only when the menu opens,
	// closes or its filter changes, and then moves it under the caret.
	function syncTemplateCaret() {
		const el = responseTextarea()
		if (!el) return
		const match = readVariableMatch(el)
		const current = variableMenu.value
		if (!match && !current) return
		if (match && current && match.start === current.start && match.query === current.query) return
		variableMenuIndex.value = 0
		if (match) {
			const wrap = el.closest('[data-component-id="templates-new-content-field"]')
			if (wrap) {
				const coords = caretCoordinates(el, el.selectionStart ?? 0)
				const elBox = el.getBoundingClientRect()
				const wrapBox = wrap.getBoundingClientRect()
				variableMenuPosition.value = {
					top: elBox.top - wrapBox.top + coords.top - el.scrollTop + coords.lineHeight + 4,
					left: Math.max(0, Math.min(elBox.left - wrapBox.left + coords.left, wrap.clientWidth - 260)),
				}
			}
		}
		variableMenu.value = match
	}

	function onTemplateTitleInput(event) {
		const value = event?.target?.value ?? ""
		clearTimeout(templateTitleTimer)
		templateTitleTimer = setTimeout(() => {
			newTemplateTitle.value = value
		}, 150)
	}

	function onResponseInput(event) {
		const value = event?.target?.value ?? ""
		syncTemplateCaret()
		clearTimeout(templateContentTimer)
		templateContentTimer = setTimeout(() => {
			newTemplateContent.value = value
		}, 150)
	}

	function onResponseKeydown(event) {
		if (!isVariableMenuOpen()) return
		const items = templateVariableSuggestions()
		if (event.key === "ArrowDown" || event.key === "ArrowUp") {
			event.preventDefault()
			const step = event.key === "ArrowDown" ? 1 : -1
			variableMenuIndex.value = (variableMenuIndex.value + step + items.length) % items.length
		} else if (event.key === "Enter" || event.key === "Tab") {
			event.preventDefault()
			insertTemplateVariable(items[variableMenuIndex.value] || items[0])
		} else if (event.key === "Escape") {
			// close just the menu -- without stopPropagation the dialog would close too
			event.preventDefault()
			event.stopPropagation()
			variableMenuDismissedAt = variableMenu.value?.start ?? -1
			variableMenu.value = null
		}
	}

	function insertTemplateVariable(variable) {
		const el = responseTextarea()
		const match = variableMenu.value
		if (!el || !match || !variable) return
		const inserted = "{{ " + variable.key + " }}"
		// swallow a "}}" the user already typed after the caret
		const after = el.value.slice(el.selectionStart ?? el.value.length).replace(/^\s*\}\}/, "")
		const caret = match.start + inserted.length
		variableMenu.value = null
		setInputText(el, el.value.slice(0, match.start) + inserted + after, caret)
		el.focus()
	}

	// The form as typed right now, not as of the last pause -- what Save sends.
	function currentTemplateForm() {
		clearTimeout(templateTitleTimer)
		clearTimeout(templateContentTimer)
		const title = inputElement("templates-new-name-input", "input")?.value ?? newTemplateTitle.value
		const content = responseTextarea()?.value ?? newTemplateContent.value
		newTemplateTitle.value = title
		newTemplateContent.value = content
		return { title: title.trim(), content: content.trim() }
	}

	async function saveNewTemplate() {
		const { title, content } = currentTemplateForm()
		if (!title || !content || creatingTemplate.value) return
		creatingTemplate.value = true
		try {
			const editing = editingTemplateName.value
			if (editing) {
				await call("connect.api.message_templates.update_message_template", {
					name: editing,
					title,
					content,
					scope: newTemplateScope.value,
				})
			} else {
				await call("connect.api.message_templates.create_message_template", {
					title,
					content,
					scope: newTemplateScope.value,
				})
			}
			editingTemplateName.value = null
			await loadTemplates()
			// land on the filter the new template lives under, so it's visible straight away
			templateScopeFilter.value = newTemplateScope.value
			templateSearchQuery.value = ""
			templatesView.value = "list"
			toast.success(editing ? "Template updated" : "Template created")
		} catch (e) {
			toast.error(editingTemplateName.value ? "Could not update template" : "Could not create template", { description: e.messages ? e.messages[0] : e.message })
		} finally {
			creatingTemplate.value = false
		}
	}

	return {
		showTemplatesDialog,
		openTemplatesDialog,
		insertTemplate,
		templatesView,
		templateScopeFilter,
		templateScopeLabel,
		templateScopeFilterOptions,
		filteredMessageTemplates,
		templatesEmptyMessage,
		onTemplateSearchInput,
		canEditTemplate,
		openEditTemplate,
		openNewTemplate,
		backToTemplateList,
		templateFormTitle,
		newTemplateTitle,
		newTemplateContent,
		newTemplateScope,
		newTemplateScopeOptions,
		templateResponsePlaceholder,
		creatingTemplate,
		saveNewTemplate,
		onTemplateTitleInput,
		onResponseInput,
		onResponseKeydown,
		syncTemplateCaret,
		isVariableMenuOpen,
		templateVariableSuggestions,
		variableMenuPosition,
		insertTemplateVariable,
	}
}
