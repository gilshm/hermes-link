---
name: agent-comms
description: Use this skill when a Hermes agent should send messages to another configured agent through Hermes Link.
---

# Agent Communications

Hermes Link can deliver messages to another agent in the org while preserving
that agent's Hermes session for the routed conversation.

Use the Hermes Link org directory to decide who to contact. Contact another
agent when their expertise is a better fit for part of the user's request, when
you need a second opinion, or when the user explicitly asks you to talk to them.

If the `route_message` tool is available, use it to contact another agent:

- `from_agent`: your agent id.
- `to`: the target agent id.
- `body`: the message to deliver.

If no `route_message` tool is available, output exactly one routing directive:

```text
SEND agent_id: message
```

Examples:

```text
SEND hl_advisor: Please review this idea and respond to hl_ceo.
SEND hl_ceo: I reviewed it. The smallest next step is clear.
```

Rules:

- Use only agent ids that exist in the org.
- Choose the recipient based on the expertise listed in the org directory.
- You may also use configured topics such as `@review` when the org directory
  lists them.
- Hermes Link may block a route by org policy. If that happens, explain the
  block to the user instead of retrying the same route.
- Put the full message after the colon.
- Do not wrap the directive in Markdown.
- If you are done and want to answer the user, do not use `SEND`; answer normally.
