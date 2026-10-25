# Connect project guidance

This file records the working guidance shared for this repository. Some examples below come from Frappe Central. Treat Central-specific architecture and names as examples, and apply them to Connect only where Connect has the corresponding feature or pattern. Prefer Connect's existing implementation and established conventions when they differ.

## Core principles

- Keep changes small, direct, and in the module that owns the behavior.
- Before a substantial implementation, explain the proposed design, assumptions, ownership, state, dependencies, error flow, risks, and important trade-offs. Use a small ASCII diagram when it helps, and proceed after the user agrees.
- Build the minimum working change, then iterate. Simplify existing code where that fully addresses the need.
- For a bug fix, find the root cause before changing code.
- Do not change unrelated dirty files, generated artifacts, or local data.
- Do not add plan files such as `plan_*.md`. Track planned work in GitHub issues.
- Do not commit secrets, private keys, tokens, `.env` content, or production credentials.
- Use `git mv` when intentionally moving or renaming a tracked file.

## Compatibility

- Preserve existing behavior unless the task or specification requires a change.
- Add a data patch for a change to stored data. Do not leave old data behind a new schema.
- Do not add compatibility layers, deprecated aliases, or fallback behavior unless required.
- Do not design for rolling upgrades, mixed-version deployments, or zero-downtime migration unless required.

## Permissions and data access

Treat every permission change as security-sensitive.

- Resolve authorization through Connect's existing permission and capability patterns. Do not introduce a parallel permission model.
- Scope reads and writes to the relevant user, team, or owning entity as required by the feature.
- Enforce access at the data-access layer as well as in user-facing API routes when the framework and feature require both.
- Prefer permission-aware APIs for reads on behalf of a user. Use permission-bypassing APIs only on system paths, and keep explicit scope filters there.
- Do not use `ignore_permissions=True` as a substitute for correct permission design. If a system path must bypass permissions, add a brief comment that explains why.
- Add focused tests for permission rules, including denial and cross-entity cases where applicable.

The detailed team/capability rules from Central apply only if Connect implements the same authorization model. In that case, use Connect's corresponding helpers and fixtures rather than copying Central paths or names.

## Desk and operations

Build DocTypes and operator-facing workflows so that an operator can read, find, and act on records from the Desk where applicable.

### Make lists usable

- Mark useful identity, ownership, state, and health fields for list display.
- Mark common filter fields as standard filters.
- Index fields that lists filter or sort on using the repository's established migration or DocType lifecycle pattern.
- Set meaningful title and search fields so operators can find records by recognizable names.
- Give state fields an indicator colour where supported.

### Make forms readable

- Group fields into tabs and sections that follow the operator's task.
- Put identity and state near the top. Put credentials, raw payloads, and debug fields in a collapsed section or separate tab.
- Use labels that explain fields to people. Add a description when a field's meaning is not obvious.
- Mark system-written fields read-only.

### Make records navigable and actionable

- Add dashboard connections to related records an operator is likely to inspect next.
- Use Link fields for related records instead of plain text identifiers where appropriate.
- Add Desk actions for manual operations when they are part of the product workflow.
- Show actions only when valid for the record state and current user, and confirm destructive actions.
- Keep action behavior in the server-side method that owns it; the button should trigger that method.
- Surface failures where the operator is working, not only in logs.

## Code style

### All code

- Choose clear code over clever code. Prefer explicit configuration over implicit behavior.
- Use complete words for names. Avoid abbreviations.
- Put behavior with the module, domain object, or DocType controller that owns it.
- Use standard Frappe APIs and existing repository helpers before adding custom logic or dependencies.
- Keep functions small. About 25 lines is a useful target, not a reason to split readable code.
- Put blank lines between logical code blocks in a function.
- Add a one- or two-line comment only when the purpose needs explanation. Explain why, not how.
- Keep cyclomatic complexity at 8 or less. Keep files between 100 and 500 lines when practical.
- Extend an existing folder before adding a new one. Do not add generic `utils`, `helpers`, `common`, or `misc` folders.
- Keep one owner for state that can drift. Keep temporary state inside the object or module that owns its lifecycle.
- Fail near the cause. Do not hide corrupt or partial state behind a broad fallback. Retry only operations that are safe to repeat.
- Do not add comments that repeat the code. Explain a business rule, invariant, external quirk, or concurrency rule only when the code cannot show it.
- Do not put explanatory comments at the top of a file. Use a short class or function docstring.
- Add focused tests for changed behavior and failure cases. Keep tests deterministic and independent.
- Follow DRY, SOLID, and KISS to remove real duplication and coupling, not to add layers.
- Reduce the layers a reader must trace and the state they must hold in their head.
- Abstract only when it represents a distinct concept with a consistent interface.
- Review each test for necessity. Avoid tests that only raise coverage when type checking or an existing integration test already verifies the behavior.

### Python

- Keep domain behavior in the DocType controller, service module, or task that owns it. Keep API routes and `hooks.py` entries thin.
- Do not add a second API for a variant of an existing operation. Extend the existing API when that is the established design.
- Use type hints for public functions and important data structures.
- Raise specific exceptions. Handle only errors the code can recover from. Use the repository's established user-facing error patterns.
- Prefer standard Frappe APIs and built-in DocTypes. Use `frappe.db` and `frappe.qb` instead of raw SQL.
- Wrap every user-facing string in `_()`.
- Avoid mutable global state, circular imports, and lazy re-exports in a package `__init__.py`.
- Use `@property` only for a cheap, side-effect-free, no-argument operation that returns one noun-like value. Use `get_<what_it_returns>()` for operations with arguments or multi-step work.
- Name boolean properties and methods with `is_` or `has_`.
- Keep a method public when a caller outside its owner uses it. Use a leading underscore for raw parsing, security-sensitive validation, or genuinely internal details.
- Use binary units and name a field for its unit, such as `disk_mib`.
- Do not use `ignore_permissions=True` as a substitute for correct permission design. For a necessary system bypass, add a comment that states why.
- Use `frappe.qb` with a join when a read spans more than two tables. Do not loop a query per row; avoid N+1 queries.
- Add indexes and unique constraints using the repository's established DocType lifecycle pattern.

#### Prefer controller lifecycle hooks over API wiring

Read the [Frappe controller documentation](https://docs.frappe.io/framework/user/en/basics/doctypes/controllers) before adding behavior that reacts to a document reaching a state. When a document follows a lifecycle, put each step in the controller hook that owns that point in the lifecycle, rather than sequencing calls manually in an API route or integration function.

Common hooks, in call order:

| Hook | Runs | Use it for |
| --- | --- | --- |
| `before_validate` | Before `validate`, on every save | Normalize input before it is checked |
| `validate` | Before every save | Enforce invariants; block the save on failure |
| `before_insert` | Once, before the first save | Set a field a fresh document alone needs |
| `after_insert` | Once, right after the first save | Start work triggered only by a new document |
| `on_update` | After every save | React to any change, not only creation |
| `on_trash` | Before delete | Clean up what the document owns |

A route should stay a thin trigger: build the document and call `insert()` or `save()`. The controller hooks should own lifecycle behavior so every creation path gets the same behavior.

### Dashboard

Use the dashboard's existing Vue, TypeScript, Frappe UI, and design-system conventions. The Espresso-specific requirements below apply only if Connect uses that design system.

- Organize components by domain and use the existing component tiers and patterns.
- Extract repeated table actions, dialogs, empty states, and mutation behavior into shared components when doing so creates a clear reusable concept.
- Keep pages thin. A page composes components and reads composables; it does not own data fetching or domain logic.
- Put data fetching in composables and keep shared types in the established types folder. Avoid `any`.
- Give components typed props with a named props interface.
- Handle loading, empty, error, and disabled states.
- Use the established toast and persistent error-reporting patterns for success and failure.
- Keep form and dialog failures inside the form or dialog. Put field validation messages below their fields. Keep page or list loading failures in the content area.
- Use the project's UI components and semantic classes for layout, spacing, color, and typography. Avoid mixing ad hoc utility values with design-system tokens.
- Keep line heights and text sizes on the design-system scale.
- Use correct HTML semantics. Give every control a label, reachable focus state, and keyboard operation.

## Commits and pull requests

### Commits

- Use a short Conventional Commit subject: `type(scope): lower case`.
- Use one of `feat`, `fix`, `refactor`, `test`, `docs`, `build`, or `chore` as the type.
- Use a kebab-case scope.
- Start the subject after the colon in lower case. Capitalize only a proper noun, such as Atlas or MariaDB.
- Do not end the subject with a period.
- Do not add an AI co-author, session data, or agent data.

### Pull requests

- Use the same Conventional Commit format for the pull request title.
- Keep the description short and use Simplified Technical English.
- State what changed and why it matters. Do not narrate the implementation.
- Group related changes. Include visual evidence only for visual changes.
- Avoid words like “doors”, “seam”, and “rule”.
- Follow validation and handover requirements before writing the description.

For a bug fix, use:

```markdown
## Issue
<One sentence that states the user-visible or operational problem.>

## Summary
<1 or 2 sentences that state the fix and why it matters.>

## What changed
- <Specific change>

## Why
<The technical or business reason for this approach.>

## Screenshots
<Before and after evidence. Omit this section when it does not apply.>

## Related issues
Closes #<issue>
```

For a feature, use:

```markdown
## Summary
<1 or 2 sentences that state the capability and why it matters.>

## What changed
- <Specific change>

## Why
<The technical or business reason for this approach.>

## Screenshots
<Before and after evidence. Omit this section when it does not apply.>

## Related issues
Refs #<issue>
```

## Agent tooling and continuity

- Use the most specific available skill for the task.
- Use `code-style` for every code edit and code-style question.
- Use `quality-code-review` for Frappe correctness, security, performance, concurrency, readability, API design, and test reviews.
- Use `review-like-ankush` for review of a Frappe diff or pull request.
- Use `technical-writing` for documentation, READMEs, commits, pull requests, and release notes.
- Use `ui-design` for dashboard layout, polish, hierarchy, spacing, typography, color, and accessibility.
- Use `grill-me` for strict review of a plan or design before handover.
- Use `diagnose` for a hard bug or performance regression.
- Use `draft-security-advisory` for a security advisory for a fixed vulnerability.
- Use `i-have-adhd` for focused, action-first output when requested.
- Treat this file as the primary repository guidance for each task.
- After context compaction, summarization, restart, or loss of working context, read this file again before continuing.
- Preserve a reference to `CLAUDE.md` in any handover or context summary so the next context reloads it.
