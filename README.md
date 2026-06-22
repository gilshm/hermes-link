# Hermes Link

Hermes Link lets independent Hermes agents communicate with each other while
keeping their own Hermes identities, sessions, and responsibilities.

The core flow is:

1. A user talks to an agent, usually `hl_ceo`.
2. That agent decides whether another configured agent should help.
3. Hermes Link delivers the message to the target agent and preserves the target
   agent's session for future messages in the same routed thread.
4. Replies are routed back through the originating agent so it can answer the
   user with the delegated context included.

Agents are declared in [config/org.yaml](config/org.yaml). Each entry defines the
Hermes command to run and the agent's expertise, which is shown to agents so they
can choose the right peer instead of guessing from ids.

## Install

Install the local CLI wrapper, communication skill, and plugin into Hermes
profiles:

```bash
python3 install.py
```

The installer discovers profiles under `~/.hermes/profiles` and asks where to
install. Press Enter to install into all discovered profiles. In non-interactive
runs, it defaults to all profiles.

Installed pieces:

- `bin/hermes_link`: repo-local wrapper for `python -m hermes_link.cli`.
- `skills/agent-comms`: instructions copied into selected Hermes profiles.
- `hermes-link` plugin: `route_message` tool copied into selected Hermes
  profiles and enabled.

Useful installer flags:

```bash
python3 install.py --create-profiles --clone-from base
python3 install.py --all
python3 install.py --profile hl_ceo --profile hl_advisor
python3 install.py --skip-wrapper
python3 install.py --skip-skills
python3 install.py --skip-plugin
```

Validate the org and local install inputs:

```bash
bin/hermes_link org validate
```

## Configure The Org

`config/org.yaml` is the directory agents see when deciding who to contact:

```yaml
agents:
  hl_ceo:
    command: hl_ceo
    title: CEO
    team: executive
    expertise: >
      First-contact executive and final decision maker.
  hl_advisor:
    command: hl_advisor
    title: Strategic Advisor
    team: executive
    manager: hl_ceo
    expertise: >
      Independent senior advisor.
  hl_cto:
    command: hl_cto
    title: CTO
    team: executive
    manager: hl_ceo
    expertise: >
      Technical executive.
  hl_product_manager:
    command: hl_product_manager
    title: Product Manager
    team: product
    manager: hl_ceo
    expertise: >
      Product lead.
  hl_backend_engineer:
    command: hl_backend_engineer
    title: Backend Engineer
    team: engineering
    manager: hl_cto
    expertise: >
      Backend implementation specialist.
  hl_frontend_engineer:
    command: hl_frontend_engineer
    title: Frontend Engineer
    team: engineering
    manager: hl_cto
    expertise: >
      Frontend implementation specialist.

topics:
  review:
    default: hl_advisor
    agents:
      - hl_advisor
      - hl_cto

skill: skills/agent-comms/SKILL.md
max_messages: 12
```

Agents can route directly to another agent id, or to a topic such as `@review`.
Topics resolve to their configured default agent.

By default, the org is flat: any configured agent may message any other
configured agent. Add an optional `routing` section to enforce hierarchy or team
boundaries:

```yaml
routing:
  default: deny
  allow:
    hl_ceo:
      - "*"
    hl_cto:
      - hl_ceo
      - hl_backend_engineer
      - hl_frontend_engineer
    hl_backend_engineer:
      - hl_cto
      - hl_frontend_engineer
  deny:
    hl_backend_engineer:
      - hl_ceo
```

`deny` wins over `allow`. `*` can be used as a sender or recipient wildcard. If
a route is blocked, Hermes Link does not call the target agent; it returns a
policy-blocked message to the sending agent and writes a blocked event to the
log.

## How Agents Route

Desktop and TUI agents use the installed `route_message` plugin tool when it is
available. The plugin calls back into this repository, runs the target Hermes
profile, and returns a transcript to the calling agent.

The skill also documents a text fallback:

```text
SEND hl_advisor: message
SEND @review: message
```

The Python runner parses these `SEND` directives, delivers messages, and resumes
the same Hermes session for each participating agent. If a routed recipient
answers normally instead of sending another `SEND`, Hermes Link records that
reply and resumes the originating agent so it can answer the user.

## Use The CLI

Talk to an org agent through Hermes Link:

```bash
bin/hermes_link chat hl_ceo "Ask hl_advisor for one short review, then answer me."
```

Show configured agents and local install state:

```bash
bin/hermes_link agents
```

Run a live health prompt against each configured agent:

```bash
bin/hermes_link agents --check
```

Show persisted source-session to target-session mappings:

```bash
bin/hermes_link sessions
```

Validate the org config:

```bash
bin/hermes_link org validate
```

Run the install/config doctor:

```bash
bin/hermes_link doctor
bin/hermes_link doctor --check-agents
```

## Logs

Hermes Link writes routed events to `.hermes-link/events.jsonl`.

Show the log:

```bash
bin/hermes_link log
```

Show one conversation trace by thread id or source session id:

```bash
bin/hermes_link trace <thread_id>
```

Watch messages live:

```bash
bin/hermes_link log --watch
```

Force color output:

```bash
bin/hermes_link log --watch --color always
```

Log output includes timestamps, thread ids, and branch markers so related
messages line up:

```text
2026-06-21 22:00:00 [abc123] ┌─ bridge hl_ceo -> hl_advisor: hi
2026-06-21 22:00:01 [abc123] ├─ hl_advisor -> hl_ceo: hello
2026-06-21 22:00:02 [abc123] └─ hl_ceo final: thanks
```

## Test

Run the offline suite:

```bash
python -m unittest discover -s tests -v
```

Run the live Hermes profile tests:

```bash
HERMES_LINK_RUN_REAL_AGENTS=1 python -m unittest tests.test_real_hermes_agents -v
```

The live tests require working `hl_ceo` and `hl_advisor` Hermes commands on `PATH`
with the plugin and skill installed.

## Code Shape

- `hermes_link.hermes_runner.HermesRunner`: real Hermes profile mediator.
- `hermes_link.bridge_runner`: plugin entrypoint for `route_message`.
- `hermes_link.org`: org config and topic resolution.
- `hermes_link.session_map.SessionMap`: source-session to target-session reuse.
- `hermes_link.log`: JSONL event log and formatted watcher output.
- `hermes_link.validation`: `org validate` checks.
- `skills/agent-comms/SKILL.md`: routing instructions shown to agents.
- `.hermes/plugins/hermes-link`: Hermes plugin source.
- `install.py`: profile discovery and install/enable flow.
- `hermes_link.demo`: in-memory round-trip demo for development.
