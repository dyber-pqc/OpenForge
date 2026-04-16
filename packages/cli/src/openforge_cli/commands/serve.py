"""openforge serve -- start the REST API server."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def serve(
    port: int = typer.Option(8000, "--port", "-p", help="Port to listen on."),
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Host to bind to."),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload for development."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of worker processes."),
) -> None:
    """Start the OpenForge REST API server.

    Examples:
        openforge serve
        openforge serve --port 8080 --host 127.0.0.1
        openforge serve --reload --workers 4
    """
    console.print(f"[bold]Starting OpenForge API server[/]")
    console.print(f"  host    : [green]{host}[/]")
    console.print(f"  port    : [green]{port}[/]")
    console.print(f"  workers : [green]{workers}[/]")
    console.print(f"  reload  : [green]{reload}[/]")
    console.print()

    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Error:[/] uvicorn not installed. "
            "Install with: [bold]pip install uvicorn[fastapi][/]"
        )
        raise typer.Exit(code=1)

    try:
        # Verify the API module can be imported
        from openforge_api.main import app as _  # noqa: F401
    except ImportError:
        console.print(
            "[red]Error:[/] openforge-api package not installed. "
            "Install with: [bold]pip install openforge-api[/]"
        )
        raise typer.Exit(code=1)

    console.print(f"[bold green]API available at http://{host}:{port}[/]")
    console.print(f"[bold green]Docs at http://{host}:{port}/docs[/]")
    console.print()

    uvicorn.run(
        "openforge_api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers,
    )
