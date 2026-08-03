param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$cloudflared = Join-Path $projectRoot "resources\tools\cloudflared.exe"
$localSettings = Join-Path $projectRoot "deploy\cloudflare-tunnel.local.ps1"
$tunnelConfig = Join-Path $projectRoot "deploy\cloudflare-config.yml"
$certFile = Join-Path $HOME ".cloudflared\cert.pem"

function Stop-WithMessage([string]$Message) {
    Write-Host ""
    Write-Host $Message -ForegroundColor Red
    exit 1
}

function Quote-PowerShell([string]$Value) {
    return $Value.Replace("'", "''")
}

if (-not (Test-Path -LiteralPath $cloudflared)) {
    Stop-WithMessage "未找到 cloudflared.exe。"
}

if (-not (Test-Path -LiteralPath $localSettings)) {
    Write-Host "首次设置固定域名隧道" -ForegroundColor Cyan
    Write-Host "Cloudflare 会打开浏览器，请登录并选择你的域名。"

    if (-not (Test-Path -LiteralPath $certFile)) {
        & $cloudflared tunnel login
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $certFile)) {
            Stop-WithMessage "Cloudflare 登录没有完成。"
        }
    }

    $tunnelName = Read-Host "隧道名称（直接回车使用 80gotv）"
    if ([string]::IsNullOrWhiteSpace($tunnelName)) { $tunnelName = "80gotv" }

    $hostname = (Read-Host "请输入固定域名，例如 cs.example.com").Trim().ToLowerInvariant()
    if ($hostname -notmatch '^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$') {
        Stop-WithMessage "域名格式不正确。"
    }

    $tunnels = @(& $cloudflared tunnel list --output json | ConvertFrom-Json)
    $tunnel = $tunnels | Where-Object { $_.name -eq $tunnelName } | Select-Object -First 1
    if (-not $tunnel) {
        & $cloudflared tunnel create $tunnelName
        if ($LASTEXITCODE -ne 0) { Stop-WithMessage "创建固定隧道失败。" }
        $tunnels = @(& $cloudflared tunnel list --output json | ConvertFrom-Json)
        $tunnel = $tunnels | Where-Object { $_.name -eq $tunnelName } | Select-Object -First 1
    }
    if (-not $tunnel) { Stop-WithMessage "没有找到刚创建的固定隧道。" }

    $tunnelId = [string]$tunnel.id
    $credentialsFile = Join-Path $HOME ".cloudflared\$tunnelId.json"
    if (-not (Test-Path -LiteralPath $credentialsFile)) {
        Stop-WithMessage "没有找到固定隧道的凭据文件。"
    }

    & $cloudflared tunnel route dns $tunnelName $hostname
    if ($LASTEXITCODE -ne 0) {
        Stop-WithMessage "绑定固定域名失败。该域名可能已有 DNS 记录，请改用一个空闲子域名。"
    }

    $yamlCredential = $credentialsFile.Replace("\", "/")
    $yaml = @(
        "tunnel: $tunnelId"
        "credentials-file: $yamlCredential"
        "ingress:"
        "  - hostname: $hostname"
        "    service: http://127.0.0.1:5000"
        "  - service: http_status:404"
    )
    [IO.File]::WriteAllLines($tunnelConfig, $yaml, [Text.UTF8Encoding]::new($false))

    $settings = @(
        "`$TunnelName = '$(Quote-PowerShell $tunnelName)'"
        "`$Hostname = '$(Quote-PowerShell $hostname)'"
    )
    [IO.File]::WriteAllLines($localSettings, $settings, [Text.UTF8Encoding]::new($false))
}

. $localSettings
if ([string]::IsNullOrWhiteSpace($TunnelName) -or [string]::IsNullOrWhiteSpace($Hostname)) {
    Stop-WithMessage "固定隧道设置不完整。"
}
if (-not (Test-Path -LiteralPath $tunnelConfig)) {
    Stop-WithMessage "缺少固定隧道配置，请删除 cloudflare-tunnel.local.ps1 后重新运行。"
}

& $cloudflared tunnel --config $tunnelConfig ingress validate
if ($LASTEXITCODE -ne 0) { Stop-WithMessage "固定隧道规则检查失败。" }

$busyPort = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
if ($busyPort) {
    Stop-WithMessage "5000 端口已被占用。请先关闭正在运行的本地网站。"
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { Stop-WithMessage "没有找到 Python。" }
    $python = $pythonCommand.Source
}

$dependencyCheck = Start-Process -FilePath $python `
    -ArgumentList '-c "import flask, waitress"' `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
if ($dependencyCheck.ExitCode -ne 0) {
    Write-Host "首次运行正在安装网站依赖..." -ForegroundColor Yellow
    $requirements = Join-Path $projectRoot "requirements.txt"
    $dependencyInstall = Start-Process -FilePath $python `
        -ArgumentList "-m pip install -r `"$requirements`"" `
        -NoNewWindow `
        -Wait `
        -PassThru
    if ($dependencyInstall.ExitCode -ne 0) { Stop-WithMessage "安装网站依赖失败。" }
}

$env:FLASK_ENV = "production"
$env:PUBLIC_BASE_URL = "https://$Hostname"
$env:SESSION_COOKIE_SECURE = "true"
$env:TRUST_PROXY = "true"
$env:TRUSTED_HOSTS = $Hostname

$webStartInfo = [System.Diagnostics.ProcessStartInfo]::new()
$webStartInfo.FileName = $python
$webStartInfo.Arguments = "-m waitress --listen=127.0.0.1:5000 wsgi:app"
$webStartInfo.WorkingDirectory = $projectRoot
$webStartInfo.UseShellExecute = $false
$webStartInfo.CreateNoWindow = $true
$webProcess = [System.Diagnostics.Process]::new()
$webProcess.StartInfo = $webStartInfo
if (-not $webProcess.Start()) {
    Stop-WithMessage "本地网站启动失败。"
}

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($webProcess.HasExited) { break }
        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:5000/healthz" `
                -Headers @{ Host = $Hostname } `
                -UseBasicParsing `
                -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch {}
    }
    if (-not $ready) {
        Stop-WithMessage "本地网站启动失败，请重新运行后再试。"
    }

    Write-Host ""
    Write-Host "80GOTV 已上线：https://$Hostname" -ForegroundColor Green
    Write-Host "保持此窗口开启；按 Ctrl+C 可关闭网站和隧道。"
    Write-Host ""
    & $cloudflared tunnel --config $tunnelConfig run $TunnelName
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage "固定隧道连接失败。" }
} finally {
    if ($webProcess -and -not $webProcess.HasExited) {
        Stop-Process -Id $webProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
