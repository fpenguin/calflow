# `claude_harness/` — Claude Code agent + skill definitions

This directory contains the harness configuration for Claude Code (and other
Claude-API-driven agents) operating in CalFlow.

## Activation

Different Claude tooling expects different paths:

| Tool | Expected path |
|---|---|
| Claude Code (current) | `.claude/agents/` and `.claude/skills/` |
| Claude Agent SDK | `~/.claude/agents/` (global) or `.claude/agents/` (project) |

Move the contents of this directory to `.claude/` after review:

```bash
mv claude_harness/agents .claude/agents
mv claude_harness/skills .claude/skills
rmdir claude_harness
```

This directory exists as `claude_harness/` rather than `.claude/` because
the harness was generated in a sandboxed session that blocked dotted-path
writes. Once moved, both names are equivalent.

## Contents

```
claude_harness/
├── agents/          # subagent definitions (5 files)
└── skills/          # reusable instruction patterns (14 files)
```

See `CLAUDE.md` (root) for project-level rules that apply unconditionally.
Agents and skills below refine those rules — they NEVER override.
