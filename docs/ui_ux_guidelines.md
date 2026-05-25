# Project UI / UX Design Guidelines for Codex

## Core Principle

This product is not allowed to ship UI that is merely beautiful.

Every new feature, page, component, or interface modification must reduce user thinking cost. The interface must help users understand:

1. Where am I?
2. What is this page for?
3. What is the current system status?
4. What can I do here?
5. What should I do first?
6. What will happen after I click?
7. Which information comes from source evidence, AI inference, user confirmation, or conflict detection?

If a UI looks visually polished but does not answer these questions, it is considered incomplete.

## Product Context

This product is a ProjectWiki / AI project memory system.

It helps users connect project sources such as GitHub, Gitea, GitLab, local repositories, documents, code, issues, and notes, then transforms them into a maintainable, evidence-based project knowledge system.

The product should help users:

- Connect project data sources.
- Scan code and documents.
- Generate a project wiki.
- View project facts.
- Ask questions about the project.
- Trace every important answer back to evidence.
- Detect conflicts between code, documents, and AI-generated understanding.
- Confirm, correct, or reject AI-inferred facts.
- Generate handover packages for new team members.

The UI must always make the project state, evidence state, AI state, and user action path clear.

## Mandatory UX Review Before UI Changes

Before implementing any UI change, adding a feature, or modifying a page, first perform a short UX review.

Do not start coding until the following are clear:

### 1. User Goal

Identify the user's main goal on this page or component.

Examples:

- Connect a repository.
- Start a scan.
- View generated wiki.
- Check evidence.
- Resolve conflicts.
- Confirm an AI-inferred fact.
- Ask a question.
- Generate handover material.

### 2. Primary Action

Every main page should have one clearly dominant primary action.

Good examples:

- Connect Git Repository
- Start Project Scan
- Generate Project Wiki
- Review Conflicts
- Confirm This Fact
- View Evidence
- Generate Handover Package

Avoid vague labels:

- Submit
- Confirm
- Process
- Execute
- Continue
- OK

Button text must describe the result of the action.

### 3. Current Status

The page must clearly show what state the system is in.

Common states include:

- Not connected
- Connected
- Waiting for scan
- Scanning
- Syncing
- Generating
- Generated
- Needs review
- Has conflicts
- Evidence available
- Low confidence
- Failed
- No permission
- No result
- Empty

If the system is doing background work, the user must know what is happening.

### 4. Next Step

The user should never need to guess what to do next.

Every page, empty state, error state, success state, and long-running operation should provide a recommended next step.

## Visual Hierarchy Rules

When designing or modifying UI, always establish clear visual hierarchy.

### Required hierarchy

1. Page title and purpose.
2. Current project or object.
3. Current status.
4. Primary action.
5. Key information.
6. Secondary actions.
7. Advanced or technical details.

Do not give every card, title, button, and badge the same visual weight.

Use size, spacing, grouping, contrast, placement, and component priority to guide user attention.

The user should know within 5 seconds:

- What page they are on.
- What the most important information is.
- What they should do next.

## Interaction State Rules

Every interactive feature must consider the following states:

1. Default
2. Hover
3. Focus
4. Active
5. Disabled
6. Loading
7. Success
8. Error
9. Empty
10. No permission
11. No result

For long-running AI or repository tasks, also include:

- Scanning
- Syncing
- Indexing
- Generating
- Waiting for confirmation
- Conflict detected
- Partially completed
- Retry available

Do not implement only the ideal "normal" state.

Real product UX depends heavily on edge states.

## Empty State Rules

Do not use "No data" or "暂无数据" as the only empty state.

Every empty state must explain:

1. What is missing.
2. Why it matters.
3. What the user can do next.
4. Which button starts the recommended action.

Good empty state examples:

### No Project

Title: Create your first project memory

Description: Connect a repository or document source so ProjectWiki can scan your project and build an evidence-based wiki.

Primary action: Connect Repository

Secondary action: Try Demo Project

### No Wiki

Title: No wiki has been generated yet

Description: Start a project scan to let the system extract modules, documents, APIs, decisions, and project facts.

Primary action: Start Project Scan

### No Conflicts

Title: No conflicts found

Description: Current documents, code, and confirmed facts are consistent based on the latest scan.

Primary action: View Project Facts

### No Evidence

Title: No evidence attached yet

Description: This fact may be AI-inferred or not yet linked to source files. Review it before relying on it.

Primary action: Review Fact

## Discoverability Rules

Users must be able to tell what is clickable, expandable, editable, confirmable, or inspectable.

Use visible affordances such as:

- Clear button styles.
- Hover states.
- Focus rings.
- Disclosure arrows.
- View evidence links.
- Expand details controls.
- Tooltips for icon-only actions.
- Inline labels for important icons.
- Cursor and interaction feedback.

Avoid UI where:

- Decorative elements look clickable.
- Clickable elements look decorative.
- Important actions are hidden behind unlabeled icons.
- Users must guess whether a card can be opened.

## Progressive Disclosure Rules

Do not expose all complexity at once.

Default views should show what the user needs to complete the main task.

Advanced information should be collapsed or moved into secondary views.

Examples of information that should often be progressively disclosed:

- Raw scan logs.
- Full file paths.
- Embedding or indexing details.
- Internal IDs.
- Advanced sync configuration.
- Debug metadata.
- Full evidence chains.
- Low-level AST or parser output.
- Advanced permission settings.

Recommended user path:

1. Create or choose project.
2. Connect data source.
3. Start scan.
4. Generate wiki.
5. Review project facts.
6. Inspect evidence.
7. Resolve conflicts.
8. Ask questions.
9. Generate handover package.

The UI should guide users through this path, especially during first-time use.

## Visual Language System

The product must have a consistent visual language for information source, confidence, status, and user action.

### Information Source

Use consistent badges, icons, labels, and tooltips for:

- Git source
- Document source
- Issue source
- AI inference
- User confirmed
- System generated
- Manually edited

Users must be able to distinguish source-backed information from AI-inferred information.

### Evidence State

Represent these states clearly:

- Evidence attached
- Multiple sources agree
- Single source only
- AI-inferred
- Evidence missing
- Evidence outdated
- Evidence conflicts with code
- Evidence conflicts with document
- Needs human review

### Conflict State

Conflicts must be visually distinct from normal content.

A conflict item should show:

- What is conflicting.
- Which sources disagree.
- Why it matters.
- Recommended resolution action.
- Whether user confirmation is needed.

### AI State

AI-generated or AI-inferred content must never look identical to verified source content.

Use labels such as:

- AI inferred
- Needs review
- Low confidence
- Generated from scan
- Confirmed by user
- Source verified

## UX Writing Rules

Use clear, result-oriented interface copy.

Prefer user-facing language over internal implementation terms.

Good examples:

- Connect Git Repository
- Start Project Scan
- Generate Project Wiki
- View Source Evidence
- Confirm This Fact
- Mark as Outdated
- Resolve Conflict
- Ask About This Project
- Generate Handover Package

Avoid vague or technical labels unless the target user clearly needs them:

- Submit
- Process
- Execute
- Run
- Sync Vector Store
- Parse AST
- Commit Memory Object

Technical terms are allowed when necessary, but they should be supported with explanation, tooltip, or progressive disclosure.

## Language-Specific Status Copy

Status labels, actions, and user-facing errors must follow the active UI language.

- Chinese mode must use Chinese status labels such as `当前有效`, `待确认`, `已被替代`, and `历史参考`.
- English mode must use `Current`, `Needs review`, `Superseded`, and `Historical`.
- Internal enum values may appear in APIs, logs, tests, and developer diagnostics, but must not appear in the main UI.
- Evidence excerpts, file paths, API endpoints, code symbols, and original document titles should keep the source language and should not be forcibly translated.

## Page-Level Requirements

When creating or modifying a page, define the following before coding:

1. Page goal
2. First visual focus
3. Primary action
4. Secondary actions
5. Current status display
6. Required empty state
7. Required loading state
8. Required success state
9. Required error state
10. Required no-permission state
11. Required no-result state
12. Advanced information that should be hidden or collapsed
13. Components to add, remove, or refactor

Apply this especially to:

- Dashboard
- Project detail page
- Source connector page
- Scan / sync status page
- Wiki page
- Facts page
- Conflict detection page
- Evidence viewer
- Ask page
- Handover page
- Settings page

## Dashboard Rules

The dashboard must answer:

1. Which project am I viewing?
2. Is the project connected to sources?
3. When was it last scanned?
4. Is the wiki generated?
5. Are there conflicts?
6. Are there facts requiring confirmation?
7. What should I do next?

The dashboard should prioritize:

- Project status summary
- Recommended next action
- Recent activity
- Scan / sync state
- Conflict and review indicators
- Entry points to wiki, facts, evidence, ask, and handover

Do not turn the dashboard into a decorative card grid with no clear task direction.

## Evidence Viewer Rules

Evidence is central to the product.

Any evidence viewer must show:

1. Source type
2. Source file or document
3. Relevant excerpt or reference
4. Last updated time if available
5. Confidence or reliability indicator
6. Related project fact
7. Whether AI inferred anything from this evidence
8. Action to open, compare, confirm, or reject

Evidence must be easy to inspect without overwhelming the main page.

Use progressive disclosure for long evidence chains.

## Conflict Resolution Rules

Conflict UI must be actionable.

Each conflict should show:

1. Conflict title
2. Conflicting claims
3. Source A
4. Source B
5. Why the conflict matters
6. Suggested resolution
7. User action

Possible actions:

- Accept code as source of truth
- Accept document as source of truth
- Mark document outdated
- Confirm manually
- Ignore this conflict
- Open related evidence

## Implementation Priorities

When improving UI, prioritize in this order:

### P0

- Clarify page purpose.
- Clarify current system state.
- Clarify primary action.
- Add missing empty states.
- Add loading, success, and failure states.
- Distinguish evidence, AI inference, conflict, and user confirmation.
- Make clickable elements discoverable.

### P1

- Improve information hierarchy.
- Improve onboarding path.
- Improve button and status copy.
- Add hover, focus, active, and disabled states.
- Collapse advanced details.
- Improve evidence and conflict views.

### P2

- Animation.
- Advanced filters.
- Personalized layouts.
- Complex visualizations.
- Decorative polish.

Do not prioritize visual decoration before P0 and P1 usability issues are solved.

## Coding Rules for UI Work

When implementing UI:

1. Reuse existing components and design tokens when possible.
2. Do not introduce large dependencies unless necessary.
3. Do not break existing behavior.
4. Keep components readable and maintainable.
5. Prefer explicit state models over scattered boolean flags.
6. Keep mock data clearly separated from real data.
7. Use accessible labels for important controls.
8. Provide keyboard-visible focus states.
9. Avoid icon-only controls unless they include tooltip and aria-label.
10. Keep destructive actions visually and semantically distinct.

## Required Output Before Code Changes

Before modifying code for any UI-related task, output a short plan with:

1. User goal
2. Main UX problem
3. Proposed visual hierarchy
4. Required states
5. Primary action
6. Empty state strategy
7. Components to change
8. What will not be changed in this pass

Then implement.

## Required Self-Check After Code Changes

After implementing, verify:

1. Can the user understand the page purpose within 5 seconds?
2. Can the user identify the next action within 5 seconds?
3. Is the current project or system status visible?
4. Is there only one dominant primary action?
5. Are secondary actions visually lower priority?
6. Are empty, loading, success, failure, no-permission, and no-result states handled?
7. Are AI inference, source evidence, conflicts, and user confirmations visually distinct?
8. Are clickable elements discoverable?
9. Are hover, focus, active, and disabled states present where needed?
10. Is the copy result-oriented and user-facing?
11. Is advanced complexity hidden by default?
12. Did the change reduce user thinking cost?

At the end of the response, summarize:

- What changed
- Why it changed
- Which user confusion it solves
- Remaining UX risks
- Suggested next UX improvement
