package adapter

import (
	"context"
	"errors"
	"fmt"
)

// ErrNotImplemented is returned by every adapter that does not yet invoke a real
// worker. Returning a BuildReport of Status BUILD_COMPLETE with no files changed and
// no validation executed would be evidence that a build happened when none did — the
// exact failure the Definition of Done exists to prevent. A caller that cannot reach a
// worker must fail, not synthesise a green report.
var ErrNotImplemented = errors.New("adapter does not invoke a real worker yet")

func notImplemented(worker string) error {
	return fmt.Errorf(
		"%w: %s. Until it does, the operating model is the convention in "+
			"workflows/execution.md, followed by a harness and verified by a human",
		ErrNotImplemented, worker,
	)
}

// BuildReport represents the fixed-format output from a worker
type BuildReport struct {
	Status               string   `json:"status"` // BUILD_COMPLETE, BUILD_BLOCKED, etc.
	FilesChanged         []string `json:"files_changed"`
	ValidationExecuted   []string `json:"validation_executed"`
	ValidationSkipped    []string `json:"validation_skipped"`
	Assumptions          []string `json:"assumptions"`
	RemainingRisks       []string `json:"remaining_risks"`
	HumanDecisionsNeeded []string `json:"human_decisions_required"`
	WorkerName           string   `json:"worker_name"`
	TaskID               string   `json:"task_id"`
	RawOutput            string   `json:"raw_output"`
}

// WorktreeContext holds the execution context for a task
type WorktreeContext struct {
	TaskID       string
	WorktreePath string
	EnvVars      map[string]string
	Timeout      int // seconds
}

// Adapter is the interface all workers must implement
type Adapter interface {
	Name() string
	Capabilities() []string
	Invoke(ctx *WorktreeContext) (*BuildReport, error)
	InvokeWithContext(ctx context.Context, taskID string, worktreePath string) (*BuildReport, error)
}

// ClaudeAdapter declares Claude's capabilities for routing. It does not invoke
// Claude yet; Invoke and InvokeWithContext fail rather than report a build.
type ClaudeAdapter struct{}

func (a *ClaudeAdapter) Name() string {
	return "claude"
}

func (a *ClaudeAdapter) Capabilities() []string {
	return []string{
		"architecture_reasoning",
		"large_context",
		"refactoring",
	}
}

func (a *ClaudeAdapter) Invoke(ctx *WorktreeContext) (*BuildReport, error) {
	return nil, notImplemented("claude")
}

func (a *ClaudeAdapter) InvokeWithContext(ctx context.Context, taskID string, worktreePath string) (*BuildReport, error) {
	return nil, notImplemented("claude")
}

// CodexAdapter declares Codex's capabilities for routing. It does not invoke
// Codex yet; Invoke and InvokeWithContext fail rather than report a build.
type CodexAdapter struct{}

func (a *CodexAdapter) Name() string {
	return "codex"
}

func (a *CodexAdapter) Capabilities() []string {
	return []string{
		"implementation",
		"debugging",
		"testing",
		"code_review",
	}
}

func (a *CodexAdapter) Invoke(ctx *WorktreeContext) (*BuildReport, error) {
	return nil, notImplemented("codex")
}

func (a *CodexAdapter) InvokeWithContext(ctx context.Context, taskID string, worktreePath string) (*BuildReport, error) {
	return nil, notImplemented("codex")
}

// CopilotAdapter declares Copilot's capabilities for routing. It does not invoke
// Copilot yet; Invoke and InvokeWithContext fail rather than report a build.
type CopilotAdapter struct{}

func (a *CopilotAdapter) Name() string {
	return "copilot"
}

func (a *CopilotAdapter) Capabilities() []string {
	return []string{
		"implementation",
		"github_native",
		"repository_operations",
	}
}

func (a *CopilotAdapter) Invoke(ctx *WorktreeContext) (*BuildReport, error) {
	return nil, notImplemented("copilot")
}

func (a *CopilotAdapter) InvokeWithContext(ctx context.Context, taskID string, worktreePath string) (*BuildReport, error) {
	return nil, notImplemented("copilot")
}

// AdapterRegistry holds all available adapters
type AdapterRegistry struct {
	adapters map[string]Adapter
}

// NewRegistry creates a new adapter registry
func NewRegistry() *AdapterRegistry {
	return &AdapterRegistry{
		adapters: map[string]Adapter{
			"claude":  &ClaudeAdapter{},
			"codex":   &CodexAdapter{},
			"copilot": &CopilotAdapter{},
		},
	}
}

// Get retrieves an adapter by name
func (r *AdapterRegistry) Get(name string) (Adapter, error) {
	adapter, ok := r.adapters[name]
	if !ok {
		return nil, fmt.Errorf("unknown adapter: %s", name)
	}
	return adapter, nil
}
