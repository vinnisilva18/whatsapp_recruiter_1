param(
    [string]$Search = "",

    [int]$Limit = 30,

    [int]$ChatLimit = 50,

    [string]$Output = "output/recruiters",

    [bool]$Headless = $true
)

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$arguments = @(
    (Join-Path $PSScriptRoot "main.py"),
    "--limit", $Limit,
    "--chat-limit", $ChatLimit,
    "--output", $Output
)

if (-not (Test-Path $python)) {
    Write-Error "Ambiente virtual nao encontrado em .venv. Rode primeiro: python -m venv .venv"
    exit 1
}

if ($Search -and $Search.Trim()) {
    $arguments += @("--search", $Search)
}

$env:HEADLESS = $Headless.ToString().ToLowerInvariant()

& $python @arguments
