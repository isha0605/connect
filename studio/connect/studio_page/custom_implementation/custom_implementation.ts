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

	// ---- Hire: agree to the terms, then say why this partner (or skip) ----
	const hireOpen = ref(false)
	const hireStep = ref("terms")
	const hireAgreed = ref(false)
	const hireRow = ref(null)
	const hiring = ref(false)
	const hireName = computed(() => hireRow.value?.partner_name || "this partner")
	const hireTitle = computed(() => (hireStep.value === "terms" ? `Hire ${hireName.value}` : `Why ${hireName.value}?`))
	const hireTerms = computed(() => [
		{ title: `Pay ${hireName.value} directly`, text: "Frappe takes no fee and is not a party to the agreement." },
		{ title: "Scope, price and timeline are as quoted", text: `Changes are agreed between you and ${hireName.value}.` },
		{ title: "Hosting is billed through your partner", text: `Frappe Cloud bills ${hireName.value}, who bills you.` },
		{ title: "Your site stays private", text: "Frappe can see that this project exists, not what is in your site." },
	])
	const hireReasons = ["Price", "Timeline", "Their profile", "How they replied"]

	function hirePartner(row) {
		hireRow.value = row
		hireAgreed.value = false
		hireStep.value = "terms"
		hireOpen.value = true
	}

	function confirmHire() {
		if (!hireAgreed.value || hiring.value || !hireRow.value) return
		hiring.value = true
		call("connect.api.projects.hire_partner", { quote: hireRow.value.name })
			.then((data) => {
				project.value = data
				hireStep.value = "why"
				toast.success(`${hireName.value} is your partner`)
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't hire this partner. Try again."))
			.finally(() => {
				hiring.value = false
			})
	}

	// Skip sends no reason; either way the dialog closes on step 2.
	function giveHireReason(reason) {
		hireOpen.value = false
		if (!reason || !project.value) return
		call("connect.api.projects.set_hire_reason", { name: project.value.name, reason }).catch(() => {})
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
	// Shared, Hired and Completed are all past the draft: the brief has gone out.
	const isDraft = computed(() => !["Shared", "Hired", "Completed"].includes(project.value?.status))
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
	const isShared = computed(() => !isDraft.value)

	// ---- After hiring: setting up hosting, step 2 of 2 ----
	const hired = computed(() => project.value?.hired || null)
	const isHired = computed(() => !!hired.value)
	const stageTitle = computed(() => (isHired.value ? "Set up hosting" : "Choosing a partner"))
	const stageStep = computed(() => (isHired.value ? "Step 2 of 2" : "Step 1 of 2"))

	const HOSTING_TASKS = [
		{
			key: "fc-login",
			label: "Log in to Frappe Cloud",
			hint: "Your site is hosted on Frappe Cloud. Create an account if you do not have one.",
			cta: "Log in",
			url: "https://frappecloud.com/dashboard",
		},
		{
			key: "fc-code",
			label: "Copy your partner’s referral code",
			hint: "You enter it on Frappe Cloud in the next task.",
			copy: true,
		},
		{
			key: "fc-link",
			label: "Link your Frappe Cloud account to your partner",
			hint: "Your partner then manages your hosting and bills you for it.",
			cta: "Link",
			url: "https://frappecloud.com/dashboard/settings/partner",
		},
	]
	const hostingTasks = computed(() => {
		const done = project.value?.done_tasks || []
		return HOSTING_TASKS.map((task) => ({ ...task, done: done.includes(task.key) }))
	})

	function completeTask(task) {
		call("connect.api.projects.complete_task", { name: projectName, task: task.key })
			.then((data) => {
				project.value = data
			})
			.catch(() => {})
	}

	function actOnTask(task) {
		if (task.copy) return copyReferralCode(task)
		window.open(task.url, "_blank", "noopener")
		completeTask(task)
	}

	function copyReferralCode(task) {
		const code = hired.value?.referral_code
		if (!code) return
		navigator.clipboard
			.writeText(code)
			.then(() => toast.success("Referral code copied", { description: code }))
			.catch(() =>
				toast.info(`Your referral code is ${code}`, {
					description: "Your browser blocked the clipboard. Copy it from here.",
				}),
			)
		completeTask(task)
	}

	const isCompleted = computed(() => project.value?.status === "Completed")
	const completing = ref(false)
	function markComplete() {
		if (completing.value) return
		completing.value = true
		call("connect.api.projects.complete_project", { name: projectName })
			.then((data) => {
				project.value = data
				toast.success("Project completed")
			})
			.catch((error) => toast.error(error?.messages?.[0] || "Couldn't complete the project. Try again."))
			.finally(() => {
				completing.value = false
			})
	}

	// The Partner panel: who was hired, and on what quote.
	const hiredCost = computed(() => (hired.value ? quoteAmount(hired.value) : ""))
	function messagePartner() {
		if (hired.value?.thread) router.push({ path: "/messaging", query: { thread: hired.value.thread } })
	}
	function viewPartnerProfile() {
		if (hired.value) router.push(`/partner-profile-redesign/${encodeURIComponent(hired.value.partner)}`)
	}
	const sentLine = computed(() => {
		const n = project.value?.shared_count || 0
		return `Sent to ${n} partner${n === 1 ? "" : "s"}. Quotes arrive in Messages, usually within a few working days.`
	})
	// Once hired, the timeline is the partner's quoted one.
	const timelineLabel = computed(() =>
		hired.value?.timeline_weeks ? quoteTimeline(hired.value) : goLiveCriterion(project.value?.go_live),
	)
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
		hireOpen,
		hireRow,
		hireStep,
		hireAgreed,
		hiring,
		hireTitle,
		hireTerms,
		hireReasons,
		confirmHire,
		giveHireReason,
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
		hired,
		isHired,
		stageTitle,
		stageStep,
		hostingTasks,
		actOnTask,
		isCompleted,
		completing,
		markComplete,
		hiredCost,
		messagePartner,
		viewPartnerProfile,
		sentLine,
		timelineLabel,
		createdOn,
		openFeedback,
		requirementsOpen,
		viewRequirements,
		requirements,
	}
}
