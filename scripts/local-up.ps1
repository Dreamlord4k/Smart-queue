[CmdletBinding()]
param(
    [switch]$Prod,
    [switch]$Help
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

$Mode = if ($Prod) { "prod" } else { "local" }
$ComposePrefix = if ($Prod) {
    @("-f", "docker-compose.yml", "-f", "scripts/deploy/docker-compose.https.yml")
} else {
    @()
}

function Show-Usage {
    Write-Host "Использование:"
    Write-Host "  .\scripts\local-up.ps1          # локальный HTTP-запуск"
    Write-Host "  .\scripts\local-up.ps1 -Prod    # production с HTTPS-overlay"
}

if ($Help) {
    Show-Usage
    exit 0
}

function Write-Step([string]$Number, [string]$Text) {
    Write-Host "`n[$Number] $Text"
}

function Write-Ok([string]$Text) {
    Write-Host "✓ $Text" -ForegroundColor Green
}

function Write-WarningWithAdvice([string]$Text, [string]$Advice) {
    Write-Warning "$Text Что делать дальше: $Advice"
}

function Stop-WithAdvice([string]$Text, [string]$Advice, [int]$Code = 1) {
    Write-Host "✗ $Text" -ForegroundColor Red
    Write-Host "Что делать дальше: $Advice" -ForegroundColor Yellow
    exit $Code
}

function Invoke-Compose([string[]]$Arguments, [switch]$AllowFailure) {
    & docker compose @ComposePrefix @Arguments
    $Code = $LASTEXITCODE
    if ($Code -ne 0 -and -not $AllowFailure) {
        throw "docker compose завершился с кодом $Code"
    }
}

function Get-ComposeOutput([string[]]$Arguments) {
    $Output = @(& docker compose @ComposePrefix @Arguments 2>$null)
    if ($LASTEXITCODE -ne 0) { return @() }
    return $Output
}

function Read-DotEnv([string]$Path) {
    $Values = @{}
    foreach ($Line in Get-Content -LiteralPath $Path) {
        $Trimmed = $Line.Trim()
        if (-not $Trimmed -or $Trimmed.StartsWith("#")) { continue }
        $Separator = $Trimmed.IndexOf("=")
        if ($Separator -lt 1) { continue }
        $Key = $Trimmed.Substring(0, $Separator).Trim()
        $Value = $Trimmed.Substring($Separator + 1).Trim()
        if ($Value.Length -ge 2) {
            $First = $Value.Substring(0, 1)
            $Last = $Value.Substring($Value.Length - 1, 1)
            if (($First -eq '"' -and $Last -eq '"') -or ($First -eq "'" -and $Last -eq "'")) {
                $Value = $Value.Substring(1, $Value.Length - 2)
            }
        }
        $Values[$Key] = $Value
    }
    return $Values
}

function Get-EnvOrDefault([hashtable]$Values, [string]$Name, [string]$Default) {
    if ($Values.ContainsKey($Name) -and $Values[$Name]) { return [string]$Values[$Name] }
    return $Default
}

function Convert-ToPort([string]$Value, [string]$Name) {
    $Port = 0
    if (-not [int]::TryParse($Value, [ref]$Port) -or $Port -lt 1 -or $Port -gt 65535) {
        Stop-WithAdvice "Некорректный порт для $Name" "Укажите в .env целое число от 1 до 65535."
    }
    return $Port
}

function Get-ProjectContainerNames {
    return @(Get-ComposeOutput -Arguments @("ps", "--format", "{{.Name}}"))
}

function Test-PortAvailable([int]$Port, [string]$Name) {
    $Published = @(& docker ps --filter "publish=$Port" --format "{{.Names}} {{.Ports}}" 2>$null)
    if ($LASTEXITCODE -ne 0) { $Published = @() }

    if ($Published.Count -gt 0) {
        $OwnNames = @(Get-ProjectContainerNames)
        $Foreign = @()
        foreach ($Line in $Published) {
            $ContainerName = ($Line -split "\s+", 2)[0]
            if ($OwnNames -notcontains $ContainerName) { $Foreign += $Line }
        }
        if ($Foreign.Count -eq 0) {
            Write-Host "  Порт $Port ($Name) занят текущим compose-проектом и будет освобождён на шаге down:"
            $Published | ForEach-Object { Write-Host "  $_" }
            return
        }
        Write-Host "  Обнаружены контейнеры:" -ForegroundColor Yellow
        $Foreign | ForEach-Object { Write-Host "  $_" }
        Stop-WithAdvice "Порт $Port ($Name) занят чужим Docker-контейнером" "Остановите указанный контейнер либо измените соответствующий порт в .env."
    }

    $Connections = @()
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $Connections = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    } else {
        $Connections = @(netstat -ano -p tcp 2>$null | Select-String -Pattern ":$Port\s+.*LISTENING")
    }

    if ($Connections.Count -gt 0) {
        Write-Host "  Владелец порта:" -ForegroundColor Yellow
        foreach ($Connection in $Connections) {
            if ($Connection.PSObject.Properties.Name -contains "OwningProcess") {
                $OwnerProcessId = [int]$Connection.OwningProcess
                $OwnerProcess = Get-Process -Id $OwnerProcessId -ErrorAction SilentlyContinue
                $OwnerName = if ($OwnerProcess) { $OwnerProcess.ProcessName } else { "неизвестный процесс" }
                Write-Host "  PID $OwnerProcessId ($OwnerName), $($Connection.LocalAddress):$Port"
            } else {
                Write-Host "  $Connection"
            }
        }
        Stop-WithAdvice "Порт $Port ($Name) занят" "Остановите указанный процесс либо измените соответствующий порт в .env."
    }

    Write-Ok "Порт $Port ($Name) свободен"
}

Write-Step "1/8" "Обновление кода"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-WarningWithAdvice "Git не установлен — продолжаю с текущей копией кода." "Установите Git и обновите репозиторий вручную."
} elseif (-not (Test-Path -LiteralPath ".git" -PathType Container)) {
    Write-WarningWithAdvice "Каталог не является Git-репозиторием — продолжаю без pull." "Проверьте, что скрипт запущен из клона проекта."
} else {
    & git pull --ff-only
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Код обновлён fast-forward"
    } else {
        Write-WarningWithAdvice "git pull не выполнен — продолжаю с текущим кодом." "Проверьте сеть, ветку и незакоммиченные изменения."
    }
}

Write-Step "2/8" "Проверка .env и обязательных настроек"
if (-not (Test-Path -LiteralPath ".env" -PathType Leaf)) {
    if (-not (Test-Path -LiteralPath ".env.example" -PathType Leaf)) {
        Stop-WithAdvice ".env и .env.example отсутствуют" "Верните .env.example или создайте .env вручную."
    }
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Ok "Создан .env из .env.example; существующие файлы не перезаписывались."
    Stop-WithAdvice "Запуск намеренно остановлен: секреты нельзя подставлять молча." "Заполните POSTGRES_PASSWORD, тот же пароль внутри DB_URL и JWT_SECRET длиной не менее 32 символов, затем запустите скрипт повторно." 2
}
Write-Ok ".env найден и не будет перезаписан"

$EnvValues = Read-DotEnv ".env"
$PostgresPassword = Get-EnvOrDefault $EnvValues "POSTGRES_PASSWORD" ""
$DatabaseUrl = Get-EnvOrDefault $EnvValues "DB_URL" ""
$JwtSecret = Get-EnvOrDefault $EnvValues "JWT_SECRET" ""
$ViteApiBaseUrl = Get-EnvOrDefault $EnvValues "VITE_API_BASE_URL" ""
$Domain = Get-EnvOrDefault $EnvValues "DOMAIN" ""

if (-not $PostgresPassword -or $PostgresPassword -eq "change-me") {
    Stop-WithAdvice "POSTGRES_PASSWORD не заполнен" "Замените change-me в .env и укажите тот же пароль внутри DB_URL."
}
if (-not $DatabaseUrl) {
    Stop-WithAdvice "DB_URL не заполнен" "Укажите строку подключения PostgreSQL в .env."
}
if ($DatabaseUrl.Contains("change-me")) {
    Stop-WithAdvice "DB_URL содержит плейсхолдер" "Укажите в DB_URL тот же реальный пароль, что и в POSTGRES_PASSWORD."
}
if (-not $JwtSecret -or $JwtSecret -eq "change-me" -or $JwtSecret.Length -lt 32) {
    Stop-WithAdvice "JWT_SECRET отсутствует или короче 32 символов" "Впишите собственный секрет длиной не менее 32 символов; значение не выводите и не коммитьте."
}
if (-not $ViteApiBaseUrl -or -not $ViteApiBaseUrl.EndsWith("/api")) {
    Stop-WithAdvice "VITE_API_BASE_URL отсутствует или не оканчивается на /api" "Укажите, например, http://localhost/api или https://domain.example/api."
}

if ($Prod) {
    $InvalidDomain = (
        -not $Domain -or
        $Domain -eq "localhost" -or
        $Domain -eq "queue.example.edu" -or
        -not $Domain.Contains(".") -or
        $Domain.Contains("://") -or
        $Domain.Contains(" ")
    )
    if ($InvalidDomain) {
        Stop-WithAdvice "DOMAIN не является рабочим FQDN" "Укажите в .env реальный домен без схемы, например queue.emka.lol."
    }
    if (-not $ViteApiBaseUrl.StartsWith("https://") -or -not $ViteApiBaseUrl.EndsWith("/api")) {
        Stop-WithAdvice "Production VITE_API_BASE_URL должен использовать HTTPS и /api" "Укажите https://<DOMAIN>/api и пересоберите frontend."
    }
}
Write-Ok "Конфигурация режима $Mode прошла preflight; значения секретов не выводились"

Write-Step "3/8" "Проверка Docker и портов"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Stop-WithAdvice "Docker не найден" "Установите Docker Desktop и повторите запуск."
}
& docker compose version *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-WithAdvice "Docker Compose v2 недоступен" "Установите Compose plugin и проверьте docker compose version."
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Stop-WithAdvice "Docker daemon не отвечает" "Запустите Docker Desktop и дождитесь его готовности."
}

$HttpPort = Convert-ToPort (Get-EnvOrDefault $EnvValues "NGINX_HTTP_PORT" "80") "NGINX_HTTP_PORT"
$BackendPort = Convert-ToPort (Get-EnvOrDefault $EnvValues "BACKEND_PORT" "8000") "BACKEND_PORT"
$FrontendPort = Convert-ToPort (Get-EnvOrDefault $EnvValues "FRONTEND_PORT" "5173") "FRONTEND_PORT"
$HttpsPort = Convert-ToPort (Get-EnvOrDefault $EnvValues "NGINX_HTTPS_PORT" "443") "NGINX_HTTPS_PORT"

$CheckedPorts = @{}
foreach ($PortSpec in @(
    @{ Port = $HttpPort; Name = "NGINX_HTTP_PORT" },
    @{ Port = $BackendPort; Name = "BACKEND_PORT" },
    @{ Port = $FrontendPort; Name = "FRONTEND_PORT" }
)) {
    if (-not $CheckedPorts.ContainsKey($PortSpec.Port)) {
        Test-PortAvailable $PortSpec.Port $PortSpec.Name
        $CheckedPorts[$PortSpec.Port] = $true
    }
}
if ($Prod -and -not $CheckedPorts.ContainsKey($HttpsPort)) {
    Test-PortAvailable $HttpsPort "NGINX_HTTPS_PORT"
}

Write-Step "4/8" "Остановка прежних контейнеров без удаления данных"
try {
    Invoke-Compose -Arguments @("down", "--remove-orphans") | Out-Null
    Write-Ok "Контейнеры остановлены; volumes не удалялись"
} catch {
    Stop-WithAdvice "docker compose down завершился ошибкой" "Проверьте docker compose ps и права Docker; не используйте down -v."
}

Write-Step "5/8" "Сборка и запуск контейнеров"
try {
    Invoke-Compose -Arguments @("up", "--build", "-d") | Out-Null
    Write-Ok "Контейнеры собраны и запущены в фоне"
} catch {
    Stop-WithAdvice "docker compose up завершился ошибкой" "Посмотрите docker compose logs, исправьте первую ошибку сборки/запуска и повторите скрипт."
}

if ($Prod) {
    $BaseUrl = if ($HttpsPort -eq 443) { "https://$Domain" } else { "https://${Domain}:$HttpsPort" }
} else {
    $BaseUrl = if ($HttpPort -eq 80) { "http://localhost" } else { "http://localhost:$HttpPort" }
}
$HealthUrl = "$BaseUrl/health"

Write-Step "6/8" "Ожидание health не более 90 секунд: $HealthUrl"
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
    Stop-WithAdvice "curl.exe не найден" "Установите современную версию Windows/curl и повторите запуск."
}
$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$Healthy = $false
while ($Stopwatch.Elapsed.TotalSeconds -le 90) {
    $Response = & curl.exe --fail --silent --show-error --max-time 5 $HealthUrl 2>$null
    if ($LASTEXITCODE -eq 0) {
        try {
            $Health = $Response | ConvertFrom-Json
            if ($Health.status -eq "ok") {
                $Healthy = $true
                break
            }
        } catch { }
    }
    Start-Sleep -Seconds 3
}

if (-not $Healthy) {
    Write-Host "Последние логи backend:" -ForegroundColor Yellow
    Invoke-Compose -Arguments @("logs", "--tail=80", "backend") -AllowFailure
    Stop-WithAdvice "Health не стал успешным за 90 секунд" "Исправьте первую ошибку в логах backend, проверьте PostgreSQL/Redis и повторите: curl.exe $HealthUrl"
}
Write-Ok "Health вернул status=ok"

Write-Step "7/8" "Контрольное применение миграций"
try {
    Invoke-Compose -Arguments @("exec", "-T", "backend", "alembic", "-c", "/workspace/backend/alembic.ini", "upgrade", "head") | Out-Null
    Write-Ok "Alembic находится на head; повторный прогон безопасен"
} catch {
    Write-Host "Последние логи backend:" -ForegroundColor Yellow
    Invoke-Compose -Arguments @("logs", "--tail=80", "backend") -AllowFailure
    Stop-WithAdvice "Контрольный прогон миграций завершился ошибкой" "Проверьте DB_URL, пароль PostgreSQL и состояние backend, затем повторите скрипт."
}

Write-Step "8/8" "Итоговое состояние"
Invoke-Compose -Arguments @("ps")
Write-Host "`nГотовые URL:"
Write-Host "  Frontend: $BaseUrl/"
Write-Host "  API:      $BaseUrl/api"
Write-Host "  Health:   $BaseUrl/health"
Write-Ok "Docker-окружение запущено в режиме $Mode"
