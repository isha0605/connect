// "We recommend a custom implementation": where a draft project lands when its answers
// rule a Starter Pack out (see recommend() in @app/utils/recommendation). Opened as
// /custom-implementation?project=CP-…; the project is a Customer Project.
//
// The partner count is live (count_matching_partners). "Share requirements" keeps the
// budget and brief on the project — nothing messages partners yet, and the page says so.

import { computed, ref } from "vue"
import {
	BUDGET_OPTIONS,
	CUSTOM_HOW_IT_WORKS,
	OPERATION_OPTIONS,
	PROBLEM_OPTIONS,
	STARTER_PACK_IF,
	answersFromProject,
	goLiveCriterion,
	recommend,
} from "@app/utils/recommendation"
import { projectDialog, projectPath } from "@app/utils/projectDialog"
import { blankCriteria, criteriaSummary, orList, partnerCriteria, workCriterion } from "@app/utils/partnerCriteria"
import { installScrollFade } from "@app/utils/scrollFade"

export default function setup(context) {
	const { route, router, call, toast } = context
	installScrollFade()

	// Same test Studio's own isEditor() uses. The editor opens pages with no query string,
	// so there the page shows the newest custom-implementation project instead, and lets
	// itself grow to its full height (see `inEditor` in the blocks) so the canvas shows it all.
	const inEditor = window.location.pathname.startsWith("/studio/")

	let projectName = String(route.query.project || "")
	const project = ref(null)
	const loadError = ref(false)
	const matchCount = ref(null)
	const budget = ref("")
	const description = ref("")
	const sharing = ref(false)

	function loadProject(name) {
		projectName = name
		call("connect.api.projects.get_project", { name })
			.then((data) => {
				project.value = data
				budget.value = data.budget || ""
				description.value = data.description || ""
				refreshMatchCount(data.criteria)
				if (data.status === "Shared") loadQuotes()
			})
			.catch(() => {
				loadError.value = true
			})
	}

	// ---- Quotes: partners' replies to the shared brief ----
	// Others are replies not decided on yet; Interested is the shortlist. Not interested
	// drops a partner from both, with an Undo.
	const quotes = ref([])
	const quoteTab = ref("interested")
	function loadQuotes() {
		if (!projectName) return
		call("connect.api.projects.list_quotes", { name: projectName })
			.then((rows) => {
				quotes.value = rows || []
			})
			.catch(() => {})
	}
	const interestedQuotes = computed(() => quotes.value.filter((q) => q.status === "Interested"))
	const otherQuotes = computed(() => quotes.value.filter((q) => q.status === "Quoted"))
	const hasQuotes = computed(() => quotes.value.length > 0)
	const quoteTabs = computed(() => [
		{ label: `Interested ${interestedQuotes.value.length}`, value: "interested" },
		{ label: `Others ${otherQuotes.value.length}`, value: "others" },
	])
	const shownQuotes = computed(() => (quoteTab.value === "interested" ? interestedQuotes.value : otherQuotes.value))
	const showInterestedEmpty = computed(
		() => hasQuotes.value && quoteTab.value === "interested" && !interestedQuotes.value.length,
	)

	function quoteAmount(row) {
		return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(
			row?.amount || 0,
		)
	}
	function quoteTimeline(row) {
		const weeks = row?.timeline_weeks || 0
		return `${weeks} week${weeks === 1 ? "" : "s"}`
	}

	function setQuoteStatus(row, status) {
		const before = row.status
		row.status = status
		return call("connect.api.projects.set_quote_status", { quote: row.name, status })
			.then((counts) => {
				if (project.value) project.value = { ...project.value, ...counts }
			})
			.catch((error) => {
				row.status = before
				toast.error(error?.messages?.[0] || "Couldn't update that quote. Try again.")
				throw error
			})
	}

	function markInterested(row) {
		setQuoteStatus(row, "Interested").catch(() => {})
	}

	function notInterested(row) {
		const before = row.status
		setQuoteStatus(row, "Not Interested")
			.then(() => {
				toast(`${row.partner_name} removed`, {
					action: { label: "Undo", onClick: () => setQuoteStatus(row, before).catch(() => {}) },
				})
			})
			.catch(() => {})
	}

	function readThread(row) {
		router.push({ path: "/messaging", query: { thread: row.thread } })
	}

	function hirePartner() {
		toast.info("Hiring is coming soon.")
	}

	function quoteMenu(row) {
		return [
			{ label: "Not interested", icon: "lucide-ban", onClick: () => notInterested(row) },
			{ label: "Read the thread", icon: "lucide-message-square", onClick: () => readThread(row) },
		]
	}

	// Demo only: partners can't send quotes yet, so this makes every partner the brief went
	// to reply with one (connect.api.projects.simulate_quotes).
	const simulating = ref(false)
	function simulateQuotes() {
		if (simulating.value || !projectName) return
		simulating.value = true
		call("connect.api.projects.simulate_quotes", { name: projectName })
			.then((result) => {
				if (project.value) project.value = { ...project.value, quotes: result.quotes, shortlisted: result.shortlisted }
				toast.success(
					result.sent
						? `${result.sent} partner${result.sent === 1 ? "" : "s"} replied with a quote.`
						: "Every partner has already quoted.",
				)
				loadQuotes()
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't get quotes. Try again."))
			.finally(() => {
				simulating.value = false
			})
	}

	if (projectName) {
		loadProject(projectName)
	} else if (inEditor) {
		call("connect.api.projects.list_projects")
			.then((rows) => {
				const drafts = (rows || []).filter((row) => row.kind === "project")
				const first = drafts.find((row) => row.verdict === "custom") || drafts[0]
				if (first) loadProject(first.project)
				else loadError.value = true
			})
			.catch(() => {
				loadError.value = true
			})
	} else {
		loadError.value = true
	}


	const projectTitle = computed(() => project.value?.project_name || "Project")
	const isDraft = computed(() => project.value?.status !== "Shared")
	const breadcrumbItems = computed(() => [
		{ label: "Projects", route: { path: "/projects" } },
		{ label: projectTitle.value },
	])

	const whyReasons = computed(() => {
		if (!project.value) return []
		const result = recommend(answersFromProject(project.value))
		return result.verdict === "custom" ? result.reasons : []
	})

	// ---- Partner criteria: who the brief goes to (see @app/utils/partnerCriteria) ----
	const savedCriteria = computed(() => ({ ...blankCriteria(), ...(project.value?.criteria || {}) }))
	const criteria = computed(() => criteriaSummary(savedCriteria.value, project.value?.go_live))

	function refreshMatchCount(saved) {
		call("connect.api.projects.partner_criteria", { criteria: JSON.stringify(saved || {}) })
			.then((data) => {
				matchCount.value = data.total
			})
			.catch(() => {})
	}

	const criteriaOpen = ref(false)
	const chips = partnerCriteria(context, {
		saved: () => savedCriteria.value,
		goLive: () => project.value?.go_live,
	})

	function editCriteria() {
		chips.startEditing()
		criteriaOpen.value = true
	}

	const savingCriteria = ref(false)
	function saveCriteria() {
		if (savingCriteria.value || !project.value) return
		savingCriteria.value = true
		call("connect.api.projects.save_criteria", {
			name: project.value.name,
			criteria: JSON.stringify(chips.draftFilters()),
			go_live: chips.criteriaDraft.value.go_live,
		})
			.then((data) => {
				project.value = data
				matchCount.value = chips.criteriaFacets.value.total
				criteriaOpen.value = false
			})
			.catch(() => toast.error("Couldn't save your criteria. Try again."))
			.finally(() => {
				savingCriteria.value = false
			})
	}

	const matchCountLabel = computed(() => (matchCount.value === null ? "–" : String(matchCount.value)))
	const matchCaption = computed(() =>
		matchCount.value === 1 ? "partner matches your criteria" : "partners match your criteria",
	)

	function shareRequirements() {
		if (sharing.value || !project.value) return
		sharing.value = true
		call("connect.api.projects.share_requirements", {
			name: project.value.name,
			budget: budget.value,
			description: description.value,
		})
			.then((data) => {
				project.value = data
				const n = data.shared_count || 0
				toast.success(`Sent to ${n} partner${n === 1 ? "" : "s"}. Their quotes arrive in Messages and on this page.`)
			})
			.catch((error) => {
				toast.error(error?.messages?.[0] || "Couldn't send your requirements. Try again.")
			})
			.finally(() => {
				sharing.value = false
			})
	}

	// "Change my answers" edits the draft right here. If the new answers still point to a
	// custom implementation the page just reloads the project; otherwise it moves to the
	// Starter Pack page the answers now recommend.
	const dialog = projectDialog(context, {
		onSaved: (saved) => {
			if (saved.verdict === "custom") {
				project.value = saved
				projectName = saved.name
				return
			}
			router.push(projectPath({ kind: "project", project: saved.name, verdict: saved.verdict }))
		},
	})

	function changeAnswers() {
		if (project.value) dialog.editProject(project.value)
	}

	function viewAllPartners() {
		router.push("/partner-directory-redesign")
	}

	function lookAtPacks() {
		router.push({ path: "/starter-pack-recommendation", query: { project: projectName } })
	}

	// Delete asks first: it removes the project and every answer on it.
	const deleteOpen = ref(false)
	const deleting = ref(false)

	function confirmDelete() {
		if (deleting.value) return
		deleting.value = true
		call("connect.api.projects.delete_project", { name: projectName })
			.then(() => router.push("/projects"))
			.catch(() => toast.error("Couldn't delete the draft."))
			.finally(() => {
				deleting.value = false
			})
	}

	const projectMenu = [
		{ label: "Edit draft", icon: "lucide-pencil", onClick: changeAnswers },
		{ label: "Delete draft", icon: "lucide-trash-2", onClick: () => (deleteOpen.value = true) },
	]

	// ---- After "Share requirements": choosing a partner, step 1 of 2 ----
	const isShared = computed(() => project.value?.status === "Shared")
	const sentLine = computed(() => {
		const n = project.value?.shared_count || 0
		return `Sent to ${n} partner${n === 1 ? "" : "s"}. Quotes arrive in Messages, usually within a few working days.`
	})
	const timelineLabel = computed(() => goLiveCriterion(project.value?.go_live))
	const createdOn = computed(() => {
		const at = project.value?.created_on
		return at ? new Date(at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : ""
	})

	function openFeedback() {
		toast.info("Feedback form is coming soon.")
	}

	// ---- View requirements: everything the brief says, read back ----
	const requirementsOpen = ref(false)
	function viewRequirements() {
		requirementsOpen.value = true
	}

	const labelIn = (options, value) => options.find((o) => o.value === value)?.label || ""
	function andList(values) {
		if (values.length <= 1) return values.join("")
		return `${values.slice(0, -1).join(", ")} and ${values[values.length - 1]}`
	}

	const requirements = computed(() => {
		const p = project.value || {}
		const c = savedCriteria.value
		const place = c.cities.length ? c.cities : c.countries
		const where = place.length ? `in ${orList(place)}` : "in any region"
		const tier = c.tiers.length ? `a ${orList(c.tiers)} tier partner` : "a partner of any tier"
		const work = { "On premises": "on premises", Remote: "remotely" }[workCriterion(c.work)] || "remotely or on premises"
		return {
			budget: p.budget || "No budget given",
			goLive: goLiveCriterion(p.go_live),
			description: p.description || "",
			operations: labelIn(OPERATION_OPTIONS, p.operations),
			systems: (p.systems || []).length ? `You use ${andList(p.systems)}` : "",
			problems: (p.problems || []).map((v) => labelIn(PROBLEM_OPTIONS, v)).filter(Boolean),
			lookingFor: `${tier[0].toUpperCase()}${tier.slice(1)} based ${where}, who works ${work}.`,
		}
	})

	return {
		quotes,
		quoteTab,
		quoteTabs,
		hasQuotes,
		shownQuotes,
		showInterestedEmpty,
		quoteAmount,
		quoteTimeline,
		markInterested,
		readThread,
		hirePartner,
		quoteMenu,
		simulating,
		simulateQuotes,
		...dialog,
		inEditor,
		project,
		loadError,
		projectTitle,
		isDraft,
		breadcrumbItems,
		whyReasons,
		criteria,
		matchCountLabel,
		matchCaption,
		budget,
		description,
		sharing,
		budgetOptions: BUDGET_OPTIONS,
		customHowItWorks: CUSTOM_HOW_IT_WORKS,
		starterPackIf: STARTER_PACK_IF,
		shareRequirements,
		editCriteria,
		criteriaOpen,
		cityChips: chips.cityChips,
		tierChips: chips.tierChips,
		workChips: chips.workChips,
		goLiveChips: chips.goLiveChips,
		partnersLeft: chips.partnersLeft,
		toggleCriterion: chips.toggleCriterion,
		setGoLive: chips.setGoLive,
		clearCriteria: chips.clearCriteria,
		saveCriteria,
		savingCriteria,
		changeAnswers,
		lookAtPacks,
		viewAllPartners,
		projectMenu,
		deleteOpen,
		deleting,
		confirmDelete,
		isShared,
		sentLine,
		timelineLabel,
		createdOn,
		openFeedback,
		requirementsOpen,
		viewRequirements,
		requirements,
	}
}
