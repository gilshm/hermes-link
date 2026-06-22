from __future__ import annotations

import fcntl
import re
import shutil
import subprocess
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path

from hermes_link.directive import SendAllDirective, SendDirective, parse_send_directive
from hermes_link.log import EventLog
from hermes_link.message import Message
from hermes_link.org import OrgConfig


_SESSION_RE = re.compile(r"^session_id:\s*(\S+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class AgentTurn:
    agent: str
    session_id: str
    response: str


@dataclass(frozen=True)
class ChatResult:
    transcript: list[Message]
    turns: list[AgentTurn]
    final_response: str


@dataclass(frozen=True)
class RoutedSend:
    message: Message
    turn: AgentTurn


@dataclass(frozen=True)
class ScatterItem:
    recipient: str
    body: str
    ok: bool
    response: str
    turn: AgentTurn | None = None


class HermesRunner:
    def __init__(
        self,
        org: OrgConfig,
        *,
        cwd: Path,
        timeout: int = 120,
        sessions: dict[str, str] | None = None,
        event_log: EventLog | None = None,
        thread_id: str | None = None,
    ) -> None:
        self._org = org
        self._cwd = cwd
        self._timeout = timeout
        self._sessions: dict[str, str] = dict(sessions or {})
        self._skill_text = org.skill_path.read_text(encoding="utf-8")
        self._event_log = event_log
        self._thread_id = thread_id

    @property
    def sessions(self) -> dict[str, str]:
        return dict(self._sessions)

    def chat(
        self,
        agent: str,
        prompt: str,
        *,
        max_messages: int | None = None,
        stop_recipient: str | None = None,
    ) -> ChatResult:
        agent = self._resolve_agent(agent)
        limit = max_messages if max_messages is not None else self._org.max_messages
        if limit < 1:
            raise ValueError("max_messages must be at least 1")

        transcript: list[Message] = [Message("user", agent, prompt)]
        turns: list[AgentTurn] = []
        seen_messages: set[tuple[str, str, str]] = set()
        current_agent = agent
        current_prompt = self._agent_prompt(prompt, allow_tools=False)

        for _ in range(limit):
            turn = self._run_agent(current_agent, current_prompt)
            turns.append(turn)
            directive = parse_send_directive(turn.response)
            if directive is None:
                if current_agent != agent and len(turns) < limit:
                    transcript.append(Message(current_agent, agent, turn.response))
                    self._log(
                        "message",
                        from_agent=current_agent,
                        to_agent=agent,
                        from_session_id=turn.session_id,
                        to_session_id=self._sessions.get(agent),
                        body=turn.response,
                    )
                    final_prompt = self._agent_prompt(
                        "Original user request:\n"
                        f"{prompt}\n\n"
                        f"{current_agent} replied to you:\n\n{turn.response}\n\n"
                        "Answer the original user directly now. Do not output SEND. "
                        "If the original request required an exact final marker, include it.",
                        allow_tools=False,
                    )
                    final_turn = self._run_agent(agent, final_prompt)
                    turns.append(final_turn)
                    self._log(
                        "final",
                        agent=agent,
                        session_id=final_turn.session_id,
                        body=final_turn.response,
                    )
                    return ChatResult(transcript, turns, final_turn.response)
                self._log(
                    "final",
                    agent=current_agent,
                    session_id=turn.session_id,
                    body=turn.response,
                )
                return ChatResult(transcript, turns, turn.response)
            if isinstance(directive, SendAllDirective):
                scatter_items = self._run_scatter(current_agent, directive)
                for item in scatter_items:
                    transcript.append(Message(current_agent, item.recipient, item.body))
                    if item.turn is not None:
                        turns.append(item.turn)
                current_prompt = self._agent_prompt(
                    "Original user request:\n"
                    f"{prompt}\n\n"
                    "Scatter-gather results from your SEND_ALL request:\n\n"
                    f"{_format_scatter_results(scatter_items)}\n\n"
                    "Continue the conversation. Summarize successful replies and mention failures. "
                    "Do not retry failed recipients unless explicitly necessary.",
                    allow_tools=False,
                )
                continue

            recipient = self._resolve_agent(directive.recipient)
            if not self._org.can_route(current_agent, recipient):
                denial = _policy_denial(current_agent, recipient)
                self._log(
                    "blocked",
                    from_agent=current_agent,
                    to_agent=recipient,
                    from_session_id=turn.session_id,
                    body=directive.body,
                    reason=denial,
                )
                return ChatResult(transcript, turns, denial)
            transcript.append(Message(current_agent, recipient, directive.body))
            self._log(
                "message",
                from_agent=current_agent,
                to_agent=recipient,
                from_session_id=turn.session_id,
                to_session_id=self._sessions.get(recipient),
                body=directive.body,
            )
            signature = (current_agent, recipient, _normalize_body(directive.body))
            if signature in seen_messages:
                raise RuntimeError(f"repeated routed message detected: {current_agent} -> {recipient}")
            seen_messages.add(signature)
            if recipient == stop_recipient:
                return ChatResult(transcript, turns, directive.body)
            current_prompt = self._agent_prompt(
                "Original user request:\n"
                f"{prompt}\n\n"
                f"{current_agent} sent you this message:\n\n{directive.body}",
                allow_tools=False,
            )
            current_agent = recipient

        raise RuntimeError("agent exchange exceeded max_messages")

    def request_send(self, agent: str, prompt: str) -> RoutedSend:
        agent = self._resolve_agent(agent)
        turn = self._run_agent(agent, self._agent_prompt(prompt, allow_tools=False))
        directive = parse_send_directive(turn.response)
        if directive is None:
            raise RuntimeError(f"{agent} did not emit a SEND directive:\n{turn.response}")
        if isinstance(directive, SendAllDirective):
            raise RuntimeError(f"{agent} emitted SEND_ALL where one SEND directive was required:\n{turn.response}")
        recipient = self._resolve_agent(directive.recipient)
        if not self._org.can_route(agent, recipient):
            raise RuntimeError(_policy_denial(agent, recipient))
        return RoutedSend(
            message=Message(agent, recipient, directive.body),
            turn=turn,
        )

    def _run_agent(self, agent: str, prompt: str, timeout: int | None = None) -> AgentTurn:
        command = self._org.agents[agent].command
        if shutil.which(command) is None:
            raise RuntimeError(f"agent command not found for {agent}: {command}")
        args = [command, "chat", "-Q", "--pass-session-id", "--safe-mode", "--ignore-rules", "--toolsets", ""]
        if agent in self._sessions:
            args.extend(["-r", self._sessions[agent]])
        args.extend(["-q", prompt])

        with self._agent_lock(agent):
            completed = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout or self._timeout,
                cwd=self._cwd,
            )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{command} failed with exit code {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

        session_id = self._session_id_from_output(command, completed.stdout)
        self._sessions[agent] = session_id
        return AgentTurn(agent=agent, session_id=session_id, response=_clean_response(completed.stdout))

    def _run_scatter(self, sender: str, directive: SendAllDirective) -> list[ScatterItem]:
        batch = []
        for send in directive.sends:
            recipient = self._resolve_agent(send.recipient)
            batch.append(SendDirective(recipient=recipient, body=send.body))
        self._log(
            "scatter_start",
            from_agent=sender,
            recipients=[send.recipient for send in batch],
        )
        results: list[ScatterItem | None] = [None] * len(batch)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = {}
            for index, send in enumerate(batch):
                if not self._org.can_route(sender, send.recipient):
                    denial = _policy_denial(sender, send.recipient)
                    self._log(
                        "scatter_error",
                        from_agent=sender,
                        to_agent=send.recipient,
                        body=send.body,
                        reason=denial,
                    )
                    results[index] = ScatterItem(send.recipient, send.body, False, denial)
                    continue
                self._log(
                    "scatter_message",
                    from_agent=sender,
                    to_agent=send.recipient,
                    to_session_id=self._sessions.get(send.recipient),
                    body=send.body,
                )
                prompt = self._agent_prompt(
                    f"{sender} sent you this scatter-gather message:\n\n{send.body}\n\n"
                    "Answer normally. Do not output SEND unless you must delegate.",
                    allow_tools=False,
                )
                futures[executor.submit(self._run_agent, send.recipient, prompt, self._org.scatter_timeout)] = (index, send)
            for future in concurrent.futures.as_completed(futures):
                index, send = futures[future]
                try:
                    turn = future.result()
                except subprocess.TimeoutExpired as exc:
                    response = f"Timed out after {exc.timeout} seconds."
                    self._log(
                        "scatter_error",
                        from_agent=sender,
                        to_agent=send.recipient,
                        body=send.body,
                        reason=response,
                    )
                    results[index] = ScatterItem(send.recipient, send.body, False, response)
                except Exception as exc:
                    response = str(exc)
                    self._log(
                        "scatter_error",
                        from_agent=sender,
                        to_agent=send.recipient,
                        body=send.body,
                        reason=response,
                    )
                    results[index] = ScatterItem(send.recipient, send.body, False, response)
                else:
                    self._log(
                        "scatter_result",
                        from_agent=send.recipient,
                        to_agent=sender,
                        from_session_id=turn.session_id,
                        to_session_id=self._sessions.get(sender),
                        body=turn.response,
                    )
                    results[index] = ScatterItem(send.recipient, send.body, True, turn.response, turn)
        return [result for result in results if result is not None]

    def _log(self, event: str, **fields: object) -> None:
        if self._event_log is not None:
            if self._thread_id is not None:
                fields.setdefault("thread_id", self._thread_id)
            self._event_log.write(event, **fields)

    def _session_id_from_output(self, command: str, output: str) -> str:
        match = _SESSION_RE.search(output)
        if match is None:
            return self._latest_session_id(command)
        return match.group(1)

    def _latest_session_id(self, command: str) -> str:
        completed = subprocess.run(
            [command, "sessions", "list"],
            check=False,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            cwd=self._cwd,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{command} sessions list failed with exit code {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        match = re.search(r"\b(\d{8}_\d{6}_[0-9a-f]+)\b", completed.stdout)
        if match is None:
            raise RuntimeError(f"{command} sessions list did not include a session id:\n{completed.stdout}")
        return match.group(1)

    def _agent_lock(self, agent: str) -> object:
        return _AgentLock(self._cwd / ".hermes-link" / "locks" / f"{_safe_lock_name(agent)}.lock")

    def _agent_prompt(self, body: str, *, allow_tools: bool) -> str:
        agent_directory = self._agent_directory()
        if allow_tools:
            instructions = self._skill_text
        else:
            instructions = (
                "You are being called by Hermes Link as a routed recipient.\n"
                "Do not call tools. Do not call route_message.\n"
                "If you need to send the next message to another agent, output exactly:\n"
                "SEND agent_id: message\n"
                "If you need to contact multiple agents in parallel and wait for their replies, output exactly:\n"
                "SEND_ALL:\n"
                "- agent_id: message\n"
                "- agent_id: message\n"
                "If you are done, answer normally."
            )
        return (
            "Hermes Link org directory:\n"
            f"{agent_directory}\n\n"
            "Hermes Link org routing policy:\n"
            f"{self._routing_guidance()}\n\n"
            "Hermes Link routing instructions:\n"
            f"{instructions}\n\n"
            "User or routed message:\n"
            f"{body}"
        )

    def _agent_directory(self) -> str:
        lines = []
        for name in sorted(self._org.agents):
            agent = self._org.agents[name]
            detail = agent.expertise or "No expertise description provided."
            role = agent.title or name
            hierarchy = []
            if agent.team:
                hierarchy.append(f"team={agent.team}")
            if agent.manager:
                hierarchy.append(f"manager={agent.manager}")
            suffix = f" ({'; '.join(hierarchy)})" if hierarchy else ""
            lines.append(f"- {name}: {role}{suffix}. {detail}")
        for name in sorted(self._org.topics):
            topic = self._org.topics[name]
            members = ", ".join(topic.agents)
            lines.append(f"- @{name}: topic default {topic.default}; agents: {members}")
        return "\n".join(lines)

    def _routing_guidance(self) -> str:
        if self._org.routing.mode == "flat":
            return "Mode: flat. Any configured agent may contact any other configured agent."
        return (
            "Mode: strict_hierarchical. Contact agents above or below you in the manager hierarchy. "
            "You may also contact direct peers with the same manager. For cross-branch work, route "
            "through your manager instead of contacting unrelated agents directly."
        )

    def _resolve_agent(self, target: str) -> str:
        return self._org.resolve_agent(target)


def _clean_response(output: str) -> str:
    lines = [
        line
        for line in output.splitlines()
        if line.strip()
        and not line.startswith("session_id:")
        and "Resumed session " not in line
        and "tirith security scanner" not in line
    ]
    return "\n".join(lines).strip()


def _normalize_body(body: str) -> str:
    return " ".join(body.casefold().split())


def _format_scatter_results(items: list[ScatterItem]) -> str:
    lines = []
    for item in items:
        status = "replied" if item.ok else "failed"
        lines.append(f"- {item.recipient} {status}: {item.response}")
    return "\n".join(lines)


class _AgentLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._file = None

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("w", encoding="utf-8")
        fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self._file is None:
            return
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()


def _safe_lock_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _policy_denial(sender: str, recipient: str) -> str:
    return (
        "Hermes Link routing policy blocked this message: "
        f"{sender} is not allowed to send messages to {recipient}."
    )
