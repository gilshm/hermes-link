# Hermes Link

Hermes Link is currently a minimal agent-to-agent message testbed.

The first supported behavior is intentionally small:

1. `agent_a` sends a message to `agent_b`.
2. `agent_b` sends one response back to `agent_a`.
3. Hermes Link keeps one Hermes session per agent while mediating the exchange.

There is no plugin bridge, persistence, retry logic, or background service in this rewrite.

## Run

Install the local wrapper and copy the skill into org profiles:

```bash
python3 install.py
```

This installs:

- `bin/hermes_link`: a repo-local wrapper for `python3 -m hermes_link.cli`.
- `skills/agent-comms`: copied into selected Hermes profiles.
- `hermes-link` plugin: copied into selected Hermes profiles and enabled.

The installer discovers profiles under `~/.hermes/profiles` and asks where to install
the skill. Press Enter to install into all discovered profiles. In non-interactive
runs, it defaults to all.

Desktop/TUI agents use the installed `route_message` plugin tool. The mediated CLI
entry point is `bin/hermes_link chat ...`.

In-memory demo:

```bash
python -m hermes_link.demo
```

Expected output:

```text
agent_a -> agent_b: ping
agent_b -> agent_a: pong
```

Talk to a real org agent through Hermes Link:

```bash
bin/hermes_link chat agent_a "Ask agent_b for one short reply, then answer me."
```

Hermes Link loads [config/org.yaml](config/org.yaml), injects the
[agent-comms skill](skills/agent-comms/SKILL.md), and routes any response shaped like:

```text
SEND agent_b: message
```

The skill teaches agents this convention. The Python runner performs the actual delivery
and resumes the same Hermes session for each agent.

`config/org.yaml` also describes each agent's expertise. Hermes Link includes this
directory in routed prompts so agents have a reason to contact the right peer instead
of guessing from ids alone.

## Test

```bash
python -m unittest discover -s tests -v
```

Live Hermes profile smoke test:

```bash
HERMES_LINK_RUN_REAL_AGENTS=1 python -m unittest tests.test_real_hermes_agents -v
```

## Code Shape

- `hermes_link.message.Message`: immutable message object.
- `hermes_link.agent.Agent`: small named handler wrapper.
- `hermes_link.runtime.Runtime`: synchronous in-memory delivery loop.
- `hermes_link.hermes_runner.HermesRunner`: real Hermes profile mediator.
- `config/org.yaml`: available org agents.
- `skills/agent-comms/SKILL.md`: routing convention shown to agents.
- `hermes_link.demo`: executable round-trip demo.
