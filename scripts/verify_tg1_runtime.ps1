[CmdletBinding()]
param(
    [string]$ExpectedImageId = "sha256:86b8cffc648507e11bb7f8e4e1900b2534e4da5f496ecc927a3628c80bd016a7",
    [string]$BackupConfigPath = "F:\AIOS\anh-duong-checkpoints\backups\TG-1-20260801T114348Z\openclaw\openclaw.json"
)

$ErrorActionPreference = "Stop"
$container = "openclaw-openclaw-gateway-1"
$results = [Collections.Generic.List[object]]::new()

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $results.Add([pscustomobject]@{ name = $Name; passed = $Passed; detail = $Detail })
}

function Normalize-JsonValue {
    param($Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [pscustomobject]) {
        $ordered = [ordered]@{}
        foreach ($property in ($Value.PSObject.Properties | Sort-Object Name)) {
            $ordered[$property.Name] = Normalize-JsonValue $property.Value
        }
        return [pscustomobject]$ordered
    }
    if ($Value -is [Collections.IEnumerable] -and $Value -isnot [string]) {
        return @($Value | ForEach-Object { Normalize-JsonValue $_ })
    }
    return $Value
}

function Get-ValueHash {
    param($Value)
    $json = Normalize-JsonValue $Value | ConvertTo-Json -Compress -Depth 100
    $bytes = [Text.Encoding]::UTF8.GetBytes($json)
    $sha = [Security.Cryptography.SHA256]::Create()
    return [Convert]::ToHexString($sha.ComputeHash($bytes)).ToLowerInvariant()
}

function Get-ProtectedHashes {
    param($Config)
    return [ordered]@{
        telegram_token = Get-ValueHash $Config.channels.telegram.botToken
        telegram_config = Get-ValueHash $Config.channels.telegram
        agent_model = Get-ValueHash $Config.agents.defaults.model
        agent_models = Get-ValueHash $Config.agents.defaults.models
        providers = Get-ValueHash $Config.models.providers
        ninerouter = Get-ValueHash ([pscustomobject]@{
            provider = $Config.models.providers.ninerouter
            secret_provider = $Config.secrets.providers.ninerouter_key_file
        })
    }
}

try {
    $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8790/health" -TimeoutSec 5
    Add-Check "core_health" ($health.StatusCode -eq 200) "HTTP $($health.StatusCode)"
} catch {
    Add-Check "core_health" $false "unreachable"
}

try {
    $ready = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8790/ready" -TimeoutSec 5
    Add-Check "core_ready" ($ready.StatusCode -eq 200) "HTTP $($ready.StatusCode)"
} catch {
    Add-Check "core_ready" $false "unreachable"
}

$mainPid = (& wsl.exe -d Ubuntu -- systemctl show -p MainPID --value anh-duong-core.service).Trim()
$activeState = (& wsl.exe -d Ubuntu -- systemctl is-active anh-duong-core.service).Trim()
Add-Check "core_service" ($activeState -eq "active" -and $mainPid -match "^\d+$" -and $mainPid -ne "0") $activeState

$workerFilter = "tr '\000' '\n' < /proc/$mainPid/environ | sed -n 's/^ANH_DUONG_ASYNC_WORKER_ENABLED=//p'"
$workerValue = (& wsl.exe -d Ubuntu -- sh -c $workerFilter).Trim()
Add-Check "async_worker_disabled" ($workerValue -eq "false") "value=$workerValue"

$alembicOutput = (& wsl.exe -d Ubuntu -- sh -lc "cd /mnt/f/AIOS/anh-duong-core && .venv/bin/alembic current" 2>&1) -join "`n"
Add-Check "alembic_head" ($alembicOutput -match "0003 \(head\)") "0003 (head)"

$inspect = (docker inspect $container | ConvertFrom-Json)[0]
Add-Check "gateway_running" ([string]$inspect.State.Status -eq "running") ([string]$inspect.State.Status)
Add-Check "gateway_healthy" ([string]$inspect.State.Health.Status -eq "healthy") ([string]$inspect.State.Health.Status)
Add-Check "gateway_image_immutable" ([string]$inspect.Image -eq $ExpectedImageId) ([string]$inspect.Image)

$runtimeVersion = (& docker exec $container node -p "require('/app/package.json').version").Trim()
Add-Check "openclaw_version" ($runtimeVersion -eq "2026.7.1") $runtimeVersion

$coreFromGateway = (& docker exec $container node -e "fetch('http://host.docker.internal:8790/health').then(r=>process.stdout.write(String(r.status))).catch(()=>process.stdout.write('000'))").Trim()
Add-Check "core_reachable_from_gateway" ($coreFromGateway -eq "200") "HTTP $coreFromGateway"

$coreTokenFilter = "tr '\000' '\n' < /proc/$mainPid/environ | sed -n 's/^ANH_DUONG_INTERNAL_API_TOKEN=//p'"
$coreToken = & wsl.exe -d Ubuntu -- sh -c $coreTokenFilter
$gatewayToken = & docker exec $container node -e "process.stdout.write(process.env.ANH_DUONG_CORE_INTERNAL_TOKEN || '')"
Add-Check "internal_token_match" (-not [string]::IsNullOrEmpty($coreToken) -and $coreToken -ceq $gatewayToken) "matched=$($coreToken -ceq $gatewayToken)"

$runtimeRaw = & docker exec $container sh -lc "cd /app && node openclaw.mjs plugins inspect anh-duong-core --runtime --json"
$runtime = ($runtimeRaw -join "`n") | ConvertFrom-Json -Depth 40
$hookNames = @($runtime.typedHooks.name | Sort-Object)
$expectedHooks = @("agent_end", "before_agent_run", "before_prompt_build")
Add-Check "plugin_loaded" ($runtime.plugin.status -eq "loaded" -and $runtime.plugin.activated -eq $true) "status=$($runtime.plugin.status)"
Add-Check "plugin_three_hooks" (($hookNames -join ",") -eq ($expectedHooks -join ",")) ($hookNames -join ",")
Add-Check "plugin_no_diagnostics" (@($runtime.diagnostics).Count -eq 0) "count=$(@($runtime.diagnostics).Count)"
Add-Check "plugin_scope_minimal" ($runtime.plugin.toolNames.Count -eq 0 -and $runtime.plugin.channelIds.Count -eq 0 -and $runtime.plugin.httpRoutes -eq 0) "tools=0,channels=0,http=0"
Add-Check "plugin_conversation_policy" ($runtime.policy.allowConversationAccess -eq $true) "allowConversationAccess=true"

$telegramRaw = & docker exec $container sh -lc "cd /app && node openclaw.mjs channels status --probe --json"
$telegramJson = ($telegramRaw -join "`n") | ConvertFrom-Json -Depth 40
$telegram = $telegramJson.channels.telegram
Add-Check "telegram_configured" ($telegram.configured -eq $true) "configured=$($telegram.configured)"
Add-Check "telegram_running" ($telegram.running -eq $true) "running=$($telegram.running)"
Add-Check "telegram_probe" ($telegram.probe.ok -eq $true -and [string]::IsNullOrEmpty([string]$telegram.error)) "probe_ok=$($telegram.probe.ok),mode=$($telegram.mode)"

$backupConfig = Get-Content -Raw -LiteralPath $BackupConfigPath | ConvertFrom-Json -Depth 100
$liveConfigRaw = & docker exec $container sh -lc "cat /home/node/.openclaw/openclaw.json"
$liveConfig = ($liveConfigRaw -join "`n") | ConvertFrom-Json -Depth 100
$beforeHashes = Get-ProtectedHashes $backupConfig
$afterHashes = Get-ProtectedHashes $liveConfig
foreach ($key in $beforeHashes.Keys) {
    Add-Check "protected_hash_$key" ($beforeHashes[$key] -eq $afterHashes[$key]) $afterHashes[$key]
}

$failed = @($results | Where-Object { -not $_.passed })
[pscustomobject]@{
    verdict = if ($failed.Count -eq 0) { "PASS" } else { "FAIL" }
    passed = $results.Count - $failed.Count
    failed = $failed.Count
    checks = $results
} | ConvertTo-Json -Depth 6

if ($failed.Count -ne 0) { exit 1 }
