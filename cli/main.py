#!/usr/bin/env python3
"""Shunya CLI — control plane for the Cekura-style QA platform."""

import json
import sys
import typer
from typing import Optional
from rich import print as rprint
from rich.table import Table
from rich.console import Console
from rich.panel import Panel

from . import client

app = typer.Typer(
    name="shunya",
    help="Control plane CLI for the Shunya voice agent QA platform.",
    no_args_is_help=True,
)
agents_app = typer.Typer(help="Manage agents", no_args_is_help=True)
tests_app = typer.Typer(help="Manage test runs", no_args_is_help=True)
calls_app = typer.Typer(help="Inspect calls", no_args_is_help=True)
scenarios_app = typer.Typer(help="Manage scenarios", no_args_is_help=True)

app.add_typer(agents_app, name="agents")
app.add_typer(tests_app, name="tests")
app.add_typer(calls_app, name="calls")
app.add_typer(scenarios_app, name="scenarios")

console = Console()


# ── Agents ──────────────────────────────────────────────────────────────────

@agents_app.command("list")
def agents_list():
    """List all agents."""
    data = client.get("/api/agents/")
    results = data.get("results", data) if isinstance(data, dict) else data
    t = Table("ID", "Name", "Created")
    t.columns[0].min_width = 36
    for a in results:
        t.add_row(a["id"], a["name"], a.get("created_at", "")[:10])
    console.print(t)


@agents_app.command("create")
def agents_create(
    name: str = typer.Argument(..., help="Agent name"),
    system_prompt: str = typer.Option(..., "--prompt", "-p", help="System prompt"),
):
    """Create a new agent."""
    a = client.post("/api/agents/", {"name": name, "system_prompt": system_prompt})
    rprint(Panel(f"[green]Created agent[/green]\nID: {a['id']}\nName: {a['name']}"))


@agents_app.command("show")
def agents_show(agent_id: str):
    """Show agent details."""
    a = client.get(f"/api/agents/{agent_id}/")
    rprint(a)


@agents_app.command("chat")
def agents_chat(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    message: str = typer.Argument(..., help="Message to send"),
    conversation_id: Optional[str] = typer.Option(None, "--conv", help="Continue existing conversation"),
):
    """Send a message to an agent and get a response."""
    payload = {"message": message}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    r = client.post(f"/api/agents/{agent_id}/chat/", payload)
    rprint(Panel(
        f"[bold]Agent:[/bold] {r['response']}\n\n"
        f"[dim]conversation_id: {r['conversation_id']} | latency: {r['ts_ms']}ms[/dim]"
    ))


@agents_app.command("connect")
def agents_connect(
    agent_id: str = typer.Argument(..., help="Agent ID"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the join link in your browser"),
):
    """Start the voice agent in a Daily room and join it to talk to the agent live.

    Provisions a Daily.co room, boots only the agent pipeline (no synthetic caller),
    and returns a pre-authed join link. Open it, unmute, and speak to the agent.
    Requires the pipecat voice server (:8001) to be running.
    """
    r = client.post(f"/api/agents/{agent_id}/connect/", {})
    join_url = r.get("observer_url") or r.get("room_url")
    rprint(Panel(
        f"[green]Agent is live.[/green] Open the link, unmute, and start talking.\n\n"
        f"[bold]🎙  Join:[/bold] [blue underline]{join_url}[/blue underline]\n"
        f"[dim]room: {r.get('room_name', r.get('room_url', ''))}[/dim]"
    ))
    if open_browser and join_url:
        import webbrowser
        webbrowser.open(join_url)


# ── Scenarios ────────────────────────────────────────────────────────────────

@scenarios_app.command("list")
def scenarios_list():
    """List all scenarios."""
    data = client.get("/api/scenarios/")
    results = data.get("results", data) if isinstance(data, dict) else data
    t = Table("Name", "Description", "Steps")
    for s in results:
        t.add_row(s["name"], (s.get("description") or "")[:60], str(len(s.get("steps") or [])))
    console.print(t)


@scenarios_app.command("show")
def scenarios_show(name: str):
    """Show a scenario's YAML content."""
    data = client.get("/api/scenarios/")
    results = data.get("results", data) if isinstance(data, dict) else data
    scenario = next((s for s in results if s["name"] == name), None)
    if not scenario:
        rprint(f"[red]Scenario '{name}' not found[/red]")
        raise typer.Exit(1)
    rprint(Panel(scenario.get("yaml_content", json.dumps(scenario, indent=2)), title=name))


# ── Tests ────────────────────────────────────────────────────────────────────

@tests_app.command("run")
def tests_run(
    agent_id: str = typer.Argument(..., help="Agent ID to test"),
    scenario: str = typer.Option(..., "--scenario", "-s", help="Scenario name"),
    mode: str = typer.Option("text", "--mode", "-m", help="text | audio"),
    wait: bool = typer.Option(False, "--wait", "-w", help="Poll until run completes"),
):
    """Trigger a test run for an agent."""
    run = client.post("/api/test-runs/", {"agent": agent_id, "scenario": scenario, "mode": mode})
    rprint(Panel(
        f"[green]Test run queued[/green]\n"
        f"ID: {run['id']}\nStatus: {run['status']}\nMode: {mode}"
    ))

    if wait:
        import time
        run_id = run["id"]
        observer_shown = False
        console.print("[dim]Polling for completion…[/dim]")
        for _ in range(60):
            time.sleep(3)
            r = client.get(f"/api/test-runs/{run_id}/")
            status = r.get("status")
            console.print(f"  status: {status}")
            # Print observer URL once it's available (set right after room provisioning)
            if not observer_shown and r.get("observer_url"):
                observer_shown = True
                console.print(
                    f"\n[bold]👁  Join to observe:[/bold] "
                    f"[blue underline]{r['observer_url']}[/blue underline]\n"
                )
            if status in ("completed", "failed"):
                _print_run_result(r)
                break
        else:
            console.print("[yellow]Timed out waiting. Check status manually.[/yellow]")


def _print_run_result(run: dict):
    status_color = "green" if run.get("status") == "completed" else "red"
    if run.get("observer_url") and run.get("status") == "running":
        console.print(
            f"[bold]👁  Join to observe:[/bold] "
            f"[blue underline]{run['observer_url']}[/blue underline]"
        )
    result = run.get("result")
    if not result:
        rprint(f"[{status_color}]Status: {run['status']} (no result yet)[/{status_color}]")
        return

    passed = "[green]PASS[/green]" if result.get("passed") else "[red]FAIL[/red]"
    rprint(Panel(
        f"Status: [{status_color}]{run['status']}[/{status_color}] | Result: {passed}\n\n"
        + _format_scores(result.get("scores", [])),
        title="Test Result"
    ))


def _format_scores(scores: list) -> str:
    if not scores:
        return "Judge scores pending…"
    lines = []
    for s in scores:
        bar = "█" * int(s["score"] * 10)
        status = "✓" if s["passed"] else "✗"
        lines.append(f"{status} {s['field']:<25} {bar:<10} {s['score']:.2f}  {s['reasoning']}")
    return "\n".join(lines)


@tests_app.command("run-all")
def tests_run_all(
    mode: str = typer.Option("text", "--mode", "-m", help="text | audio"),
    wait: bool = typer.Option(True, "--wait/--no-wait", "-w", help="Poll until all runs complete"),
    agent_filter: Optional[str] = typer.Option(None, "--agent", help="Only run scenarios for this agent name"),
    scenario_filter: Optional[str] = typer.Option(None, "--scenario", help="Only run this scenario"),
):
    """
    Run every scenario against its compatible agent(s).

    Scenarios with no 'agents' field in their YAML run against a default
    agent named 'demo_support_agent' (if one exists).

    The mapping is declared in each scenario YAML under the 'agents:' key.
    Omitting the key means the scenario is generic and runs against the
    default agent only.
    """
    import time

    # Fetch all agents (name → id)
    agents_data = client.get("/api/agents/")
    agents_list = agents_data.get("results", agents_data) if isinstance(agents_data, dict) else agents_data
    agent_by_name = {a["name"]: a["id"] for a in agents_list}

    if not agent_by_name:
        rprint("[red]No active agents found. Create or load agents first.[/red]")
        raise typer.Exit(1)

    # Fetch all scenarios
    scenarios_data = client.get("/api/scenarios/")
    scenarios_list = scenarios_data.get("results", scenarios_data) if isinstance(scenarios_data, dict) else scenarios_data

    # Build (agent_name, scenario_name) pairs from compatible_agents mapping
    pairs: list[tuple[str, str]] = []
    default_agent = "demo_support_agent"

    for s in scenarios_list:
        scenario_name = s["name"]
        if scenario_filter and scenario_name != scenario_filter:
            continue
        compatible = s.get("compatible_agents") or []
        targets = compatible if compatible else ([default_agent] if default_agent in agent_by_name else [])
        for agent_name in targets:
            if agent_filter and agent_name != agent_filter:
                continue
            if agent_name not in agent_by_name:
                rprint(f"[yellow]  Skipping '{scenario_name}' — agent '{agent_name}' not found[/yellow]")
                continue
            pairs.append((agent_name, scenario_name))

    if not pairs:
        rprint("[yellow]No matching agent-scenario pairs found.[/yellow]")
        raise typer.Exit(0)

    # Display the run plan
    plan_table = Table("Agent", "Scenario", "Mode", title="Run plan")
    for agent_name, scenario_name in pairs:
        plan_table.add_row(agent_name, scenario_name, mode)
    console.print(plan_table)
    console.print()

    # Dispatch all runs
    run_ids: list[tuple[str, str, str]] = []  # (run_id, agent_name, scenario_name)
    for agent_name, scenario_name in pairs:
        agent_id = agent_by_name[agent_name]
        try:
            run = client.post("/api/test-runs/", {"agent": agent_id, "scenario": scenario_name, "mode": mode})
            run_ids.append((run["id"], agent_name, scenario_name))
            console.print(f"  [green]Queued[/green]  {agent_name} × {scenario_name}  ({run['id'][:8]}…)")
        except client.ShunyaError as e:
            console.print(f"  [red]Failed to queue[/red]  {agent_name} × {scenario_name}: {e}")

    if not wait or not run_ids:
        return

    console.print(f"\n[dim]Polling {len(run_ids)} run(s) for completion…[/dim]\n")

    # Track state per run
    done: dict[str, dict] = {}
    pending = {rid: (agent, scenario) for rid, agent, scenario in run_ids}

    for _ in range(120):  # max ~6 minutes per poll cycle
        time.sleep(3)
        still_pending = {}
        for rid, (agent_name, scenario_name) in list(pending.items()):
            try:
                r = client.get(f"/api/test-runs/{rid}/")
            except client.ShunyaError:
                still_pending[rid] = (agent_name, scenario_name)
                continue
            status = r.get("status")
            if status in ("completed", "failed"):
                done[rid] = r
                console.print(f"  [dim]{rid[:8]}…[/dim]  {agent_name} × {scenario_name}  → {status}")
            else:
                still_pending[rid] = (agent_name, scenario_name)
        pending = still_pending
        if not pending:
            break
    else:
        console.print(f"\n[yellow]{len(pending)} run(s) still in progress — check manually.[/yellow]")

    # Summary table
    if done:
        console.print()
        summary = Table("Agent", "Scenario", "Status", "Pass", "Score", title="Results summary")
        for rid, (agent_name, scenario_name) in [(r, (a, s)) for r, a, s in run_ids if r in done]:
            r = done[rid]
            status = r.get("status", "")
            result = r.get("result")
            if result:
                passed = "[green]PASS[/green]" if result.get("passed") else "[red]FAIL[/red]"
                scores = result.get("scores", [])
                if scores:
                    avg = sum(sc["score"] for sc in scores) / len(scores)
                    score_str = f"{avg:.2f}"
                else:
                    score_str = "pending"
            else:
                passed = "—"
                score_str = "—"
            summary.add_row(agent_name, scenario_name, status, passed, score_str)
        console.print(summary)


@tests_app.command("list")
def tests_list(
    agent_id: Optional[str] = typer.Option(None, "--agent", help="Filter by agent ID"),
):
    """List recent test runs."""
    params = {}
    if agent_id:
        params["agent"] = agent_id
    data = client.get("/api/test-runs/", **params)
    results = data.get("results", data) if isinstance(data, dict) else data
    t = Table("ID", "Agent", "Scenario", "Mode", "Status", "Passed")
    t.columns[0].min_width = 36
    t.columns[1].min_width = 36
    t.columns[2].min_width = 36
    for r in results:
        passed = str(r.get("result", {}).get("passed", "—")) if r.get("result") else "—"
        t.add_row(
            r["id"],
            str(r.get("agent", "")),
            r.get("scenario", ""),
            r.get("mode", ""),
            r.get("status", ""),
            passed,
        )
    console.print(t)


@tests_app.command("show")
def tests_show(run_id: str):
    """Show details of a test run including judge scores."""
    r = client.get(f"/api/test-runs/{run_id}/")
    _print_run_result(r)


@tests_app.command("transcript")
def tests_transcript(
    run_id: str,
    raw: bool = typer.Option(False, "--raw", "-r", help="Show original DSL-annotated text"),
    no_color: bool = typer.Option(False, "--no-color", help="Plain text output"),
):
    """Print the conversation transcript from a test run."""
    r = client.get(f"/api/test-runs/{run_id}/")
    result = r.get("result")

    if not result:
        rprint("[yellow]No transcript yet — run may still be in progress.[/yellow]")
        raise typer.Exit(1)

    transcript = result.get("transcript", [])
    if not transcript:
        rprint("[yellow]Transcript is empty.[/yellow]")
        raise typer.Exit(0)

    scenario_id = r.get("scenario", "")
    passed = result.get("passed")
    verdict = "[green]PASS[/green]" if passed else "[red]FAIL[/red]"

    console.print(f"\n[bold]Test Run:[/bold] {run_id}  "
                  f"[bold]Result:[/bold] {verdict}\n")

    for i, turn in enumerate(transcript):
        speaker = turn["speaker"]
        text = turn.get("raw", turn["text"]) if raw else turn["text"]
        quirks = turn.get("quirks", [])
        latency = turn.get("ts_ms", 0)

        from rich.markup import escape as rescape
        safe_text = rescape(text)
        if no_color:
            quirk_note = f" [{', '.join(quirks)}]" if quirks else ""
            console.print(f"{speaker.upper()}{quirk_note}: {safe_text}")
        else:
            if speaker == "caller":
                label = "[bold cyan]CALLER[/bold cyan]"
                quirk_note = (
                    " [dim cyan]" + "  ".join(rescape(f"[{q}]") for q in quirks) + "[/dim cyan]"
                    if quirks else ""
                )
                console.print(f"{label}{quirk_note}")
                console.print(f"  [cyan]{safe_text}[/cyan]")
            else:
                label = "[bold green]AGENT[/bold green]"
                latency_note = f" [dim](~{latency}ms)[/dim]" if latency else ""
                console.print(f"{label}{latency_note}")
                console.print(f"  [green]{safe_text}[/green]")

        if i < len(transcript) - 1:
            console.print()

    if r.get("mode") == "audio":
        url = f"{client.BASE_URL}/recordings/{run_id}.wav"
        console.print(f"\n[bold]🔊 Recording:[/bold] [blue underline]{url}[/blue underline]")


@tests_app.command("audio")
def tests_audio(
    run_id: str,
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the recording in your browser"),
):
    """Print (and open) the audio recording link for an audio test run."""
    url = f"{client.BASE_URL}/recordings/{run_id}.wav"
    console.print(f"[bold]🔊 Recording:[/bold] [blue underline]{url}[/blue underline]")
    if open_browser:
        import webbrowser
        webbrowser.open(url)


# ── Calls ────────────────────────────────────────────────────────────────────

@calls_app.command("list")
def calls_list(
    agent_id: Optional[str] = typer.Option(None, "--agent", help="Filter by agent ID"),
):
    """List recent calls."""
    params = {}
    if agent_id:
        params["agent"] = agent_id
    data = client.get("/api/calls/", **params)
    results = data.get("results", data) if isinstance(data, dict) else data
    t = Table("ID", "Agent", "Source", "Status", "Started")
    t.columns[0].min_width = 36
    t.columns[1].min_width = 36
    for c in results:
        t.add_row(
            c["id"],
            str(c.get("agent", "")),
            c.get("source", ""),
            c.get("status", ""),
            (c.get("started_at") or "")[:16],
        )
    console.print(t)


@calls_app.command("transcript")
def calls_transcript(call_id: str):
    """Print a call's transcript."""
    data = client.get(f"/api/calls/{call_id}/transcript/")
    for turn in data.get("turns", []):
        speaker = turn["speaker"].upper()
        quirks = f" [{', '.join(turn['quirks'])}]" if turn.get("quirks") else ""
        rprint(f"[bold]{speaker}[/bold]{quirks}: {turn['text']}")


@calls_app.command("metrics")
def calls_metrics(call_id: str):
    """Show metrics for a call."""
    data = client.get(f"/api/calls/{call_id}/metrics/")
    t = Table("Metric", "Value")
    for m in data:
        t.add_row(m["name"], str(round(m["value"], 2)))
    console.print(t)


def main():
    """Entry point that renders ShunyaError without a traceback."""
    try:
        app()
    except client.ShunyaError as e:
        rprint(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
