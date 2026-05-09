"""MCP Prompts — reusable workflow skills for AI agents."""

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP):
    """Register all workflow prompts on the MCP server."""

    @mcp.prompt()
    def work_summary() -> str:
        """Insight-driven dashboard: active work, blockers, and next actions.

        Call get_context() and present a compact status report:
        - Status counts (queue/work/review/done/blocked)
        - Active items with progress
        - Blocked items with reasons
        - Next recommended action
        """
        return """Analyze the current work state and present a compact dashboard.

Steps:
1. Call get_context() for the global overview
2. For each active item, call get_context(item_id=...) to get children and notes
3. Present results as:

📋 Tarefas: X queue | Y work | Z done | W blocked
🔨 Em andamento: [list active items with status]
🚫 Bloqueado: [list blocked items with what blocks them]
⏭️ Próximo: [next recommended item from get_next_item()]

Keep it concise. Use emoji for visual scanning. Group by project (parent)."""

    @mcp.prompt()
    def create_item_from_context() -> str:
        """Create a tracked work item from the current conversation context.

        Analyze what the user is working on and create appropriate work items.
        """
        return """Based on the current conversation, create work items to track the work.

Steps:
1. Identify the main task and any subtasks from the conversation
2. Check if similar items already exist using query_items(operation="list", search="...")
3. If not, create items with appropriate hierarchy:
   - Find or create the parent Epic/project
   - Create child tasks with clear titles and descriptions
   - Set priority based on urgency discussed
   - Add dependencies if tasks have ordering requirements
4. Add notes with context from the conversation (requirements, decisions made)
5. Confirm what was created to the user"""

    @mcp.prompt()
    def quick_start() -> str:
        """Interactive onboarding — teaches by doing, adapts to empty or populated workspaces."""
        return """Help the user get started with the task orchestrator.

Steps:
1. Call get_context() to check current state
2. If empty (no items):
   - Ask what project they're working on
   - Create a sample work tree with create_work_tree
   - Show how to advance items and add notes
3. If populated:
   - Show the work summary
   - Explain the workflow: queue → work → review → done
   - Show available triggers: start, complete, block, resume, cancel, reopen
   - Demonstrate get_next_item() for priority-based work selection
4. Mention note schemas if .taskorchestrator/config.yaml exists"""

    @mcp.prompt()
    def status_progression(item_id: str) -> str:
        """Navigate role transitions; shows gate status and the correct trigger."""
        return f"""Show the status progression options for item {item_id}.

Steps:
1. Call get_context(item_id="{item_id}") to get current state, notes, and gate info
2. Show current status and available transitions:
   - For each valid trigger, call get_next_status(item_id="{item_id}", trigger=...) 
3. Present as a clear map:
   Current: [status]
   Available transitions:
   → start: [current] → [next] [✅ ready | ❌ blocked by: ...]
   → complete: [current] → done [✅ ready | ❌ missing notes: ...]
   → block: [current] → blocked
   → cancel: [current] → cancelled
4. If there are missing notes (gate check), show what needs to be filled
5. Suggest the most logical next action"""

    @mcp.prompt()
    def dependency_manager(item_id: str = "") -> str:
        """Visualize, create, and diagnose dependencies between work items."""
        target = f" for item {item_id}" if item_id else ""
        query = (
            f'query_dependencies(item_id="{item_id}", neighbors_only=false)'
            if item_id
            else "get_blocked_items()"
        )
        return f"""Visualize and manage dependencies{target}.

Steps:
1. Call {query} to get the dependency graph
2. Present as a visual tree:
   [Item A] ──blocks──→ [Item B] ──blocks──→ [Item C]
   Use ✅ for done items, 🔄 for in-progress, ⏳ for queue, 🚫 for blocked
3. Identify issues:
   - Circular dependencies (shouldn't exist but check)
   - Long chains that could be parallelized
   - Blocked items whose blockers are not being worked on
4. Suggest actions:
   - Which blocker to work on first
   - Dependencies that could be removed
   - Pattern shortcuts (linear, fan-out, fan-in) for new deps"""

    @mcp.prompt()
    def batch_complete(parent_id: str) -> str:
        """Complete or cancel multiple items at once — close out features or workstreams."""
        return f"""Batch-complete items under parent {parent_id}.

Steps:
1. Call get_context(item_id="{parent_id}") to see all children and their status
2. Show what will be completed and what will be skipped:
   ✅ Will complete: [items in queue/work/review]
   ⏭️ Already done: [items in done/cancelled]
   ❌ Cannot complete: [items blocked by deps or missing notes]
3. Ask for confirmation before proceeding
4. Call complete_tree(parent_id="{parent_id}")
5. Report results: X completed, Y skipped with reasons"""

    @mcp.prompt()
    def session_start() -> str:
        """Load current work context at the beginning of each session."""
        return """Initialize the work session by loading full context.

Steps:
1. Call get_context() for global dashboard
2. If there are items in 'work' status, these were in-progress — summarize them
3. If there are blocked items, highlight what's stuck and why
4. Call get_next_item() for the recommended next action
5. Present compact summary:

📋 Tarefas: X queue | Y work | Z done | W blocked
🔨 Em andamento: [active items]
⏭️ Próximo: [next recommended item]
🚫 Bloqueado: [blocked items with reasons]

Ask the user what they want to work on."""
