
"""SKY Command Line Interface."""

import asyncio
import os
import sys
from pathlib import Path

# Force UTF-8 encoding for stdout on Windows to prevent UnicodeEncodeError
if sys.platform == "win32":
    try:
        import ctypes
        # Set Windows console to UTF-8 (65001)
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass

if sys.stdout.encoding != "utf-8" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import typer
from rich.console import Console

from sky import __version__

app = typer.Typer(help="SKY - Local CLI-based agentic software development assistant")
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"SKY CLI Version: {__version__}")
        raise typer.Exit()

def _handle_error(e):
    if "GROQ_API_KEY" in str(e):
        return "🔑 Missing GROQ_API_KEY. Run 'sky init'."
    if "NVIDIA_NIM_API_KEY" in str(e):
        return "🔑 Missing NVIDIA_NIM_API_KEY. Run 'sky init'."
    if "models.yaml" in str(e):
        return "⚠️ Configuration error. Run 'sky init --force'."
    return f"Error: {e}"


@app.callback()
def main(
    version: bool = typer.Option(None, "--version", callback=version_callback, is_eager=True, help="Show version."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose output.")
) -> None:
    """
    ☁️ Sky — Build without boundaries.

    Commands:
      chat       Start conversational chat with Sky
      ask        Ask a question (read-only)
      plan       Create a structured plan
      agent      Run agent mode with tools
      workflow   Run multi-step workflow
      init       Interactive setup
      index      Index repository
      context    Semantic search
      stats      Show usage statistics
      sessions   List sessions
      audit      Show audit log
    """
    pass


async def _run_loop(mode: str, prompt: str, inject_context: bool = False, quiet: bool = False, verbose: bool = False, max_turns: int = 20):
    from dotenv import load_dotenv
    from sky.config.schema import get_config_dir
    load_dotenv(get_config_dir() / ".env", override=True)
    
    from sky.config import load_config, load_models_config
    from sky.core.approval import ApprovalGate
    from sky.core.fast_loop import FastLoopEngine
    from sky.core.router import ModelRouter
    from sky.storage import get_db
    from sky.errors import SkyError
    import pydantic
    
    try:
        config = load_config()
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in sky.yaml or .env[/bold red]")
        console.print("[yellow]Please run 'sky init' to regenerate your configuration.[/yellow]")
        raise typer.Exit(1)
        
    if verbose:
        config.verbose = True
        
    if getattr(config, "security_enabled", True):
        from sky.security.rate_limit import get_rate_limiter
        from sky.security import get_security_guardrails
        
        rate_limiter = get_rate_limiter()
        if not rate_limiter.is_allowed("cli_user"):
            console.print("[bold red]Rate limit exceeded. Please wait before making more requests.[/bold red]")
            raise typer.Exit(1)
            
        guardrails = get_security_guardrails()
        guardrails.strict_mode = getattr(config, "security_strict_mode", True)
        
        is_safe, sanitized_prompt, warning = guardrails.process_user_input(prompt)
        if not is_safe:
            console.print("\n[bold red]🔒 Security Violation Detected[/bold red]")
            console.print("─────────────────────────────────────────")
            if guardrails.violations:
                latest = guardrails.violations[-1]
                console.print(f"  [bold]Category:[/bold] {latest[0]}")
                console.print(f"  [bold]Pattern:[/bold] {latest[1]}")
            console.print("\n  [bold red]Your request was blocked to protect your system.[/bold red]")
            console.print(f"  Reason: {warning}")
            console.print("─────────────────────────────────────────")
            console.print("  [dim][Log] Security event recorded in audit log[/dim]\n")
            raise typer.Exit(1)
            
        prompt = sanitized_prompt
        
    try:
        models = load_models_config()
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in models.yaml.[/bold red]")
        console.print("[yellow]Please run 'sky init' to regenerate it.[/yellow]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("\n[bold red]⚠️ Configuration file not found.[/bold red]")
        console.print("[yellow]Please run 'sky init' to create it.[/yellow]")
        raise typer.Exit(1)
        
    db = get_db()
    session_id = db.create_session(mode, prompt)
    
    router = ModelRouter(models, db, session_id)
    approval_gate = ApprovalGate(config, db, session_id)
    
    indexer = None
    if getattr(config, "memory_enabled", False):
        try:
            from sky.memory import get_vector_store, get_indexer
            vector_store = get_vector_store(Path.home() / ".sky" / "lancedb", config.memory_model)
            indexer = get_indexer(config, db, vector_store)
            if getattr(config, "memory_auto_index", False) and not quiet:
                console.print("[dim]Checking repository index...[/dim]")
                indexer.index_directory(Path.cwd())
        except Exception as e:
            if not quiet:
                console.print(f"[bold yellow]Warning: Memory initialization failed: {e}[/bold yellow]")
            
    engine = FastLoopEngine(config, db, router, session_id, approval_gate=approval_gate, indexer=indexer)
    
    messages = [{"role": "user", "content": prompt}]
    db.append_message(session_id, "user", prompt)
    
    if not quiet:
        console.print(f"[bold green]Starting {mode.upper()} mode...[/bold green] (Session: {session_id})")
    
    try:
        if not quiet:
            with console.status("[bold cyan]Thinking...[/bold cyan]", spinner="dots") as status:
                async for event in engine.run(messages, mode, inject_context=inject_context, max_turns=max_turns):
                    if event["type"] == "model_response":
                        if event["message"].get("content"):
                            from rich.markdown import Markdown
                            status.stop()
                            console.print(Markdown(event["message"]["content"]))
                            status.start()
                    elif event["type"] == "tool_results":
                        for res in event["results"]:
                            status.stop()
                            console.print(f"[dim]Tool {res.get('name', 'unknown')} completed.[/dim]")
                            status.start()
                    elif event["type"] == "waiting":
                        status.stop()
                        # We do NOT restart the status here. It will restart on the next event if needed, or remain stopped for input.
                    elif event["type"] == "error":
                        status.stop()
                        console.print(f"[bold red]Error:[/bold red] {event['content']}")
                        status.start()
        else:
            # Quiet mode: consume events but don't print unless error or final answer
            async for event in engine.run(messages, mode, inject_context=inject_context, max_turns=max_turns):
                if event["type"] == "final_answer":
                    print(event.get("content", ""))
                elif event["type"] == "error":
                    print(f"Error: {event['content']}", file=sys.stderr)
                    
        db.update_session_status(session_id, "completed")
    except SkyError as e:
        if not quiet:
            console.print(f"[bold red]Error ({e.code}):[/bold red] {e.message}")
            if e.suggestion:
                console.print(f"[bold yellow]Suggestion:[/bold yellow] {e.suggestion}")
        else:
            print(f"Error: {e.message}", file=sys.stderr)
        db.update_session_status(session_id, "failed")
    except Exception as e:
        if not quiet:
            console.print(f"[bold red]Execution failed:[/bold red] {e}")
        else:
            print(f"Execution failed: {e}", file=sys.stderr)
        db.update_session_status(session_id, "failed")


from typing import Optional

@app.command("chat")
def chat(
    prompt: Optional[str] = typer.Argument(None, help="Initial message (optional)"),
    model: Optional[str] = typer.Option(None, "--model", help="Override model for chat"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """
    Start a conversational chat with Sky.

    Examples:
      sky chat
      sky chat "Who built you?"
      sky chat "What can you do?"
      sky chat "Help me plan a feature"

    In chat mode, Sky will:
      - Introduce itself as Sky (not ChatGPT)
      - Share information about its creator when asked
      - Answer questions about its capabilities
      - Suggest the right command for your task
      - Redirect to /ask, /agent, /workflow when appropriate

    Created by Aaditya A (AI/ML Intern at CoRover.ai)
    """
    from sky.config import load_config, load_models_config
    from sky.storage import get_db
    from sky.core.router import ModelRouter
    from sky.core.chat import ChatEngine
    from dotenv import load_dotenv
    from sky.config.schema import get_config_dir
    import pydantic
    
    load_dotenv(get_config_dir() / ".env", override=True)
    try:
        config = load_config()
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in sky.yaml or .env[/bold red]")
        console.print("[yellow]Please run 'sky init' to regenerate your configuration.[/yellow]")
        raise typer.Exit(1)
        
    try:
        models_config = load_models_config()
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in models.yaml.[/bold red]")
        console.print("[yellow]Please run 'sky init' to regenerate it.[/yellow]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("\n[bold red]⚠️ Configuration file not found.[/bold red]")
        console.print("[yellow]Please run 'sky init' to create it.[/yellow]")
        raise typer.Exit(1)
    
    if verbose:
        config.verbose = True
        
    db = get_db()
    session_id = db.create_session("chat", prompt or "conversation")
    router = ModelRouter(models_config, db, session_id)
    
    engine = ChatEngine(config, models_config, db, router)
    engine.run(prompt)


@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Your question"),
    context: bool = typer.Option(False, "--context", help="Inject semantic context from indexed repository"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Quiet mode (minimal output)")
) -> None:
    """
    Ask Sky a question in read-only mode.

    Examples:
      sky ask "What does FastLoopEngine do?"
      sky ask --context "Explain the approval gate"
    """
    asyncio.run(_run_loop("ask", prompt, inject_context=context, quiet=quiet, verbose=verbose))


@app.command()
def agent(
    prompt: str = typer.Argument(..., help="Your request"),
    context: bool = typer.Option(False, "--context", help="Inject semantic context from indexed repository"),
    workflow: bool = typer.Option(False, "--workflow", help="Enable workflow visualization"),
    max_turns: int = typer.Option(20, "--max-turns", help="Max conversation turns"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Quiet mode")
) -> None:
    """
    Run Sky in agent mode with full tool access.

    Examples:
      sky agent "Fix the bug in approval.py"
      sky agent --workflow "Add authentication"
    """
    asyncio.run(_run_loop("agent", prompt, inject_context=context, quiet=quiet, verbose=verbose, max_turns=max_turns))


@app.command()
def plan(prompt: str) -> None:
    """Planning mode to produce a structured plan."""
    asyncio.run(_run_loop("plan", prompt))


@app.command()
def stats() -> None:
    """Show database statistics and usage."""
    from sky.storage import get_db
    db = get_db()
    stats = db.get_total_usage()
    console.print("[bold blue]Stats[/bold blue]")
    console.print(f"Total sessions: {stats['total_sessions']}")
    console.print(f"Total cost: ${stats['total_cost']:.4f}")


@app.command()
def audit(session_id: str) -> None:
    """View session audit logs."""
    from sky.storage import get_db
    db = get_db()
    logs = list(db.get_audit_log(session_id))
    console.print(f"[bold cyan]Audit Log for {session_id}[/bold cyan]")
    for log in logs:
        console.print(log)


@app.command()
def sessions() -> None:
    """List recent sessions."""
    from sky.storage import get_db
    db = get_db()
    sessions = db.list_sessions(limit=10)
    for s in sessions:
        console.print(f"- {s.id} | {s.mode} | {s.status}")


@app.command()
def resume(session_id: str) -> None:
    """Resume an interrupted session."""
    console.print(f"Resuming {session_id} not fully implemented in stub.")


@app.command("check-tools")
def check_tools() -> None:
    """List all registered tools available to SKY."""
    from sky.tools.registry import get_tool_schemas, get_tool
    from sky.config import load_config
    from sky.storage import get_db
    from sky.memory import get_vector_store, get_indexer
    
    schemas = get_tool_schemas()
    console.print(f"[bold cyan]Registered Tools ({len(schemas)})[/bold cyan]")
    for schema in schemas:
        name = schema["function"]["name"]
        tool_def = get_tool(name)
        risk = tool_def.risk_tier.name if tool_def else "UNKNOWN"
        console.print(f"- [bold]{name}[/bold] (Risk: [yellow]{risk}[/yellow])")
        
    config = load_config()
    db = get_db()
    if getattr(config, "memory_enabled", False):
        try:
            vector_store = get_vector_store(Path.home() / ".sky" / "lancedb", config.memory_model)
            indexer = get_indexer(config, db, vector_store)
            stats = indexer.get_stats()
            console.print("\n[bold cyan]Memory Status[/bold cyan]")
            console.print(f"Status: [green]Enabled[/green]")
            console.print(f"Indexed Files: {stats.get('total_files', 0)}")
            console.print(f"Total Chunks: {stats.get('total_chunks', 0)}")
        except Exception as e:
            console.print(f"\n[bold cyan]Memory Status[/bold cyan]")
            console.print(f"Status: [yellow]Error ({e})[/yellow]")
    else:
        console.print("\n[bold cyan]Memory Status[/bold cyan]")
        console.print("Status: [dim]Disabled[/dim]")

@app.command("index")
def index_repo(
    force: bool = typer.Option(False, "--force", help="Force re-index all files"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress")
) -> None:
    """
    Index repository for semantic search.

    Examples:
      sky index          # Index current repo
      sky index --force  # Force re-index all files
      sky index --verbose  # Show progress
    """
    from sky.config import load_config
    from sky.storage import get_db
    from sky.memory import VectorStoreManager, RepoIndexer, get_vector_store
    
    config = load_config()
    db = get_db()
    
    if not getattr(config, "memory_enabled", False):
        console.print("[bold red]Error: Memory is disabled in configuration.[/bold red]")
        raise typer.Exit(1)
        
    try:
        vector_store = get_vector_store(Path.home() / ".sky" / "lancedb", config.memory_model)
        if force:
            console.print("[yellow]Clearing existing vector store...[/yellow]")
            vector_store.clear()
            
        indexer = RepoIndexer(config, db, vector_store)
        
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Indexing repository...", total=None)
            
            def update_progress(msg: str):
                progress.update(task, description=f"[cyan]Indexing: {msg}")
                
            stats = indexer.index_directory(Path.cwd(), progress_callback=update_progress if verbose else None)
            
        console.print("[bold green]Indexing Complete![/bold green]")
        console.print(f"Files Indexed: {stats.get('indexed', 0)}")
        console.print(f"Files Skipped (unchanged/binary): {stats.get('skipped', 0)}")
        console.print(f"Errors: {stats.get('errors', 0)}")
        console.print(f"Deleted Files Pruned: {stats.get('pruned', 0)}")
        console.print("[dim]Embeddings generated locally (free)[/dim]")
    except Exception as e:
        console.print(f"[bold red]Indexing failed: {e}[/bold red]")

@app.command("context")
def search_context_cmd(query: str, top_k: int = typer.Option(5, "--top-k", help="Number of results")) -> None:
    """Search the indexed repository."""
    from sky.config import load_config
    from sky.memory import VectorStoreManager, get_vector_store
    
    config = load_config()
    if not getattr(config, "memory_enabled", False):
        console.print("[bold red]Error: Memory is disabled in configuration.[/bold red]")
        raise typer.Exit(1)
        
    try:
        vector_store = get_vector_store(Path.home() / ".sky" / "lancedb", config.memory_model)
        results = vector_store.search(query, top_k=top_k)
        
        from rich.table import Table
        if not results:
            console.print("[yellow]No relevant context found.[/yellow]")
            return
            
        console.print(f"[bold green]Found {len(results)} context chunks:[/bold green]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Score", style="cyan", width=6)
        table.add_column("File Path", style="green", width=30)
        table.add_column("Snippet", style="dim")
        
        for res in results:
            score = res.get("score", 0.0)
            path = res.get("file_path", "")
            snippet = res.get("content", "").replace("\n", " ")[:60] + "..."
            table.add_row(f"{score:.2f}", path, snippet)
            
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Search failed: {e}[/bold red]")

from typing import Optional

async def run_workflow_with_display(engine, goal: str, max_retries: int, resume: Optional[str] = None, quiet: bool = False):
    from rich.markdown import Markdown
    from sky.errors import SkyError
    
    # State tracking
    result = {}
    
    try:
        if quiet:
            async for event in engine.run_streaming(goal, max_retries=max_retries, resume_from=resume):
                if event.get("type") == "complete":
                    print(event.get("summary", ""))
                    result = event
                elif event.get("type") == "error":
                    print(f"Error: {event.get('content')}", file=sys.stderr)
                    result = event
            return result

        with console.status("[bold cyan]Thinking...[/bold cyan]", spinner="dots") as status:
            async for event in engine.run_streaming(goal, max_retries=max_retries, resume_from=resume):
                event_type = event.get("type")
                
                if event_type == "step":
                    status.stop()
                    console.print(f"  [cyan]{event['message']}[/cyan]")
                    status.start()
                    
                elif event_type == "step_complete":
                    status.stop()
                    console.print(f"  [green] {event['step']}: Done[/green]")
                    if "result" in event:
                        res_str = str(event['result'])
                        if len(res_str) > 200:
                            res_str = res_str[:197] + "..."
                        console.print(f"    [dim]{res_str}[/dim]")
                    status.start()
                    
                elif event_type == "subagent_start":
                    status.stop()
                    console.print(f"  [bold magenta] {event['role']}: {event['task']}[/bold magenta]")
                    status.start()
                    
                elif event_type == "subagent_complete":
                    status.stop()
                    console.print(f"  [bold green] {event['role']} complete[/bold green]")
                    if "summary" in event and event["summary"]:
                        res_str = str(event['summary'])
                        if len(res_str) > 200:
                            res_str = res_str[:197] + "..."
                        console.print(f"    [dim]{res_str}[/dim]")
                    status.start()
                    
                elif event_type == "tool_call":
                    status.stop()
                    args_str = str(event.get('args', ''))
                    if len(args_str) > 200:
                        args_str = args_str[:197] + "..."
                    console.print(f"    [dim] Calling: {event['tool_name']}({args_str})[/dim]")
                    status.start()
                    
                elif event_type == "tool_result":
                    status.stop()
                    res_str = str(event.get('result', ''))
                    if len(res_str) > 200:
                        res_str = res_str[:197] + "..."
                    console.print(f"    [dim]   {event.get('tool_name', 'tool')} completed: {res_str}[/dim]")
                    status.start()
                    
                elif event_type == "waiting":
                    status.stop()
                    
                elif event_type == "error":
                    status.stop()
                    console.print(f"  [bold red]Error:[/bold red] {event.get('content')}")
                    status.start()
                    
                elif event_type == "complete":
                    status.stop()
                    console.print(f"\n[bold green]Workflow Complete![/bold green]")
                    if "summary" in event:
                        console.print(Markdown(event["summary"]))
                    result = event
                    status.start()
    except SkyError as e:
        if not quiet:
            console.print(f"\n[bold red]Error ({e.code}):[/bold red] {e.message}")
            if e.suggestion:
                console.print(f"[bold yellow]Suggestion:[/bold yellow] {e.suggestion}")
        else:
            print(f"Error: {e.message}", file=sys.stderr)
    except Exception as e:
        if not quiet:
            console.print(f"\n[bold red]Workflow crashed:[/bold red] {e}")
        else:
            print(f"Workflow crashed: {e}", file=sys.stderr)
        
    return result

@app.command("workflow")
def workflow(
    goal: str = typer.Argument(..., help="The goal to achieve"),
    max_retries: int = typer.Option(3, "--max-retries", help="Maximum retry attempts"),
    resume: Optional[str] = typer.Option(None, "--resume", help="Session ID to resume"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Quiet mode")
) -> None:
    """
    Run a multi-step workflow with subagents.

    Examples:
      sky workflow "Add a docstring to approval.py"
      sky workflow --resume <session_id> "Continue"
    """
    from sky.config import load_config, load_models_config
    from sky.core.approval import ApprovalGate
    from sky.core.router import ModelRouter
    from sky.storage import get_db
    from dotenv import load_dotenv
    from sky.config.schema import get_config_dir
    import pydantic
    load_dotenv(get_config_dir() / ".env", override=True)
    
    if not quiet:
        console.print(f"[bold blue]Starting WORKFLOW mode...[/bold blue]")
        console.print(f"Goal: {goal}\n")
    
    # Load config
    try:
        config = load_config()
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in sky.yaml or .env[/bold red]")
        console.print("[yellow]Please run 'sky init' to regenerate your configuration.[/yellow]")
        raise typer.Exit(1)
        
    try:
        models_config = load_models_config()
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in models.yaml.[/bold red]")
        console.print("[yellow]Please run 'sky init' to regenerate it.[/yellow]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("\n[bold red]⚠️ Configuration file not found.[/bold red]")
        console.print("[yellow]Please run 'sky init' to create it.[/yellow]")
        raise typer.Exit(1)
        
    if verbose:
        config.verbose = True
        
    # Initialize components
    db = get_db()
    session_id = resume if resume else db.create_session("workflow", goal)
    router = ModelRouter(models_config, db, session_id)
    approval_gate = ApprovalGate(config, db, session_id)
    
    # Initialize memory if enabled
    indexer = None
    if config.memory_enabled:
        from sky.memory.vectorstore import get_vector_store
        from sky.memory.indexer import RepoIndexer
        vector_store = get_vector_store(Path.cwd() / ".sky" / "vectors")
        indexer = RepoIndexer(config, db, vector_store)
    
    # Initialize workflow engine (Lazy import to preserve < 150ms startup)
    from sky.core.workflow import WorkflowEngine
    engine = WorkflowEngine(
        config=config,
        db=db,
        router=router,
        approval_gate=approval_gate,
        indexer=indexer,
    )
    
    import asyncio
    asyncio.run(run_workflow_with_display(engine, goal, max_retries, resume, quiet=quiet))


@app.command("init")
def init(
    provider: str = typer.Option(None, "--provider", help="Provider: groq, nim, hybrid"),
    global_install: bool = typer.Option(False, "--global", help="Install globally (~/.sky/)"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing config")
):
    """
    Interactive setup for Sky.

    Examples:
      sky init           # Interactive setup
      sky init --provider groq  # Quick setup with Groq
      sky init --force   # Overwrite existing configuration
    """
    from pathlib import Path
    import subprocess
    from rich.prompt import Prompt
    
    console.print("[bold blue]Initializing SKY Project...[/bold blue]")
    
    # 1. Ask for NIM API Key
    nim_key = console.input("Enter your NVIDIA NIM API Key (or press Enter to skip): ").strip()
    groq_key = console.input("Enter your GROQ API Key (or press Enter to skip): ").strip()
    
    if groq_key and not groq_key.startswith("gsk_"):
        console.print("[red]⚠️ Groq API key should start with 'gsk_'[/red]")
        groq_key = Prompt.ask("Re-enter Groq API key")
        
    from sky.config.schema import get_config_dir
    config_dir = get_config_dir(global_mode=global_install)
        
    def _save_env(groq_key: str, nim_key: str):
        with open(config_dir / ".env", "w") as f:
            if groq_key:
                f.write(f"GROQ_API_KEY={groq_key}\n")
            if nim_key:
                f.write(f"NVIDIA_NIM_API_KEY={nim_key}\n")
        console.print(f"[green]✅ API keys saved to {config_dir / '.env'}[/green]")

    _save_env(groq_key, nim_key)
        
    # 2. Generate local models.yaml
    models_yaml_path = config_dir / "models.yaml"
    should_write = True
    if models_yaml_path.exists() and not force:
        if not typer.confirm(f"{models_yaml_path} already exists. Overwrite?"):
            should_write = False
            
    if should_write:
        _write_default_models_yaml(models_yaml_path)
        console.print(f"[green]Created/Overwrote {models_yaml_path}[/green]")
        
    # Validate the generated config
    from sky.config import load_models_config
    import pydantic
    try:
        models_config = load_models_config(global_mode=global_install)
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in models.yaml.[/bold red]")
        console.print("[yellow]Please run 'sky init --force' to regenerate it.[/yellow]")
        raise typer.Exit(1)
        
    console.print("\n[bold green]✅ Sky configuration complete![/bold green]")
    console.print(f"[dim]Configuration saved to: {config_dir}[/dim]")

    console.print("\n[bold]Would you like to:[/bold]")
    console.print("  1. [cyan]Check provider connections[/cyan] (sky check-providers)")
    console.print("  2. [cyan]Ask a test question[/cyan] (sky ask 'hello')")
    console.print("  3. [cyan]Exit[/cyan]")

    choice = Prompt.ask("Your choice", choices=["1", "2", "3"], default="1")

    if choice == "1":
        subprocess.run(["sky", "check-providers"])
    elif choice == "2":
        subprocess.run(["sky", "ask", "hello"])
    elif choice == "3":
        console.print("[dim]Exiting...[/dim]")

def _write_default_models_yaml(path: Path):
    content = """providers:
  groq:
    base_url: "https://api.groq.com/openai/v1"
    timeout: 30
    default_model: "openai/gpt-oss-120b"
    models:
      - id: "groq/compound-mini"
        description: "Ultra-fast routing (0.1s)"
      - id: "openai/gpt-oss-120b"
        description: "Best general conversation"
      - id: "qwen/qwen3.6-27b"
        description: "Best-in-class tool calling"

  nim:
    base_url: "https://integrate.api.nvidia.com/v1"
    timeout: 60
    default_model: "meta/muse-glimmer-30b"
    models:
      - id: "meta/muse-glimmer-30b"
        description: "Purpose-built for agentic reasoning & planning"
      - id: "nvidia/nemotron-3-super-120b-a12b"
        description: "Best-in-class tool calling & coding"
      - id: "nvidia/llama-3.1-nemotron-70b-instruct"
        description: "Reliable backup model"

roles:
  general:
    provider: "groq"
    model_id: "openai/gpt-oss-120b"
    temperature: 0.7
    description: "Best general conversation"

  planning:
    provider: "nim"
    model_id: "meta/muse-glimmer-30b"
    temperature: 0.3
    description: "Dedicated reasoning & planning"

  reviewer:
    provider: "nim"
    model_id: "meta/muse-glimmer-30b"
    temperature: 0.3
    description: "Code review & analysis"

  routing:
    provider: "groq"
    model_id: "groq/compound-mini"
    temperature: 0.0
    description: "Ultra-fast routing (0.1s)"

  fast_loop:
    provider: "nim"
    model_id: "nvidia/nemotron-3-super-120b-a12b"
    temperature: 0.1
    description: "Best-in-class tool calling"

  coder:
    provider: "nim"
    model_id: "nvidia/nemotron-3-super-120b-a12b"
    temperature: 0.1
    description: "Agentic coding"

  tester:
    provider: "nim"
    model_id: "nvidia/nemotron-3-super-120b-a12b"
    temperature: 0.1
    description: "Test generation & pattern recognition"

fallback:
  provider: "nim"
  model_id: "nvidia/llama-3.1-nemotron-70b-instruct"
  temperature: 0.1
  description: "Reliable backup when primary fails"
"""
    path.write_text(content)


def validate_model(provider: str, model_id: str) -> bool:
    """Check if the model exists on the provider."""
    import os
    import httpx
    
    if provider == "groq":
        key = os.getenv("GROQ_API_KEY")
        if key:
            try:
                res = httpx.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"})
                if res.status_code == 200:
                    models = [m["id"] for m in res.json().get("data", [])]
                    if model_id not in models:
                        console.print(f"[yellow]Warning: Model {model_id} not found in Groq models list![/yellow]")
            except:
                pass
    elif provider == "nim":
        key = os.getenv("NIM_API_KEY")
        if key:
            try:
                res = httpx.get("https://integrate.api.nvidia.com/v1/models", headers={"Authorization": f"Bearer {key}"})
                if res.status_code == 200:
                    models = [m["id"] for m in res.json().get("data", [])]
                    if model_id not in models:
                        console.print(f"[yellow]Warning: Model {model_id} not found in NIM models list![/yellow]")
            except:
                pass
    return True

@app.command("check-providers")
def check_providers(global_install: bool = typer.Option(False, "--global", help="Use global config (~/.sky/)")):
    """
    Check provider connectivity and configuration.

    Examples:
      sky check-providers

    Shows:
      - Status of each provider
      - Available models
      - Model recommendations per role
    """
    import os
    import httpx
    from dotenv import load_dotenv
    from sky.config import load_models_config
    from sky.config.schema import get_config_dir
    from sky.errors import ProviderError, SkyError
    import pydantic
    
    config_dir = get_config_dir(global_mode=global_install)
    load_dotenv(config_dir / ".env", override=True)
    console.print("[bold blue]Checking Providers...[/bold blue]\n")
    
    try:
        models_config = load_models_config()
    except pydantic.ValidationError as e:
        console.print("\n[bold red]⚠️ Configuration error in models.yaml.[/bold red]")
        console.print("[yellow]Please run 'sky init' to regenerate it.[/yellow]")
        raise typer.Exit(1)
    except FileNotFoundError:
        console.print("\n[bold red]⚠️ Configuration file not found.[/bold red]")
        console.print("[yellow]Please run 'sky init' to create it.[/yellow]")
        raise typer.Exit(1)
    
    try:
        # Helper to print models
        def print_provider_info(provider_name: str, status_msg: str):
            provider = models_config.providers.get(provider_name)
            console.print(f"  Status: {status_msg}")
            if provider and provider.models:
                console.print("  Available Models (configured):")
                for m in provider.models:
                    desc = m.description or "No description"
                    console.print(f"    - {m.id} ({desc})")
            
            used_roles = [r for r, c in models_config.roles.items() if c.provider == provider_name]
            if used_roles:
                console.print(f"  Used for: {', '.join(used_roles)}")
        
        # Check NIM
        console.print("[bold]NVIDIA NIM:[/bold]")
        nim_key = os.getenv("NVIDIA_NIM_API_KEY")
        if not nim_key:
            raise ProviderError(
                "NVIDIA_NIM_API_KEY not found",
                code="SKY-001",
                suggestion="Add NVIDIA_NIM_API_KEY to .env or run `sky init`"
            )
        else:
            try:
                nim_provider = models_config.providers.get("nim")
                nim_base = nim_provider.base_url if (nim_provider and nim_provider.base_url) else "https://integrate.api.nvidia.com/v1"
                res = httpx.get(f"{nim_base.rstrip('/')}/models", headers={"Authorization": f"Bearer {nim_key}"})
                if res.status_code == 200:
                    print_provider_info("nim", "✅ [green]Connected[/green]")
                else:
                    print_provider_info("nim", f"❌ [red]Connection failed: {res.status_code} {res.text}[/red]")
            except Exception as e:
                print_provider_info("nim", f"❌ [red]Connection failed: {e}[/red]")
                
        console.print()
        
        # Check Groq
        console.print("[bold]Groq:[/bold]")
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ProviderError(
                "GROQ_API_KEY not found",
                code="SKY-001",
                suggestion="Add GROQ_API_KEY to .env or run `sky init`"
            )
        else:
            try:
                groq_provider = models_config.providers.get("groq")
                groq_base = groq_provider.base_url if (groq_provider and groq_provider.base_url) else "https://api.groq.com/openai/v1"
                res = httpx.get(f"{groq_base.rstrip('/')}/models", headers={"Authorization": f"Bearer {groq_key}"})
                if res.status_code == 200:
                    print_provider_info("groq", "✅ [green]Connected[/green]")
                else:
                    print_provider_info("groq", f"❌ [red]Connection failed: {res.status_code} {res.text}[/red]")
            except Exception as e:
                print_provider_info("groq", f"❌ [red]Connection failed: {e}[/red]")
    
        console.print("\n[bold]Model Recommendations:[/bold]")
        console.print("  - [bold]General Interaction:[/bold] openai/gpt-oss-120b (Groq) - Best conversation")
        console.print("  - [bold]Planning/Reviewing:[/bold] Muse Glimmer 30B (NIM) - Best reasoning")
        console.print("  - [bold]Routing:[/bold] groq/compound-mini (Groq) - Fastest (0.1s)")
        console.print("  - [bold]Tool Calling:[/bold] Nemotron 120B (NIM) - Best tool use")
        console.print("  - [bold]Coding/Testing:[/bold] Nemotron 120B (NIM) - Best SWE-bench")
    except SkyError as e:
        console.print(f"\n[bold red]Error ({e.code}):[/bold red] {e.message}")
        if e.suggestion:
            console.print(f"[bold yellow]Suggestion:[/bold yellow] {e.suggestion}")
        import sys
        sys.exit(1)

@app.command("clean")
def clean(global_install: bool = typer.Option(False, "--global", help="Clean global config (~/.sky/)")):
    """Remove all Sky configuration files."""
    from rich.prompt import Confirm
    import shutil
    from sky.config.schema import get_config_dir
    
    config_dir = get_config_dir(global_mode=global_install)
    if Confirm.ask(f"Delete Sky configuration folder ({config_dir})?", default=False):
        if config_dir.exists():
            shutil.rmtree(config_dir)
            console.print(f"[green]✅ Sky configuration cleaned from {config_dir}.[/green]")
        else:
            console.print(f"[yellow]No configuration found at {config_dir}.[/yellow]")

@app.command("reset")
def reset():
    """Reset Sky configuration (same as sky clean)."""
    clean()

if __name__ == "__main__":
    try:
        app()
    except Exception as e:
        console.print(f"[bold red]{_handle_error(e)}[/bold red]")
        sys.exit(1)
        app()
    except Exception as e:
        console.print(f"[bold red]{_handle_error(e)}[/bold red]")
        sys.exit(1)
