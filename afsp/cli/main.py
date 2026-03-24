"""AFSP CLI — Click-based command line interface."""

import json
import os
import sys

import click
import requests
import yaml

RUNTIME_URL = os.environ.get("AFSP_RUNTIME_URL", "http://localhost:8000")
OPERATOR_TOKEN = os.environ.get("AFSP_OPERATOR_TOKEN", "")
AGENTS_PATH = os.environ.get("AFSP_AGENTS_PATH", "/var/afsp/agents")


def _headers():
    return {"Authorization": f"Bearer {OPERATOR_TOKEN}"}


def _api(method, path, **kwargs):
    url = f"{RUNTIME_URL}{path}"
    resp = getattr(requests, method)(url, headers=_headers(), **kwargs)
    if resp.status_code >= 400:
        click.echo(f"Error {resp.status_code}: {resp.text}", err=True)
        sys.exit(1)
    return resp.json()


@click.group()
def cli():
    """AFSP — Agent File Scope Protocol CLI."""
    pass


@cli.command()
@click.argument("name")
def push(name):
    """Deploy agent from afsp.yml in agents/{name}/."""
    yml_path = os.path.join(AGENTS_PATH, name, "afsp.yml")
    if not os.path.exists(yml_path):
        click.echo(f"No afsp.yml found at {yml_path}", err=True)
        sys.exit(1)

    with open(yml_path) as f:
        config = yaml.safe_load(f)

    # Create agent
    agent = _api("post", "/v1/agents", json={
        "org_id": config.get("org_id", "default"),
        "name": config["name"],
        "role": config.get("role"),
    })
    agent_id = agent["agent_id"]
    click.echo(f"Agent created: {agent_id}")

    # Declare view
    view_entries = config.get("view", [])
    if view_entries:
        _api("post", f"/v1/view/{agent_id}", json=view_entries)
        click.echo(f"View declared: {len(view_entries)} entries")

    # Show client secret (one-time display)
    if agent.get("client_secret"):
        click.echo(f"Client secret: {agent['client_secret']}")
        click.echo("(This secret is single-use and will not be shown again)")


@cli.command()
@click.argument("name")
def start(name):
    """Start agent container."""
    click.echo(f"Starting agent {name}...")
    click.echo("Note: Container management requires Docker integration (not yet implemented)")


@cli.command()
@click.argument("name")
def stop(name):
    """Stop agent container."""
    click.echo(f"Stopping agent {name}...")
    click.echo("Note: Container management requires Docker integration (not yet implemented)")


@cli.command()
@click.argument("name")
def suspend(name):
    """Immediately revoke all sessions and suspend agent."""
    # Find agent by name
    # For MVP, we need to look up the agent_id from the name
    # Try the API — inspect by querying agents
    click.echo(f"Suspending agent {name}...")

    # Read credentials file to get agent_id
    cred_path = os.path.join(AGENTS_PATH, name, ".credentials")
    if os.path.exists(cred_path):
        agent_id = None
        with open(cred_path) as f:
            for line in f:
                if line.startswith("AFSP_AGENT_ID="):
                    agent_id = line.strip().split("=", 1)[1]
        if agent_id:
            result = _api("patch", f"/v1/agents/{agent_id}/suspend")
            click.echo(f"Agent {agent_id} suspended. All sessions revoked.")
            return

    click.echo(f"Could not find agent_id for {name}. Provide the full agent_id.", err=True)
    sys.exit(1)


@cli.command()
@click.argument("name")
def inspect(name):
    """Show agent identity and status."""
    cred_path = os.path.join(AGENTS_PATH, name, ".credentials")
    if not os.path.exists(cred_path):
        click.echo(f"No credentials found for {name}", err=True)
        sys.exit(1)

    agent_id = None
    with open(cred_path) as f:
        for line in f:
            if line.startswith("AFSP_AGENT_ID="):
                agent_id = line.strip().split("=", 1)[1]

    if not agent_id:
        click.echo(f"Could not parse agent_id for {name}", err=True)
        sys.exit(1)

    agent = _api("get", f"/v1/agents/{agent_id}")
    click.echo(f"Agent ID:  {agent['agent_id']}")
    click.echo(f"Name:      {agent['name']}")
    click.echo(f"Org:       {agent['org_id']}")
    click.echo(f"Role:      {agent.get('role', '-')}")
    click.echo(f"Status:    {agent['status']}")


@cli.command()
@click.argument("name")
def view(name):
    """Show exactly what the agent currently perceives."""
    cred_path = os.path.join(AGENTS_PATH, name, ".credentials")
    if not os.path.exists(cred_path):
        click.echo(f"No credentials found for {name}", err=True)
        sys.exit(1)

    agent_id = None
    with open(cred_path) as f:
        for line in f:
            if line.startswith("AFSP_AGENT_ID="):
                agent_id = line.strip().split("=", 1)[1]

    if not agent_id:
        click.echo(f"Could not parse agent_id for {name}", err=True)
        sys.exit(1)

    entries = _api("get", f"/v1/view/{agent_id}")

    if not entries:
        click.echo(f"Agent {name} ({agent_id}) has an empty view — sees nothing.")
        return

    click.echo(f"View for {name} ({agent_id}):")
    click.echo()
    for entry in entries:
        ops_str = ", ".join(entry["ops"])
        source = entry.get("source", "static")
        line = f"  {entry['path']}  [{ops_str}]"
        if entry.get("flags"):
            line += f"  flags={entry['flags']}"
        if source == "sgt":
            expires = entry.get("expires_at", "?")
            line += f"  (SGT — expires {expires})"
        click.echo(line)


@cli.command()
@click.argument("name")
def logs(name):
    """Stream agent logs."""
    click.echo(f"Streaming logs for {name}...")
    click.echo("Note: Log streaming requires container integration (not yet implemented)")


@cli.command("token-issue")
@click.option("--grantor", required=True, help="Grantor agent ID")
@click.option("--grantee", required=True, help="Grantee agent ID")
@click.option("--path", required=True, help="Path to grant access to")
@click.option("--ops", required=True, help="Comma-separated operations (read,write)")
@click.option("--ttl", default=3600, help="Time to live in seconds")
@click.option("--single-use", is_flag=True, help="Token can only be used once")
def token_issue(grantor, grantee, path, ops, ttl, single_use):
    """Issue a scope grant token."""
    ops_list = [o.strip() for o in ops.split(",")]
    result = _api("post", "/v1/tokens", json={
        "grantor": grantor,
        "grantee": grantee,
        "path": path,
        "ops": ops_list,
        "ttl": ttl,
        "single_use": single_use,
    })
    click.echo(f"Token issued: {result['token_id']}")
    click.echo(f"  Path:       {result['path']}")
    click.echo(f"  Ops:        {', '.join(result['ops'])}")
    click.echo(f"  Expires:    {result['expires_at']}")
    click.echo(f"  Single-use: {result['single_use']}")


@cli.command()
@click.option("--agent", default=None, help="Filter by agent ID")
def audit(agent):
    """Query audit log."""
    params = {}
    if agent:
        params["agent_id"] = agent

    entries = _api("get", "/v1/audit", params=params)

    if not entries:
        click.echo("No audit entries found.")
        return

    for entry in entries:
        outcome = "ALLOWED" if entry["outcome"] == "allowed" else "DENIED"
        token_info = f" token={entry['token_id']}" if entry.get("token_id") else ""
        click.echo(
            f"[{entry['timestamp']}] {outcome} {entry['agent_id']} "
            f"{entry['op']} {entry['path']}{token_info}"
        )
