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
- `mode`: use `send` for normal delegation, or `handoff` when the target agent
  should take over and answer the user directly. If omitted, mode is `send`.

When the user says "hand off", "transfer this", "let another agent take over",
or asks that another agent answer directly, call `route_message` with
`mode="handoff"`.

If no `route_message` tool is available, output exactly one routing directive.
Use `SEND` as the default text fallback when contacting one agent:

```text
SEND agent_id: message
```

Use `HANDOFF` when another agent should take over the conversation and answer
the user directly:

```text
HANDOFF agent_id: context for the agent taking over
```

Use `SEND_ALL` when contacting multiple agents in parallel and you need the
available replies before continuing:

```text
SEND_ALL:
- hl_backend_engineer: What's up?
- hl_frontend_engineer: What's up?
```

If the org directory lists a group alias, you may send the same message to all
agents in that group:

```text
SEND_ALL @engineering: What's up?
```

You may also use built-in broadcast targets relative to your agent:

```text
SEND_ALL @direct_reports: What's up?
SEND_ALL @manager: I need guidance on this.
SEND_ALL @peers: Please review this tradeoff.
SEND_ALL @team: Please each give a status update.
```

Examples:

```text
SEND hl_advisor: Please review this idea and respond to hl_ceo.
SEND hl_ceo: I reviewed it. The smallest next step is clear.
HANDOFF hl_cto: This is a technical architecture question. Please answer the user directly.
SEND_ALL:
- hl_backend_engineer: Please review the API impact.
- hl_frontend_engineer: Please review the UI impact.
SEND_ALL @engineering: Please each give a short implementation risk.
SEND_ALL @direct_reports: Please each give a short status update.
```

Rules:

- Use only agent ids that exist in the org.
- Choose the recipient based on the expertise listed in the org directory.
- Use `HANDOFF` only when the target agent should become the final owner of the
  conversation and respond directly to the user.
- If the `route_message` tool is available, prefer `mode="handoff"` over the
  text `HANDOFF` directive for handoff requests.
- You may also use configured topics such as `@review` when the org directory
  lists them.
- Use configured groups such as `@engineering` only with `SEND_ALL`; groups
  expand to multiple recipients and use scatter-gather.
- Use built-in broadcast targets only with `SEND_ALL`. They are resolved
  relative to your agent: `@direct_reports`, `@manager`, `@peers`, and `@team`.
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
