$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$codexCommand = Get-Command codex -ErrorAction Stop
$pythonCommand = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonCommand -PathType Leaf)) {
    throw "Project Python was not found. Run 'uv sync --extra mcp' first."
}

$arguments = @(
    "mcp", "add", "tradefin", "--", $pythonCommand,
    "-m", "tradefin.mcp_server"
)
& $codexCommand.Source @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Could not register the Tradefin MCP server with Codex."
}
