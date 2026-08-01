# Your 4-agent dev team for Claude Code

This folder contains four Claude Code subagents that form a lightweight dev workflow: an idea goes in, a plan comes out, code gets built, someone tries to break it, and a manager gives you the real status.

## The team

- **Andy** (architect) — turns your idea into a concrete build plan and asks the key clarifying questions *before* writing the plan (not after code exists).
- **Dimitri** (coder) — implements Andy's plan. Doesn't re-design, just builds it faithfully and flags real deviations.
- **Thaddeus** (tester) — actively tries to break what Dimitri built. Adversarial by design: boundaries, edge cases, malformed input, not just the happy path.
- **Marquavion** (manager) — reviews the plan, the code, and the test results, spot-checks independently, and gives you a plain-language status with the issues that actually matter, ranked by severity.

## How to install

1. Copy the `.claude/agents/` folder into the root of your project (so you end up with `<your-project>/.claude/agents/andy.md`, etc.). This makes the agents available in that project only.
   - To make them available in *every* project instead, copy the four `.md` files into `~/.claude/agents/` in your home directory.
2. In Claude Code, run `/agents` to confirm all four show up (andy, dimitri, thaddeus, marquavion).
3. That's it — no restart needed for project-level agents in most setups; if they don't show up, restart Claude Code.

## How to use them

Claude Code can invoke these automatically based on their `description` field (e.g. asking to build something new will tend to trigger Andy first), or you can call them directly by name:

```
Use Andy to plan out a CSV import feature for the admin panel.
```

Then, once you're happy with the plan:

```
Use Dimitri to implement PLAN.md.
```

Then:

```
Use Thaddeus to try to break what was just built.
```

And finally, before you consider it done:

```
Use Marquavion to review the plan, the code, and the test results, and tell me if this is ready.
```

## Customizing

Each agent file has a YAML frontmatter block at the top:

```yaml
---
name: andy
description: ...
tools: Read, Grep, Glob, WebFetch, WebSearch, Write
model: opus
---
```

- `tools` — trim or expand this list to control exactly what each agent can touch. For example, if you don't want Andy writing PLAN.md to disk, remove `Write`.
- `model` — set to whichever model tier you want that agent to run on (e.g. `opus`, `sonnet`, `haiku`), or delete the line to inherit whatever model the main conversation is using.
- The body of each file is the agent's system prompt, including its name — edit freely to match how you actually want that role to behave (or rename it again).
- Want a 5th "Designer" role instead of folding it into Dimitri? Say the word and I'll split it out as its own agent.
