[CmdletBinding()]
param(
    [ValidateSet('Backend', 'Frontend')]
    [string]$Service,
    [switch]$NoBrowser,
    [ValidateRange(1024, 65535)][int]$BackendPort = 8001,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$pythonExe = Join-Path $projectDir '.venv\Scripts\python.exe'
$frontendDir = Join-Path $projectDir 'frontend'
$backendUrl = "http://127.0.0.1:$BackendPort"
$frontendUrl = "http://127.0.0.1:$FrontendPort"

# Child terminals use the README commands. Calling the venv executable directly
# avoids activation and does not change any execution policy.
if ($Service) {
    try {
        if ($Service -eq 'Backend') {
            $Host.UI.RawUI.WindowTitle = "CoreCare Backend - port $BackendPort"
            Set-Location -LiteralPath $projectDir
            & $pythonExe -m uvicorn backend.main:app --host 127.0.0.1 --port $BackendPort
        } else {
            $Host.UI.RawUI.WindowTitle = "CoreCare Frontend - port $FrontendPort"
            Set-Location -LiteralPath $frontendDir
            $env:CORECARE_BACKEND_URL = $backendUrl
            & npm.cmd run dev -- --port $FrontendPort --strictPort
        }
        if ($LASTEXITCODE -ne 0) { throw "$Service exited unsuccessfully. Review this terminal's output." }
    } catch {
        Write-Host "CoreCare $Service could not start. Check dependencies and whether its port is occupied." -ForegroundColor Red
        throw
    }
    return
}

function Test-Backend {
    try {
        $health = Invoke-RestMethod "$backendUrl/" -TimeoutSec 2
        $schema = Invoke-RestMethod "$backendUrl/openapi.json" -TimeoutSec 2
        $config = Invoke-RestMethod "$backendUrl/config" -TimeoutSec 2
        return ($health.message -eq 'CoreCare API is running' -and $schema.info.title -eq 'CoreCare' -and $null -ne $config.report_upload)
    } catch { return $false }
}

function Test-Frontend {
    try {
        $page = Invoke-WebRequest $frontendUrl -UseBasicParsing -TimeoutSec 2
        $proxy = Invoke-RestMethod "$frontendUrl/config" -TimeoutSec 2
        $direct = Invoke-RestMethod "$backendUrl/config" -TimeoutSec 2
        return ($page.Content -match '<title>CoreCare' -and $null -ne $proxy.report_upload -and
            ($proxy | ConvertTo-Json -Depth 8 -Compress) -eq ($direct | ConvertTo-Json -Depth 8 -Compress))
    } catch { return $false }
}

function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync('127.0.0.1', $Port).Wait(1000) -and $client.Connected }
    catch { return $false }
    finally { $client.Dispose() }
}

function Start-ServiceTerminal([string]$Name) {
    $shellExe = (Get-Process -Id $PID).Path
    if ([IO.Path]::GetFileName($shellExe) -notin @('pwsh.exe', 'powershell.exe')) {
        $shellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
    }
    # Visible terminals are intentional for the live demo and Ctrl+C shutdown.
    Start-Process -FilePath $shellExe -WorkingDirectory $projectDir -WindowStyle Normal `
        -ArgumentList "-NoProfile -NoExit -File `"$PSCommandPath`" -Service $Name -BackendPort $BackendPort -FrontendPort $FrontendPort" | Out-Null
    Write-Host "Starting $Name in a separate PowerShell terminal..."
}

function Wait-Service([string]$Name, [scriptblock]$Check) {
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (& $Check) { Write-Host "$Name is ready." -ForegroundColor Green; return }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready within 90 seconds. Check its PowerShell terminal. Close failed startup terminals before retrying."
}

try {
    if ($BackendPort -eq $FrontendPort) { throw 'Backend and frontend ports must be different.' }
    foreach ($path in @($pythonExe, (Join-Path $frontendDir 'node_modules\vite\bin\vite.js'),
        (Join-Path $projectDir 'tests\fixtures\reports\cbc_text.pdf'))) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required file missing: $path. Complete the README setup first." }
    }
    foreach ($command in @('node.exe', 'npm.cmd')) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command is missing. Install Node.js and complete frontend setup first." }
    }
    Write-Host 'Checking Python dependencies, configuration, and existing knowledge base (no API request)...'
    # Bound the check and suppress native diagnostics; never echo settings or keys.
    $checkCode = @'
import json, sys
stage = 'Python dependencies/configuration'
try:
    import uvicorn, fastapi, multipart, pymupdf, PIL, pytesseract, psutil, groq, chromadb
    from backend.config.settings import settings
    import backend.main
    stage = 'Chroma knowledge base: run .venv/Scripts/python.exe -m backend.rag.ingest once'
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    count = client.get_collection(settings.collection_name).count()
    if not count:
        raise RuntimeError('Empty collection')
    ocr = False
    try:
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        ocr = 'eng' in pytesseract.get_languages(config='')
    except Exception:
        pass
    print(json.dumps({'ok': True, 'chunks': count, 'groq_configured': bool(settings.groq_api_key.strip()), 'ocr_ready': ocr}))
except Exception:
    print(json.dumps({'ok': False, 'stage': stage}))
    sys.exit(1)
'@
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $pythonExe
    $startInfo.Arguments = '-'
    $startInfo.WorkingDirectory = $projectDir
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $checkProcess = New-Object System.Diagnostics.Process
    $checkProcess.StartInfo = $startInfo
    try {
        [void]$checkProcess.Start()
        $stdout = $checkProcess.StandardOutput.ReadToEndAsync()
        $stderr = $checkProcess.StandardError.ReadToEndAsync()
        $checkProcess.StandardInput.WriteLine($checkCode)
        $checkProcess.StandardInput.Close()
        if (-not $checkProcess.WaitForExit(60000)) {
            $checkProcess.Kill()
            throw 'Dependency check timed out. Check the Python environment and Chroma installation.'
        }
        $check = $stdout.GetAwaiter().GetResult() | ConvertFrom-Json
        if ($checkProcess.ExitCode -ne 0 -or -not $check.ok) { throw "Preflight failed: $($check.stage). See the README setup; configuration values are intentionally hidden." }
    } finally { $checkProcess.Dispose() }
    Write-Host "Knowledge base ready: $($check.chunks) chunks."
    if (-not $check.groq_configured) { Write-Warning 'Groq key not configured. Local extraction/ranges remain available; AI explanations require GROQ_API_KEY and internet.' }
    if (-not $check.ocr_ready) { Write-Warning 'Tesseract with English data is unavailable. Use the text-based CBC PDF; scanned reports require TESSERACT_CMD/OCR setup.' }

    if (Test-Backend) { Write-Host 'Reusing existing CoreCare backend.' }
    elseif (Test-Port $BackendPort) { throw "Port $BackendPort is occupied by an unavailable or unrecognized service. Resolve that port conflict before retrying." }
    else { Start-ServiceTerminal 'Backend' }
    Wait-Service 'Backend' { Test-Backend }

    if (Test-Frontend) { Write-Host 'Reusing existing CoreCare frontend.' }
    elseif (Test-Port $FrontendPort) { throw "Port $FrontendPort is occupied or its CoreCare API proxy is incorrect. Check that terminal and CORECARE_BACKEND_URL before retrying." }
    else { Start-ServiceTerminal 'Frontend' }
    Wait-Service 'Frontend' { Test-Frontend }

    Write-Host "CoreCare: $frontendUrl" -ForegroundColor Green
    Write-Host "Swagger: $backendUrl/docs"
    Write-Host "Synthetic report: $(Join-Path $projectDir 'tests\fixtures\reports\cbc_text.pdf')"
    Write-Host 'Enable AI consent in the application to request Groq explanations. Stop services with Ctrl+C in their terminals.'
    if (-not $NoBrowser) { Start-Process $frontendUrl; Write-Host 'Opened CoreCare in your default browser.' }
} catch {
    Write-Host "CoreCare demo startup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
