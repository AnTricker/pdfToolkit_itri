# Local Solo-Development Instructions

## Identity

* Instruction set ID: `LOCAL_SOLO_MATT_BUDGET_V5`
* This repository is primarily developed locally by one developer.
* Use the smallest sufficient workflow.
* Avoid broad exploration, repeated review, unnecessary skill invocation, and multi-agent overhead.

---

## Task sizing

Before substantial work, classify the task as `Small`, `Medium`, or `Large`.

### Small

Typical characteristics:

* one clear behavior
* one or a few related files
* known root cause or straightforward change
* verifiable with one targeted command

Workflow:

1. inspect relevant files
2. make the smallest coherent change
3. run targeted verification
4. stop when verified

Do not invoke planning, review, or sub-agent workflows.

### Medium

Typical characteristics:

* several related files or modules
* non-obvious bug
* state, interface, or dependency interaction
* multiple plausible root causes
* requirements are mostly clear

Start with targeted inspection in the primary agent.

Possible skills, only when needed:

* `diagnosing-bugs` for unclear failures
* `tdd` when a stable test seam exists
* `domain-modeling` when domain meaning is unclear
* `codebase-design` when interfaces or module boundaries are central

Escalation must be proposed before use.

### Large

Typical characteristics:

* unclear or conflicting requirements
* cross-module architecture change
* new domain concepts or lifecycle
* schema, migration, security, destructive operation, or public API change
* difficult rollback or broad impact

Suggested sequence:

1. `grill-me` or `grill-with-docs`
2. `to-spec`
3. implementation in small verified slices
4. review only when explicitly requested or risk justifies it

Do not begin a Large workflow without user approval.

---

## Escalation approval gate

Before invoking a higher-cost or broader workflow, stop and request explicit user approval.

Approval is required before:

* `grill-me`
* `grill-with-docs`
* `to-spec`
* `to-tickets`
* `/implement`
* formal `diagnosing-bugs`
* formal `tdd`
* `domain-modeling`
* `codebase-design`
* `code-review`
* any sub-agent or parallel-agent workflow
* repository-wide exploration
* full test suite, integration, end-to-end, performance, or long-running tests
* creating or substantially updating ADRs, specifications, tickets, issues, or pull requests
* any Git command or Git-based workflow

Use this format:

```text
Escalation proposal

Task size:
Current findings:
Why escalation is needed:
Proposed skill or workflow:
Scope:
Expected benefit:
Expected additional cost:
Lower-cost alternative:

Proceed? [yes/no]
```

Rules:

* wait for explicit approval before continuing
* approval applies only to the stated workflow and scope
* request approval again before expanding scope
* a user-invoked skill is approved only for that invocation

---

## Default workflow

For routine inspection, debugging, implementation, documentation, and refactoring:

1. read only relevant files
2. use minimal necessary context, such as `CONTEXT.md`, ADRs, and tests
3. reproduce the issue with the smallest useful command
4. apply the smallest coherent change
5. run the smallest relevant verification
6. re-check only modified files when needed
7. report concisely

Do not expand routine work into:

* repository-wide audit
* full architecture review
* formal code review
* multi-agent workflow
* full test-suite run

without approval.

Stop broad exploration once there is enough evidence to implement and verify a credible fix.

---

## Skill usage

Skills are on-demand tools, not default steps.

Use a skill only when it clearly reduces uncertainty or risk:

* unclear or multi-cause bug → `diagnosing-bugs`
* behavior with a stable test seam → `tdd`
* unclear domain meaning or lifecycle → `domain-modeling`
* unclear module boundaries or interfaces → `codebase-design`
* unclear requirements or scope → `grill-me`
* clarification that affects durable project knowledge → `grill-with-docs`
* settled requirements ready for formalization → `to-spec`

Do not invoke skills for:

* simple syntax fixes
* clear single-file bugs
* known solutions
* cosmetic refactoring
* routine file inspection
* ordinary targeted testing

Rules:

* prefer the smallest direct solution first
* never chain multiple skills without approval
* do not repeat the same skill unless materially new information appears

---

## `/implement`

When explicitly approved:

* implement only the approved scope
* do not automatically invoke `code-review`
* do not launch review sub-agents
* do not use Git
* make only the requested changes; do not broaden scope or perform unrelated cleanup
* after implementation, run one necessary targeted verification pass by default
* do not repeat tests, re-read unrelated files, re-plan, or re-review unless the targeted verification fails or new evidence requires it
* when verification passes, stop immediately and report the change and result concisely

Implementation default:

`requested change → one targeted verification pass → concise report → stop`

Avoid extra exploration, repeated validation, speculative improvements, and other work that does not materially increase confidence in the requested change.

---

## Code review

`code-review` is disabled by default.

Propose it only for:

* explicit user request
* security-sensitive changes
* destructive operations
* migrations
* public API or persistent-data compatibility
* large cross-module refactoring
* formal delivery to another developer or team

Prefer a targeted review of named files and behaviors over a full-system or parallel-agent review.

---

## Sub-agent policy

Keep routine work in the primary agent.

Sub-agents:

* require explicit approval
* must have narrow, non-overlapping scopes
* must not duplicate analysis already performed
* must reuse existing findings
* must not perform automatic second or third review passes

---

## Git prohibition

Do not run any Git command by default.

This includes read-only and write operations such as:

* `git status`
* `git diff`
* `git log`
* `git show`
* `git add`
* `git commit`
* branch, stash, reset, restore, checkout, merge, or rebase operations

Use direct file inspection, direct editing, targeted search, and targeted verification instead.

When Git appears necessary, stop and explain:

* why Git is required
* the exact command proposed
* what files or history it will inspect or modify
* why direct file inspection is insufficient
* the lower-cost alternative, if available

Wait for explicit user approval before running the command.

Approval to inspect or modify source code does not imply approval to use Git.

---

## Test and search budget

* use precise filenames, symbols, error messages, and directories
* limit recursive searches and command output
* avoid repeatedly reading unchanged content
* run the smallest relevant test or validation target
* avoid full-suite and long-running tests by default
* request approval before broad exploration or verification

---

## Execution ergonomics

For long, repetitive, or waiting-heavy operations:

* avoid fragmented command sequences
* provide one complete executable command set when user execution is more efficient

Report:

* current state
* completed work
* remaining work
* expected output
* verification method

---

## Language

* 回覆與專案文件主要使用繁體中文
* code, identifiers, filenames, commands, and technical terms may remain in English

---

## Completion report

Report only:

* task classification
* files changed
* behavior implemented or corrected
* targeted verification results
* unresolved risks or gaps

Do not print a full diff unless explicitly requested and approved.
