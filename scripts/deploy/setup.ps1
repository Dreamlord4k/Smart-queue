param(
    [ValidateSet("", "1", "2", "3", "4", "5")]
    [string]$Scenario = "",
    [switch]$Https
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $ProjectRoot

$script:Failures = 0
$Services = @("postgres", "redis", "backend", "bot", "frontend", "nginx")
$GroupSeedPython = @'
from scripts.generate_demo_data import _group_rows
from backend.auth.dependencies import SessionLocal
from backend.models.group import Group

rows = _group_rows("bootstrap")
with SessionLocal() as db:
    for group_id, name in rows:
        group = db.get(Group, group_id)
        if group is None:
            db.add(Group(id=group_id, name=name))
        else:
            group.name = name
    db.commit()
print(f"Групп готово: {len(rows)}")
'@

function Write-Ok([string]$Message) {
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Failure([string]$Message, [string]$Remedy) {
    Write-Host "✗ $Message" -ForegroundColor Red
    Write-Host "  Что исправить: $Remedy" -ForegroundColor Yellow
}

function Write-Note([string]$Message) {
    Write-Host "  $Message"
}

function Invoke-Step {
    param(
        [string]$Title,
        [string]$Remedy,
        [scriptblock]$Action
    )
    try {
        & $Action
        Write-Ok $Title
        return $true
    }
    catch {
        Write-Failure $Title $Remedy
        Write-Note $_.Exception.Message
        return $false
    }
}

function Invoke-DiagnosticStep {
    param(
        [string]$Title,
        [string]$Remedy,
        [scriptblock]$Action
    )
    if (-not (Invoke-Step $Title $Remedy $Action)) {
        $script:Failures++
    }
}

function Invoke-External {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
    $ExitCode = $LASTEXITCODE
    if ($ExitCode -ne 0) {
        throw "$File завершился с кодом $ExitCode"
    }
}

function Invoke-Compose([string[]]$Arguments) {
    Invoke-External "docker" (@("compose") + $Arguments)
}

function Import-DotEnv {
    if (-not (Test-Path ".env")) { return }
    foreach ($Line in Get-Content ".env") {
        $Trimmed = $Line.Trim()
        if (-not $Trimmed -or $Trimmed.StartsWith("#") -or -not $Trimmed.Contains("=")) {
            continue
        }
        $Pair = $Trimmed.Split("=", 2)
        Set-Item -Path "Env:$($Pair[0].Trim())" -Value $Pair[1].Trim()
    }
}

function Initialize-Env {
    if (Test-Path ".env") {
        Write-Note ".env уже существует — оставлен без изменений."
        return
    }
    if (-not (Test-Path ".env.example")) {
        throw ".env.example отсутствует"
    }
    Copy-Item ".env.example" ".env"
    Write-Note "Создан .env из .env.example. Пароли оставлены явными плейсхолдерами."
    Write-Note "Перед production замените POSTGRES_PASSWORD, пароль внутри DB_URL и JWT_SECRET."
}

function Test-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Get-ContainerHealth([string]$Service) {
    $Container = (& docker compose ps -q $Service 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Container) { return "missing" }
    $Status = (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $Container 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { return "missing" }
    return $Status
}

function Test-ContainerHealthy([string]$Service) {
    $Status = Get-ContainerHealth $Service
    return $Status -eq "healthy" -or $Status -eq "running"
}

function Wait-AllServices {
    $Deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $Deadline) {
        $Pending = @($Services | Where-Object { -not (Test-ContainerHealthy $_) })
        if ($Pending.Count -eq 0) { return }
        Start-Sleep -Seconds 3
    }
    $Pending = @($Services | Where-Object { -not (Test-ContainerHealthy $_) })
    throw "Не healthy: $($Pending -join ', ')"
}

function Test-AllServicesOnce {
    $Pending = @($Services | Where-Object { -not (Test-ContainerHealthy $_) })
    if ($Pending.Count -gt 0) {
        throw "Не healthy/running: $($Pending -join ', ')"
    }
}

function Wait-SeedServices {
    $Deadline = (Get-Date).AddMinutes(2)
    while ((Get-Date) -lt $Deadline) {
        if ((Test-ContainerHealthy "postgres") -and (Test-ContainerHealthy "backend")) {
            return
        }
        Start-Sleep -Seconds 3
    }
    throw "postgres или backend не перешли в healthy"
}

function Test-Certificate {
    if (-not $env:DOMAIN -or -not (Test-ContainerHealthy "nginx")) { return $false }
    & docker compose exec -T nginx test -f "/etc/letsencrypt/live/$($env:DOMAIN)/fullchain.pem" *> $null
    return $LASTEXITCODE -eq 0
}

function Test-HttpsConfigured {
    return (
        (Test-Certificate) -or
        ($env:PUBLIC_BASE_URL -and $env:PUBLIC_BASE_URL.StartsWith("https://")) -or
        ($env:VITE_API_BASE_URL -and $env:VITE_API_BASE_URL.StartsWith("https://"))
    )
}

function Get-HttpBase {
    $Port = if ($env:NGINX_HTTP_PORT) { $env:NGINX_HTTP_PORT } else { "80" }
    if ($Port -eq "80") { return "http://localhost" }
    return "http://localhost:$Port"
}

function Get-HttpsBase {
    $Port = if ($env:NGINX_HTTPS_PORT) { $env:NGINX_HTTPS_PORT } else { "443" }
    if ($Port -eq "443") { return "https://$($env:DOMAIN)" }
    return "https://$($env:DOMAIN):$Port"
}

function Test-HealthUrl([string]$BaseUrl) {
    Invoke-WebRequest -UseBasicParsing -Uri "$BaseUrl/health" -TimeoutSec 15 | Out-Null
}

function Test-GroupsUrl([string]$BaseUrl) {
    $Groups = Invoke-RestMethod -Uri "$BaseUrl/api/groups" -TimeoutSec 15
    if (@($Groups).Count -lt 2) { throw "Найдено групп: $(@($Groups).Count)" }
}

function Invoke-SeedGroups {
    $ScriptsPath = (Join-Path $ProjectRoot "scripts")
    $Volume = "${ScriptsPath}:/workspace/scripts:ro"
    Invoke-Compose @("run", "--rm", "--no-deps", "-v", $Volume, "backend", "python", "-c", $GroupSeedPython)
}

function Invoke-Migrations {
    Invoke-Compose @("exec", "-T", "backend", "alembic", "-c", "/workspace/backend/alembic.ini", "upgrade", "head")
}

function Start-PlainStack {
    Invoke-Compose @("up", "--build", "-d")
}

function Start-HttpsStack {
    Invoke-Compose @("-f", "docker-compose.yml", "-f", "scripts/deploy/docker-compose.https.yml", "up", "--build", "-d")
}

function Test-ProductionEnv {
    $Invalid = $false
    if (-not $env:POSTGRES_PASSWORD -or $env:POSTGRES_PASSWORD -eq "change-me") {
        Write-Failure "POSTGRES_PASSWORD не настроен" "Замените change-me в .env и синхронно обновите пароль внутри DB_URL."
        $Invalid = $true
    }
    if (-not $env:DB_URL -or $env:DB_URL.Contains("change-me")) {
        Write-Failure "DB_URL не настроен" "Укажите тот же пароль PostgreSQL в DB_URL внутри .env."
        $Invalid = $true
    }
    if (-not $env:JWT_SECRET -or $env:JWT_SECRET -eq "change-me" -or $env:JWT_SECRET.Length -lt 32) {
        Write-Failure "JWT_SECRET небезопасен" "Впишите собственную строку длиной не менее 32 символов; скрипт не генерирует секреты молча."
        $Invalid = $true
    }
    if (-not $env:DOMAIN -or $env:DOMAIN -eq "queue.example.edu") {
        Write-Failure "DOMAIN не настроен" "Впишите реальный домен и направьте его A-запись на сервер."
        $Invalid = $true
    }
    if (-not $env:LETSENCRYPT_EMAIL -or $env:LETSENCRYPT_EMAIL -eq "admin@example.edu") {
        Write-Failure "LETSENCRYPT_EMAIL не настроен" "Впишите настоящий email для Let's Encrypt."
        $Invalid = $true
    }
    if ($Invalid) { throw "Production .env требует ручной настройки" }
}

function Invoke-CertificateIssue {
    Invoke-Compose @("up", "-d", "nginx")
    Invoke-Compose @(
        "run", "--rm", "--entrypoint", "certbot", "certbot", "certonly",
        "--webroot", "--webroot-path", "/var/www/certbot",
        "--domain", $env:DOMAIN, "--email", $env:LETSENCRYPT_EMAIL,
        "--agree-tos", "--no-eff-email", "--non-interactive"
    )
    Invoke-Compose @(
        "-f", "docker-compose.yml", "-f", "scripts/deploy/docker-compose.https.yml",
        "up", "-d", "--force-recreate", "nginx"
    )
}

function Test-TelegramWebhook {
    if (-not $env:TELEGRAM_BOT_TOKEN) { throw "TELEGRAM_BOT_TOKEN пуст" }
    if (-not $env:DOMAIN) { throw "DOMAIN пуст" }
    $Expected = "https://$($env:DOMAIN)/api/telegram/webhook"
    $Info = Invoke-RestMethod -Uri "https://api.telegram.org/bot$($env:TELEGRAM_BOT_TOKEN)/getWebhookInfo" -TimeoutSec 15
    if (-not $Info.ok -or $Info.result.url -ne $Expected) {
        throw "Ожидался webhook $Expected, получен $($Info.result.url)"
    }
}

function Show-State {
    if (Test-Path ".env") { Write-Ok ".env найден" } else { Write-Note ".env отсутствует" }
    if (-not (Test-DockerReady)) {
        Write-Note "Docker/Compose или daemon пока недоступны"
        return
    }
    $Running = @($Services | Where-Object { Test-ContainerHealthy $_ }).Count
    $Certificate = if (Test-Certificate) { "да" } else { "нет" }
    $Groups = "недоступно"
    $Base = if (Test-HttpsConfigured) { Get-HttpsBase } else { Get-HttpBase }
    try {
        Test-GroupsUrl $Base
        $Groups = "есть (минимум 2)"
    } catch { }
    Write-Note "Запущено сервисов: $Running/$($Services.Count)"
    Write-Note "Сертификат для $(if ($env:DOMAIN) {$env:DOMAIN} else {'не задан'}): $Certificate"
    Write-Note "Группы: $Groups"
}

function Show-Summary {
    $Base = if ((Test-HttpsConfigured) -or $Https -or $Scenario -eq "2") { Get-HttpsBase } else { Get-HttpBase }
    Write-Host "`nИтоговые адреса:"
    Write-Host "  Frontend: $Base/"
    Write-Host "  API:      $Base/api"
    Write-Host "  Health:   $Base/health"
    if ($Base.StartsWith("https://")) {
        Write-Host "  Telegram: $Base/api/telegram/webhook"
    } else {
        Write-Host "  Telegram: не применяется без публичного HTTPS"
    }
}

function Initialize-Environment {
    if (-not (Invoke-Step "Docker и Compose готовы" "Установите Docker Desktop с Compose v2 и дождитесь запуска daemon." { if (-not (Test-DockerReady)) { throw "Docker недоступен" } })) { throw "Нет Docker" }
    if (-not (Invoke-Step ".env подготовлен без перезаписи" "Верните .env.example или создайте .env вручную." { Initialize-Env })) { throw "Нет .env" }
    Import-DotEnv
}

function Start-FullStack([bool]$UseHttps) {
    if ($UseHttps) {
        if (-not (Invoke-Step "Контейнеры собраны и запущены с HTTPS-overlay" "Проверьте compose logs и порты 80/443." { Start-HttpsStack })) { throw "Compose up failed" }
    } else {
        if (-not (Invoke-Step "Контейнеры собраны и запущены" "Проверьте compose logs и свободны ли порты из .env." { Start-PlainStack })) { throw "Compose up failed" }
    }
    if (-not (Invoke-Step "Все сервисы healthy" "Проверьте docker compose ps и logs первого unhealthy-контейнера." { Wait-AllServices })) { throw "Unhealthy services" }
    if (-not (Invoke-Step "Миграции применены" "Проверьте DB_URL/POSTGRES_PASSWORD и backend logs." { Invoke-Migrations })) { throw "Migration failed" }
    if (-not (Invoke-Step "Две группы посеяны идемпотентно" "Проверьте postgres/backend и DB_URL." { Invoke-SeedGroups })) { throw "Group seed failed" }
}

function Enable-Https {
    Test-ProductionEnv
    if (-not (Invoke-Step "Сертификат выпущен и HTTPS-overlay включён" "Проверьте A-запись, порты 80/443 и LETSENCRYPT_EMAIL." { Invoke-CertificateIssue })) { throw "Certificate failed" }
    if (-not (Invoke-Step "Все сервисы healthy после включения HTTPS" "Проверьте HTTPS compose и nginx logs." { Wait-AllServices })) { throw "Unhealthy services" }
    if (-not (Invoke-Step "HTTPS health отвечает" "Проверьте сертификат, DNS и порт 443." { Test-HealthUrl (Get-HttpsBase) })) { throw "HTTPS health failed" }
}

function Invoke-LocalScenario {
    Initialize-Environment
    Start-FullStack $false
    $Base = Get-HttpBase
    if (-not (Invoke-Step "HTTP health отвечает" "Проверьте nginx/backend logs и $Base/health." { Test-HealthUrl $Base })) { throw "Health failed" }
    if ($Https) {
        Enable-Https
    }
    Show-Summary
}

function Invoke-ProductionScenario {
    Initialize-Environment
    Test-ProductionEnv
    Start-FullStack $false
    if (-not (Invoke-Step "HTTP health до выпуска сертификата отвечает" "Проверьте DNS, firewall, порт 80 и nginx/backend logs." { Test-HealthUrl "http://$($env:DOMAIN)" })) { throw "HTTP health failed" }
    Enable-Https
    Show-Summary
}

function Invoke-UpdateScenario {
    Initialize-Environment
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git не установлен" }
    if (-not (Invoke-Step "Код обновлён fast-forward без сноса данных" "Уберите незакоммиченные конфликты и проверьте origin/main; volumes не удаляйте." { Invoke-External "git" @("pull", "--ff-only", "origin", "main") })) { throw "Git pull failed" }
    $UseHttps = (Test-HttpsConfigured) -and -not $Https
    Start-FullStack $UseHttps
    if ($Https) {
        Enable-Https
        $Base = Get-HttpsBase
    } else {
        $Base = if ($UseHttps) { Get-HttpsBase } else { Get-HttpBase }
    }
    if (-not (Invoke-Step "Health после обновления отвечает" "Проверьте миграции и backend/nginx logs; postgres volume сохраняется." { Test-HealthUrl $Base })) { throw "Health failed" }
    Show-Summary
}

function Invoke-GroupsScenario {
    Initialize-Environment
    if (-not (Invoke-Step "Postgres и backend запущены" "Проверьте DB_URL/POSTGRES_PASSWORD и logs postgres/backend." { Invoke-Compose @("up", "--build", "-d", "postgres", "redis", "backend") })) { throw "Compose up failed" }
    if (-not (Invoke-Step "Postgres и backend healthy" "Проверьте docker compose ps и logs postgres backend." { Wait-SeedServices })) { throw "Services unhealthy" }
    if (-not (Invoke-Step "Миграции применены" "Проверьте подключение backend к Postgres." { Invoke-Migrations })) { throw "Migration failed" }
    if (-not (Invoke-Step "Две группы посеяны идемпотентно" "Проверьте Postgres и права пользователя DB_URL." { Invoke-SeedGroups })) { throw "Group seed failed" }
    Write-Ok "Остальные данные и volumes не изменялись"
}

function Invoke-HealthScenario {
    Invoke-DiagnosticStep "Docker и Compose готовы" "Установите Docker Desktop с Compose v2 и запустите daemon." { if (-not (Test-DockerReady)) { throw "Docker недоступен" } }
    if (-not (Test-DockerReady)) {
        Write-Failure "Диагностика остановлена" "Без Docker нельзя проверить контейнеры. Никаких изменений не сделано."
        throw "Нет Docker"
    }
    Invoke-DiagnosticStep "Все сервисы healthy" "Проверьте docker compose ps/logs и поднимите отсутствующие сервисы." { Test-AllServicesOnce }
    $Base = if (Test-HttpsConfigured) { Get-HttpsBase } else { Get-HttpBase }
    Invoke-DiagnosticStep "Health отвечает" "Проверьте nginx/backend logs и $Base/health." { Test-HealthUrl $Base }
    Invoke-DiagnosticStep "В базе есть минимум две группы" "Выберите сценарий 4 — он досеет только две детерминированные группы." { Test-GroupsUrl $Base }
    Invoke-DiagnosticStep "Telegram webhook установлен на актуальный URL" "Задайте TELEGRAM_BOT_TOKEN и установите webhook на https://DOMAIN/api/telegram/webhook." { Test-TelegramWebhook }
    if (Test-Certificate) {
        Invoke-DiagnosticStep "HTTPS health отвечает" "Проверьте DNS, сертификат, порт 443 и nginx logs." { Test-HealthUrl (Get-HttpsBase) }
    } else {
        Write-Failure "HTTPS-сертификат не найден" "Для production выберите сценарий 2; локально HTTPS не обязателен."
        $script:Failures++
    }
    Show-Summary
    if ($script:Failures -gt 0) {
        throw "Проверка завершена: проблем — $script:Failures. Исправьте пункты выше и повторите сценарий 5."
    }
    Write-Ok "Проверка здоровья завершена без ошибок"
}

Import-DotEnv
Write-Host "Текущее состояние:"
Show-State

if (-not $Scenario) {
    Write-Host ""
    Write-Host "Выберите сценарий:"
    Write-Host "1) с нуля локально"
    Write-Host "2) прод-HTTPS с нуля"
    Write-Host "3) обновить код без сноса данных"
    Write-Host "4) только досеять группы"
    Write-Host "5) проверка здоровья (безопасный вариант по Enter)"
    $Scenario = Read-Host ">"
    if (-not $Scenario) { $Scenario = "5" }
}

try {
    switch ($Scenario) {
        "1" { Invoke-LocalScenario }
        "2" { Invoke-ProductionScenario }
        "3" { Invoke-UpdateScenario }
        "4" { Invoke-GroupsScenario }
        "5" { Invoke-HealthScenario }
        default { throw "Введите число от 1 до 5" }
    }
}
catch {
    Write-Failure "Сценарий $Scenario остановлен" $_.Exception.Message
    exit 1
}
