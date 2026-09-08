$IMAGE = "python:3.11-slim"
$NETWORK = "bridge"
$WORKSPACE_DIR = (Get-Location).Path

Write-Host "Starting Sky in an isolated Docker sandbox..." -ForegroundColor Cyan
Write-Host "Mounting $WORKSPACE_DIR to /workspace" -ForegroundColor Cyan
Write-Host "Network mode: $NETWORK" -ForegroundColor Cyan

# Load .env variables manually to pass to Docker
$envParams = @()
if (Test-Path ".sky/.env") {
    foreach ($line in Get-Content ".sky/.env") {
        if ($line -match "^(.*)=(.*)$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            $envParams += "-e"
            $envParams += "$name=$value"
        }
    }
}

$dockerArgs = @(
    "run", "-it", "--rm",
    "--network", $NETWORK,
    "-v", "$WORKSPACE_DIR`:/workspace",
    "-w", "/workspace"
)

$dockerArgs += $envParams
$dockerArgs += $IMAGE
$dockerArgs += "bash"
$dockerArgs += "-c"
$dockerArgs += "pip install -e . --quiet && echo 'Sky Sandbox Ready!' && bash"

& docker $dockerArgs
