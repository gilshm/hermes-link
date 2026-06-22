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

If no `route_message` tool is available, output exactly one routing directive.
Use `SEND` when contacting one agent:

```text
SEND agent_id: message
```

Use `SEND_ALL` when contacting multiple agents in parallel and you need the
available replies before continuing:

```text
SEND_ALL:
- hl_backend_engineer: What's up?
- hl_frontend_engineer: What's up?
```

Examples:

```text
SEND hl_advisor: Please review this idea and respond to hl_ceo.
SEND hl_ceo: I reviewed it. The smallest next step is clear.
SEND_ALL:
- hl_backend_engineer: Please review the API impact.
- hl_frontend_engineer: Please review the UI impact.
```

Rules:

- Use only agent ids that exist in the org.
- Choose the recipient based on the expertise listed in the org directory.
- You may also use configured topics such as `@review` when the org directory
  lists them.
- Hermes Link may block a route by org policy. If that happens, explain the
  block to the user instead of retrying the same route.
- Use `SEND_ALL` for direct reports, team checks, parallel reviews, or asking
  several specialists independent questions.
- Do not use `SEND_ALL` if one message depends on another agent's reply; use
  sequential `SEND` messages instead.
- `SEND_ALL` can return partial results if one recipient is blocked, fails, or
  times out. Continue with the successful replies and mention missing replies.
- Keep each `SEND_ALL` message self-contained because recipients do not see the
  other recipients' messages.
- Put the full message after the colon.
- Do not wrap the directive in Markdown.
- If you are done and want to answer the user, do not use `SEND`; answer normally.
