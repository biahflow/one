package cli

import (
	"errors"
	"fmt"

	"github.com/spf13/cobra"
)

// Every command below is declared and none is implemented. They print no progress and
// report no result: a command that prints "✓ Worktrees created" without creating a
// worktree is worse than a missing command, because the false green survives inside
// output that looks fine. `biah run` printed four completed tasks for workers it never
// invoked, and `biah status` listed a task as IN_PROGRESS that did not exist.
//
// The declarations stay because `--help` documents where the orchestrator is going.
// The exit code stays non-zero because it has not arrived.

// ErrNotImplemented is returned by every biah command. See MILESTONES.md.
var ErrNotImplemented = errors.New("the biah orchestrator is not implemented")

func notImplemented(what string) error {
	return fmt.Errorf(
		"%w: %s.\n\n"+
			"Today the operating model is the convention, not this binary: read\n"+
			"  workflows/execution.md              task portability and harness parity\n"+
			"  workflows/worktree-execution.md     one task, one branch, one worktree\n"+
			"  workflows/review-feedback-and-repair.md\n"+
			"  workflows/ci-feedback-and-repair.md\n"+
			"  workflows/git-publishing-and-human-merge.md\n"+
			"and have a harness follow it. A human still merges",
		ErrNotImplemented, what,
	)
}

// NewRootCommand creates the root biah command.
func NewRootCommand() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "biah",
		Short: "Biah: vendor-neutral multi-agent orchestrator (not implemented)",
		Long: `Biah is the intended orchestration layer for Engineering OS.

NOT IMPLEMENTED. No subcommand does any work; each one exits non-zero. The
capability declarations and the routing model are real and are read by other
code; the planning, execution, evidence collection and gates are not.

The operating model today is the convention in workflows/, followed by a
harness and verified by a human. See MILESTONES.md for what would change that.

Intended, once implemented:

  biah task <id>       Accept and validate a task contract
  biah plan <id>       Show the execution plan (DAG + routing)
  biah run <id>        Execute the plan in isolated worktrees
  biah review <id>     Aggregate evidence and check parity
  biah evidence <id>   Show the complete evidence package
  biah status          Show all tasks and their state
`,
		Version:       "0.0.1-alpha",
		SilenceUsage:  true,
		SilenceErrors: false,
	}

	cmd.AddCommand(
		NewTaskCommand(),
		NewPlanCommand(),
		NewRunCommand(),
		NewReviewCommand(),
		NewStatusCommand(),
		NewEvidenceCommand(),
	)

	return cmd
}

func stubCommand(use, short, what string, args cobra.PositionalArgs) *cobra.Command {
	return &cobra.Command{
		Use:   use,
		Short: short + " (not implemented)",
		Args:  args,
		RunE: func(cmd *cobra.Command, args []string) error {
			return notImplemented(what)
		},
	}
}

// NewTaskCommand would load and validate a task contract.
func NewTaskCommand() *cobra.Command {
	return stubCommand("task <task-id>", "Load and validate a task contract",
		"no contract is loaded and none is validated", cobra.ExactArgs(1))
}

// NewPlanCommand would produce the DAG and route each task by capability.
func NewPlanCommand() *cobra.Command {
	return stubCommand("plan <task-id>", "Show execution plan (DAG + routing)",
		"no DAG is derived; the plan it used to print was hard-coded for one task id",
		cobra.ExactArgs(1))
}

// NewRunCommand would create worktrees and invoke each worker.
func NewRunCommand() *cobra.Command {
	return stubCommand("run <task-id>", "Execute the task plan",
		"no worktree is created and no worker is invoked", cobra.ExactArgs(1))
}

// NewReviewCommand would aggregate evidence and check parity across workers.
func NewReviewCommand() *cobra.Command {
	return stubCommand("review <task-id>", "Review evidence and request approval",
		"no evidence is read and no parity is checked", cobra.ExactArgs(1))
}

// NewStatusCommand would show the real state of every known task.
func NewStatusCommand() *cobra.Command {
	return stubCommand("status", "Show all tasks and status",
		"no task state is tracked; the listing it used to print was invented",
		cobra.NoArgs)
}

// NewEvidenceCommand would show the aggregated evidence package.
func NewEvidenceCommand() *cobra.Command {
	return stubCommand("evidence <task-id>", "Show complete evidence package",
		"no evidence package is produced", cobra.ExactArgs(1))
}
