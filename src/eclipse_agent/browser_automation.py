"""Browser automation adapters for Eclipse.

The first implementation targets `agent-browser` as a dry-run-friendly command
adapter. It builds safe argv tuples, validates URLs, derives per-task domain
allowlists, and executes only when explicitly requested by the caller.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote_plus, urlparse

DEFAULT_AGENT_BROWSER_POLICY = Path("config/agent-browser-policy.json")
DEFAULT_SEARCH_URL = "https://www.google.com/search?q={query}"
SAFE_BROWSER_SCHEMES = {"http", "https"}
REF_PATTERN = re.compile(r"^@?e\d+$")


class BrowserCommandKind(StrEnum):
    """Supported browser command families."""

    OPEN_URL = "open_url"
    SEARCH = "search"
    SNAPSHOT = "snapshot"
    CLICK = "click"
    FILL = "fill"
    TYPE = "type"
    PRESS = "press"


class BrowserActionStatus(StrEnum):
    """Safety status for an interaction-loop step."""

    PREPARED = "prepared"
    BLOCKED = "blocked"
    FAILED = "failed"
    EXECUTED = "executed"


@dataclass(frozen=True)
class BrowserAutomationProfile:
    """Configuration for browser automation sessions."""

    backend: str = "agent-browser"
    binary: str = "agent-browser"
    session: str = "eclipse-mvp"
    action_policy: Path = DEFAULT_AGENT_BROWSER_POLICY
    default_allowed_domains: tuple[str, ...] = ("localhost", "127.0.0.1")
    search_url_template: str = DEFAULT_SEARCH_URL
    snapshot_flags: tuple[str, ...] = ("-i", "--json")
    batch_snapshot_flags: tuple[str, ...] = ("-i",)


@dataclass(frozen=True)
class BrowserAutomationRequest:
    """A browser automation request before it becomes a CLI command."""

    kind: BrowserCommandKind
    url: str | None = None
    query: str | None = None
    selector: str | None = None
    text: str | None = None
    key: str | None = None
    allowed_domains: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserAutomationResult:
    """Result of preparing or running a browser automation request."""

    success: bool
    kind: BrowserCommandKind
    command: tuple[str, ...]
    message: str
    dry_run: bool
    executed: bool = False
    pid: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class BrowserElement:
    """A single interactive/semantic element from agent-browser snapshot JSON."""

    ref: str
    role: str
    name: str


@dataclass(frozen=True)
class BrowserSnapshot:
    """Parsed agent-browser snapshot output."""

    origin: str
    elements: tuple[BrowserElement, ...]
    snapshot_text: str


@dataclass(frozen=True)
class BrowserInteractionStep:
    """A high-level browser interaction step with safety metadata."""

    kind: BrowserCommandKind
    description: str
    requires_confirmation: bool
    request: BrowserAutomationRequest


@dataclass(frozen=True)
class BrowserInteractionPlan:
    """Prepared browser interaction steps and their routing results."""

    steps: tuple[BrowserInteractionStep, ...]
    results: tuple[BrowserAutomationResult, ...]
    status: BrowserActionStatus
    message: str

    @property
    def requires_confirmation(self) -> bool:
        """Return whether any step needs explicit confirmation."""

        return any(step.requires_confirmation for step in self.steps)


class AgentBrowserAdapter:
    """Build and optionally execute safe `agent-browser` commands."""

    def __init__(self, profile: BrowserAutomationProfile | None = None) -> None:
        self.profile = profile or BrowserAutomationProfile()

    def open_url(
        self,
        url: str,
        *,
        dry_run: bool = True,
        allowed_domains: tuple[str, ...] = (),
    ) -> BrowserAutomationResult:
        """Open a URL in an agent-browser session."""

        request = BrowserAutomationRequest(
            kind=BrowserCommandKind.OPEN_URL,
            url=url,
            allowed_domains=allowed_domains,
        )
        return self.run(request, dry_run=dry_run)

    def search(
        self,
        query: str,
        *,
        dry_run: bool = True,
        allowed_domains: tuple[str, ...] = (),
    ) -> BrowserAutomationResult:
        """Open a web search in an agent-browser session."""

        url = self.profile.search_url_template.format(query=quote_plus(query))
        request = BrowserAutomationRequest(
            kind=BrowserCommandKind.SEARCH,
            url=url,
            query=query,
            allowed_domains=allowed_domains,
        )
        return self.run(request, dry_run=dry_run)

    def snapshot(
        self,
        url: str | None = None,
        *,
        dry_run: bool = True,
        allowed_domains: tuple[str, ...] = (),
    ) -> BrowserAutomationResult:
        """Request an interactive semantic page snapshot from agent-browser."""

        request = BrowserAutomationRequest(
            kind=BrowserCommandKind.SNAPSHOT,
            url=url,
            allowed_domains=allowed_domains,
        )
        return self.run(request, dry_run=dry_run)

    def click(
        self,
        selector: str,
        *,
        dry_run: bool = True,
        allowed_domains: tuple[str, ...] = (),
    ) -> BrowserAutomationResult:
        """Click an element ref from the latest snapshot."""

        request = BrowserAutomationRequest(
            kind=BrowserCommandKind.CLICK,
            selector=selector,
            allowed_domains=allowed_domains,
        )
        return self.run(request, dry_run=dry_run)

    def fill(
        self,
        selector: str,
        text: str,
        *,
        dry_run: bool = True,
        allowed_domains: tuple[str, ...] = (),
    ) -> BrowserAutomationResult:
        """Fill an element ref from the latest snapshot."""

        request = BrowserAutomationRequest(
            kind=BrowserCommandKind.FILL,
            selector=selector,
            text=text,
            allowed_domains=allowed_domains,
        )
        return self.run(request, dry_run=dry_run)

    def type_text(
        self,
        selector: str,
        text: str,
        *,
        dry_run: bool = True,
        allowed_domains: tuple[str, ...] = (),
    ) -> BrowserAutomationResult:
        """Type into an element ref without clearing it first."""

        request = BrowserAutomationRequest(
            kind=BrowserCommandKind.TYPE,
            selector=selector,
            text=text,
            allowed_domains=allowed_domains,
        )
        return self.run(request, dry_run=dry_run)

    def press(
        self,
        key: str,
        *,
        dry_run: bool = True,
        allowed_domains: tuple[str, ...] = (),
    ) -> BrowserAutomationResult:
        """Press a key in the current browser focus."""

        request = BrowserAutomationRequest(
            kind=BrowserCommandKind.PRESS,
            key=key,
            allowed_domains=allowed_domains,
        )
        return self.run(request, dry_run=dry_run)

    def run(
        self,
        request: BrowserAutomationRequest,
        *,
        dry_run: bool = True,
    ) -> BrowserAutomationResult:
        """Prepare or execute a browser automation request."""

        try:
            command = self.build_command(request)
        except ValueError as exc:
            return BrowserAutomationResult(
                success=False,
                kind=request.kind,
                command=(),
                message=str(exc),
                dry_run=dry_run,
            )

        if dry_run:
            return BrowserAutomationResult(
                success=True,
                kind=request.kind,
                command=command,
                message=f"Prepared {self.profile.backend} command.",
                dry_run=True,
                metadata=request.metadata,
            )

        if not shutil.which(self.profile.binary):
            return BrowserAutomationResult(
                success=False,
                kind=request.kind,
                command=command,
                message=f"Browser automation binary not found: {self.profile.binary}",
                dry_run=False,
                metadata=request.metadata,
            )

        completed = subprocess.run(  # noqa: S603
            command,
            text=True,
            capture_output=True,
            check=False,
        )
        return BrowserAutomationResult(
            success=completed.returncode == 0,
            kind=request.kind,
            command=command,
            message=(
                f"Executed {self.profile.backend} command."
                if completed.returncode == 0
                else completed.stderr.strip() or f"{self.profile.backend} command failed."
            ),
            dry_run=False,
            executed=completed.returncode == 0,
            metadata=request.metadata,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def build_command(self, request: BrowserAutomationRequest) -> tuple[str, ...]:
        """Build an argv tuple for a browser automation request."""

        allowed_domains = self._allowed_domains_for(request)
        command = list(self._base_command(allowed_domains))

        if request.kind in {BrowserCommandKind.OPEN_URL, BrowserCommandKind.SEARCH}:
            if not request.url:
                raise ValueError("Browser URL is required.")
            validate_browser_url(request.url)
            command.extend(("open", request.url))
            return tuple(command)

        if request.kind is BrowserCommandKind.SNAPSHOT:
            if request.url:
                validate_browser_url(request.url)
                return self.build_batch_command(
                    (f"open {request.url}", self._snapshot_command_text()),
                    allowed_domains=allowed_domains,
                )
            command.extend(("snapshot", *self.profile.snapshot_flags))
            return tuple(command)

        ref_action_kinds = {
            BrowserCommandKind.CLICK,
            BrowserCommandKind.FILL,
            BrowserCommandKind.TYPE,
        }
        if request.kind in ref_action_kinds:
            selector = validate_snapshot_ref(request.selector)
            command.append(request.kind.value)
            command.append(selector)
            if request.kind in {BrowserCommandKind.FILL, BrowserCommandKind.TYPE}:
                if request.text is None:
                    raise ValueError(f"Text is required for {request.kind.value}.")
                command.append(request.text)
            return tuple(command)

        if request.kind is BrowserCommandKind.PRESS:
            if not request.key:
                raise ValueError("Key is required for press.")
            command.extend(("press", request.key))
            return tuple(command)

        raise ValueError(f"Unsupported browser command: {request.kind}")

    def build_batch_command(
        self,
        command_texts: tuple[str, ...],
        *,
        allowed_domains: tuple[str, ...],
        bail: bool = True,
    ) -> tuple[str, ...]:
        """Build an agent-browser batch command from complete subcommands."""

        command = [*self._base_command(allowed_domains), "batch", "--json"]
        if bail:
            command.append("--bail")
        command.extend(command_texts)
        return tuple(command)

    def _base_command(self, allowed_domains: tuple[str, ...]) -> tuple[str, ...]:
        return (
            self.profile.binary,
            "--session",
            self.profile.session,
            "--allowed-domains",
            ",".join(allowed_domains),
            "--action-policy",
            str(self.profile.action_policy),
        )

    def _snapshot_command_text(self) -> str:
        return " ".join(("snapshot", *self.profile.batch_snapshot_flags))

    def _allowed_domains_for(self, request: BrowserAutomationRequest) -> tuple[str, ...]:
        domains = [*self.profile.default_allowed_domains, *request.allowed_domains]
        if request.url:
            domain = domain_from_url(request.url)
            if domain:
                domains.append(domain)
        return tuple(dict.fromkeys(domain for domain in domains if domain))


class BrowserInteractionLoop:
    """Prepare safe browser interaction loops around snapshot refs.

    This class deliberately does not choose refs on its own yet. The next layer will
    parse snapshot output or ask an LLM to choose a ref, then this loop will enforce
    confirmation before active interactions such as click/fill/type/press.
    """

    def __init__(self, adapter: AgentBrowserAdapter | None = None) -> None:
        self.adapter = adapter or AgentBrowserAdapter()

    def open_and_snapshot(
        self,
        url: str,
        *,
        dry_run: bool = True,
    ) -> BrowserInteractionPlan:
        """Open a URL and request an interactive JSON snapshot."""

        request = BrowserAutomationRequest(kind=BrowserCommandKind.SNAPSHOT, url=url)
        step = BrowserInteractionStep(
            kind=BrowserCommandKind.SNAPSHOT,
            description="Open URL and collect interactive semantic snapshot.",
            requires_confirmation=False,
            request=request,
        )
        result = self.adapter.run(request, dry_run=dry_run)
        return _plan_from_results((step,), (result,))

    def confirmed_ref_action(
        self,
        *,
        kind: BrowserCommandKind,
        selector: str | None = None,
        text: str | None = None,
        key: str | None = None,
        confirmed: bool = False,
        dry_run: bool = True,
    ) -> BrowserInteractionPlan:
        """Prepare a ref/key action, blocking active actions until confirmed."""

        if kind not in {
            BrowserCommandKind.CLICK,
            BrowserCommandKind.FILL,
            BrowserCommandKind.TYPE,
            BrowserCommandKind.PRESS,
        }:
            return BrowserInteractionPlan(
                steps=(),
                results=(),
                status=BrowserActionStatus.FAILED,
                message=f"Unsupported interaction kind: {kind}",
            )

        request = BrowserAutomationRequest(kind=kind, selector=selector, text=text, key=key)
        step = BrowserInteractionStep(
            kind=kind,
            description=f"Run active browser action: {kind.value}.",
            requires_confirmation=True,
            request=request,
        )
        if not confirmed:
            return BrowserInteractionPlan(
                steps=(step,),
                results=(),
                status=BrowserActionStatus.BLOCKED,
                message="Browser interaction requires explicit confirmation.",
            )

        result = self.adapter.run(request, dry_run=dry_run)
        return _plan_from_results((step,), (result,))


def _plan_from_results(
    steps: tuple[BrowserInteractionStep, ...],
    results: tuple[BrowserAutomationResult, ...],
) -> BrowserInteractionPlan:
    if all(result.success for result in results):
        if any(result.executed for result in results):
            status = BrowserActionStatus.EXECUTED
        else:
            status = BrowserActionStatus.PREPARED
        message = (
            "Browser interaction prepared."
            if status is BrowserActionStatus.PREPARED
            else "Browser interaction started."
        )
        return BrowserInteractionPlan(
            steps=steps,
            results=results,
            status=status,
            message=message,
        )
    return BrowserInteractionPlan(
        steps=steps,
        results=results,
        status=BrowserActionStatus.FAILED,
        message="Browser interaction failed to prepare.",
    )


def render_browser_interaction_plan(plan: BrowserInteractionPlan) -> str:
    """Render a browser interaction plan for CLI output."""

    lines = [f"Browser interaction: {plan.status.value}", plan.message]
    for step in plan.steps:
        confirmation = "requires confirmation" if step.requires_confirmation else "no confirmation"
        lines.append(f"- {step.kind.value}: {step.description} ({confirmation})")
    for result in plan.results:
        status = "executed" if result.executed else "prepared"
        if not result.success:
            status = "failed"
        lines.append(f"  result [{status}]: {result.message}")
        if result.command:
            lines.append(f"  command: {shlex_join(result.command)}")
        if result.stdout and result.kind is BrowserCommandKind.SNAPSHOT:
            try:
                snapshot = parse_agent_browser_snapshot_json(result.stdout)
            except (ValueError, json.JSONDecodeError):
                lines.append("  snapshot: unable to parse JSON output")
            else:
                lines.append(
                    f"  snapshot: {snapshot.origin} "
                    f"({len(snapshot.elements)} refs)"
                )
                for element in snapshot.elements[:8]:
                    lines.append(f"    - {element.ref} {element.role}: {element.name}")
    return "\n".join(lines)


def shlex_join(command: tuple[str, ...]) -> str:
    """Quote a command for display only."""

    import shlex

    return shlex.join(command)


def validate_browser_url(url: str) -> None:
    """Validate a URL before passing it to browser automation."""

    parsed = urlparse(url)
    if parsed.scheme not in SAFE_BROWSER_SCHEMES:
        raise ValueError(f"Unsupported browser URL scheme: {parsed.scheme or '<empty>'}")
    if not parsed.netloc:
        raise ValueError("Browser URL must include a hostname.")


def validate_snapshot_ref(selector: str | None) -> str:
    """Require snapshot refs for MVP browser interactions."""

    if not selector:
        raise ValueError("Snapshot ref is required.")
    if not REF_PATTERN.fullmatch(selector):
        raise ValueError("Only snapshot refs like @e1/e1 are allowed for MVP interactions.")
    return selector if selector.startswith("@") else f"@{selector}"


def parse_agent_browser_snapshot_json(raw_output: str) -> BrowserSnapshot:
    """Parse `agent-browser snapshot --json` output into stable objects."""

    payload = json.loads(raw_output)
    if isinstance(payload, list):
        snapshot_results = [
            item.get("result")
            for item in payload
            if item.get("success") and isinstance(item.get("result"), dict)
        ]
        data = next((item for item in reversed(snapshot_results) if "refs" in item), None)
        if data is None:
            raise ValueError("No snapshot result found in agent-browser batch output.")
        return _snapshot_from_data(data)

    if not payload.get("success"):
        error = payload.get("error") or "agent-browser snapshot failed"
        raise ValueError(str(error))
    data = payload.get("data") or {}
    return _snapshot_from_data(data)


def _snapshot_from_data(data: dict[str, object]) -> BrowserSnapshot:
    refs = data.get("refs") or {}
    elements = tuple(
        BrowserElement(
            ref=validate_snapshot_ref(ref),
            role=str(value.get("role", "")),
            name=str(value.get("name", "")),
        )
        for ref, value in refs.items()
    )
    return BrowserSnapshot(
        origin=str(data.get("origin", "")),
        elements=elements,
        snapshot_text=str(data.get("snapshot", "")),
    )


def domain_from_url(url: str) -> str:
    """Extract a lower-case hostname for domain allowlists."""

    parsed = urlparse(url)
    return (parsed.hostname or "").casefold()
