# Worktree Execution and Parallel Branch Isolation

## Purpose

Define how EngineeringOS-compatible execution isolates writable tasks so multiple tasks can run safely in parallel without sharing uncommitted state, Git index state, or branch ownership.

This workflow complements `execution.md`, `git-publishing-and-human-merge.md`, and `ci-feedback-and-repair.md`.

## Default rule

Every task that grants `WRITE` capability SHOULD execute in a dedicated task branch and a dedicated Git worktree.

```text
main checkout
  |
  +-- worktree task A -> branch task/A
  |
  +-- worktree task B -> branch task/B
```

The primary checkout is the local control-plane checkout for synchronizing `main`, inspecting repository state, creating/removing worktrees, and recovering after merge. Builders SHOULD NOT use the primary checkout for writable task implementation when a dedicated worktree can be created.

## Parallelism assessment

Before starting multiple writable tasks concurrently, the Planner or orchestration layer MUST classify their relationship as one of:

```text
SAFE_TO_PARALLELIZE
PARALLELISM_RISK
DEPENDENCY_BLOCKED
```

Worktrees isolate Git state; they do not prove semantic parallel safety.

They also do not isolate **shared external state**. Classification MUST therefore cover
both questions:

```text
1. Do these tasks depend on each other?          -> semantic safety
2. Do they write to the same external resource?  -> execution safety
```

Two tasks can be fully independent by the first question and still collide by the second.

## Shared external state

A dedicated worktree isolates the working tree, the index, and branch ownership. It isolates
nothing outside the repository. A database, a schema-migration history, an object store, a
cache, a message broker, a fixture directory, or a scratch/temporary directory shared by two
concurrent Builders is a single mutable resource with concurrent writers.

Before authorizing concurrent writable execution, the orchestration layer MUST identify the
external resources each task writes to, and either isolate them per task or record
`PARALLELISM_RISK` with the resolution.

```text
EXTERNAL STATE ISOLATION

task_id: <value>
resource: <database | object store | broker | cache | scratch directory | other>
isolation: <dedicated | shared-read-only | shared-writable>
resolution: <required when shared-writable>
```

Provisioning a per-task instance is usually cheap — creating a database costs seconds — and
is the default answer whenever a task runs schema migrations.

**Why this deserves its own rule.** A shared-external-state collision does not look like a
collision. Git conflicts announce themselves at merge; this one arrives as a failing test in
a task that did not cause it. One task applies a migration the other's branch does not
contain, and the second task's fixtures fail with an error naming a revision it has never
heard of. The natural reading is "my change broke something", and the cost is a wrong
diagnosis before the real cause is found.

An ordering convention is also part of isolation when the resource is a shared linear
history. Migration identifiers drawn from the same head by two concurrent tasks produce
divergent chains; the range each task may use SHOULD be declared before execution starts,
and rebased onto the true head at integration.

Isolation is provisioned **before** the Builder starts, not after the first collision.

## One task, one execution ownership

```text
one task
  -> one task branch
  -> one writable worktree
  -> one active Builder ownership
```

A second Builder MUST NOT write to the same task worktree concurrently.

## Creation lifecycle

```text
GitHub Issue / Task Contract
        ↓
Planner
        ↓
Parallelism assessment
        ↓
Task branch
        ↓
Dedicated worktree
        ↓
Builder
```

Conceptual commands:

```bash
git switch main
git pull --ff-only origin main
git worktree add ../<repo>-issue-<N> -b <task-branch> main
```

## Design-gated interface work

For `INTERFACE_CHANGE`, branch/worktree creation does not authorize implementation before Human Design Approval.

## Publishing lifecycle

The worktree is an isolated execution sandbox, not an integration destination.

```text
task worktree
  ↓
Builder + local validation
  ↓
Reviewer
  ↓
commit(s) + push
  ↓
GitHub PR
  ↓
required remote CI
  ↓
CI_GREEN
  ↓
READY_FOR_HUMAN_REVIEW
  ↓
HUMAN MERGE GATE
```

GitHub PR is the canonical integration path. The harness MUST NOT merge the task branch into local `main` as the normal delivery mechanism.

## Synchronization after another PR merges

If another PR changes `main`, the remaining task branch may need synchronization. Rebase may be used when project policy allows it:

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease
```

Never use unconditional `--force`. Any synchronization that changes the reviewed revision invalidates stale validation evidence; affected validation and review must run again.

## Human merge and harness-owned cleanup

After the human merges the PR, the local harness/orchestrator that owns the task SHOULD finalize the local execution environment automatically when it has filesystem access.

```text
PR merged by human
  ↓
confirm merge remotely
  ↓
fetch origin
  ↓
primary local main --ff-only
  ↓
prove task branch is integrated
  ↓
prove task worktree is safe to remove
  ↓
remove worktree
  ↓
delete local task branch
  ↓
delete remote task branch
  ↓
prune worktree metadata
  ↓
POST_MERGE_CLEANUP_COMPLETE
```

Post-merge cleanup is deterministic lifecycle work, not a recurring human chore. A second human approval is not required because the human decision was the PR merge; cleanup only disposes of an already-integrated execution sandbox.

The default lifecycle for short-lived task branches is therefore:

```text
one task
→ one task branch
→ one dedicated worktree
→ PR
→ human merge
→ remove worktree
→ remove local branch
→ remove remote branch
```

Conceptual commands:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git worktree remove ../<repo>-issue-<N>
git branch -d <task-branch>
git push origin --delete <task-branch>
git worktree prune
```

Remote task-branch deletion is the default after a confirmed merge when all cleanup safety conditions are satisfied. A project MAY explicitly retain a remote branch only when there is a concrete reason, such as ongoing investigation, an active dependent review, preserved release/hotfix work, or another documented lifecycle requirement.

A harness MUST NOT retain merged short-lived task branches merely because deletion is optional in Git. If a remote branch is intentionally retained, the reason SHOULD be recorded in cleanup evidence.

## Cleanup safety gate

Before removing anything, the harness MUST prove all applicable conditions:

```text
PR_MERGED
AND task branch integrated in target branch
AND worktree has no uncommitted/untracked user work
AND no active writable Builder owns the worktree
AND no open review depends on mutable local-only evidence
AND no active dependent workflow/review requires the remote task branch
AND primary main can be synchronized safely
```

If every condition passes:

```text
POST_MERGE_CLEANUP_COMPLETE
```

This state means, by default:

```text
worktree removed
AND local task branch removed
AND remote task branch removed
AND worktree metadata pruned
```

If any condition cannot be proven:

```text
POST_MERGE_CLEANUP_BLOCKED
```

The harness leaves the affected resource intact and reports the reason. Cleanup may be partially completed only when doing so cannot endanger remaining evidence/work; the final cleanup state must still identify what remains.

The harness MUST NOT:

- use `git worktree remove --force` to bypass uncommitted work;
- delete another active task's worktree;
- delete a branch not safely integrated or explicitly abandoned;
- delete a remote branch still required by an active review/workflow;
- delete evidence required by an open review;
- infer merge merely because a remote branch disappeared;
- merge locally to bypass the GitHub Human Gate.

## Read-only roles

Planner and Reviewer may use an existing checkout when truly read-only. Reviewer MUST NOT modify the Builder worktree.

## Evidence

Execution evidence SHOULD record task ID, branch, worktree identity when useful, base revision, parallelism classification, external state isolation, synchronization events, final commit SHA(s), PR URL, merge commit SHA, and cleanup state (`POST_MERGE_CLEANUP_COMPLETE` or `POST_MERGE_CLEANUP_BLOCKED`).

Cleanup evidence SHOULD also record:

- worktree removal result;
- local branch deletion result;
- remote branch deletion result;
- explicit retention reason when a merged remote task branch is intentionally preserved.

Local absolute paths are operational evidence, not portable Task Contract requirements.

## FinOps

Worktree creation, branch creation, merge detection, cleanup, remote-branch deletion, synchronization checks, and Git metadata propagation are deterministic operations and MUST NOT invoke an LLM merely for convenience.
