<#
.SYNOPSIS
  공용 DB PC(192.168.0.44)에 Pull Agent 를 설치한다. 최초 1회, "관리자 권한 PowerShell" 에서 실행.

.DESCRIPTION
  순서: ① main 최신 커밋 SHA 확인 → ② 그 SHA 로 고정 → ③ 체크아웃해 검토할 내용 표시 → ④ 사람이 SHA 를 입력해 검토 확인
  → ⑤ 확인한 SHA 의 배포 도구를 agent\ 에 고정 → ⑥ 의존성 설치 → ⑦ 신뢰 파일 해시 기록(bless)·검증 → 작업 스케줄러 등록.
  - 검토 전에는 저장소 코드를 실행하지 않는다. 체크아웃·의존성 설치·bless 는 실행 계정의 *비관리자* 권한으로 한다
    (일회용 작업 스케줄러 작업 GabeeSharedDbDeployAgent-Setup, RunLevel Limited — 실행 계정이 로그인해 있어야 한다).
  - 검토와 설치 사이에 main 이 바뀌어도 고정한 SHA 만 설치한다(그 SHA 가 main 이력에 없으면 중단).
  - 어느 단계든 실패하면 작업 스케줄러를 등록하지 않는다. 에이전트는 항상 "비활성"(ENABLED/APPLY=false)으로 설치된다.
  - 비밀(깃허브 읽기 토큰, gabee_migrator 비밀번호)은 프롬프트로 받아 파일에만 쓴다(명령줄·로그에 남지 않음).
  - 공용 DB 를 바꾸지 않는다. -DryRun 이면 확인만 하고 아무것도 만들거나 바꾸지 않는다.

.EXAMPLE
  .\install.ps1 -DryRun -DeployHome C:\gabee-deploy
  .\install.ps1 -DeployHome C:\gabee-deploy
#>
[CmdletBinding()]
param(
    [string]$DeployHome = "D:\gabee-deploy",
    [string]$BackupDir = "",
    [string]$Repo = "kangminhun/gabee",
    [string]$GitUrl = "",
    [int]$IntervalMinutes = 5,
    # Docker Desktop 을 실행하는 Windows 계정. 작업은 이 계정으로 실행된다(Docker Desktop 은 로그인한 계정에서 동작).
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME",
    # 설치할 main 커밋(생략하면 시작 시점의 main 최신 커밋으로 고정)
    [string]$Sha = "",
    # 내부용: 비관리자 권한으로 실행되는 단계(Checkout, Deps)
    [ValidateSet("", "Checkout", "Deps")]
    [string]$Stage = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
if (-not $BackupDir) { $BackupDir = Join-Path $DeployHome "backups" }
if (-not $GitUrl) { $GitUrl = "https://github.com/$Repo.git" }
$TaskName = "GabeeSharedDbDeployAgent"
$repoDir = Join-Path $DeployHome "repo"
$venv = Join-Path $DeployHome "venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
$envFile = Join-Path $DeployHome "agent.env"
$tokenFile = Join-Path $DeployHome "secrets\github-token"
$agentPy = Join-Path $DeployHome "agent\deploy_agent.py"
$toolNames = @("deploy_agent.py", "shared_db_deploy.py", "migration_risk.py")

function Step($text) { Write-Host "[설치] $text" -ForegroundColor Cyan }
function Do-Or-Print($text, [scriptblock]$action) {
    if ($DryRun) { Write-Host "  (dry-run) $text" -ForegroundColor DarkGray } else { & $action }
}
function Test-Admin {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}
# 읽기 전용 토큰은 환경변수로만 git 에 전달한다(명령줄·프로세스 목록에 나타나지 않음)
function Invoke-Git([string[]]$GitArgs, [switch]$Auth) {
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $env:GIT_TERMINAL_PROMPT = "0"
    if ($Auth -and $GitUrl.StartsWith("https://github.com/")) {
        $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("x-access-token:" + (Get-Content $tokenFile -Raw).Trim()))
        $env:GIT_CONFIG_COUNT = "1"; $env:GIT_CONFIG_KEY_0 = "http.https://github.com/.extraheader"; $env:GIT_CONFIG_VALUE_0 = "AUTHORIZATION: basic $basic"
    }
    try { $out = & git @GitArgs; $code = $LASTEXITCODE }
    finally { Remove-Item Env:GIT_CONFIG_COUNT, Env:GIT_CONFIG_KEY_0, Env:GIT_CONFIG_VALUE_0 -ErrorAction SilentlyContinue; $ErrorActionPreference = $old }
    if ($code -ne 0) { throw "git $($GitArgs[2]) 실패(코드 $code)" }
    return $out
}
function Assert-Sha { if ($Sha -notmatch '^[0-9a-f]{40}$') { throw "설치 대상 SHA 가 올바르지 않습니다: '$Sha'" } }

# ---- 비관리자 단계 1: 고정한 SHA 를 체크아웃하고 검토할 내용을 보여 준다(코드는 실행하지 않음) ----
function Invoke-CheckoutStage {
    Assert-Sha
    New-Item -ItemType Directory -Force -Path $repoDir | Out-Null
    if (-not (Test-Path (Join-Path $repoDir ".git"))) {
        Invoke-Git @("-C", $repoDir, "init", "-q") | Out-Null
        Invoke-Git @("-C", $repoDir, "remote", "add", "origin", $GitUrl) | Out-Null
    } else { Invoke-Git @("-C", $repoDir, "remote", "set-url", "origin", $GitUrl) | Out-Null }
    Invoke-Git @("-C", $repoDir, "fetch", "--no-tags", "--quiet", "--depth", "100", "origin", "main") -Auth | Out-Null
    Invoke-Git @("-C", $repoDir, "cat-file", "-e", "$Sha^{commit}") | Out-Null
    Invoke-Git @("-C", $repoDir, "merge-base", "--is-ancestor", $Sha, "FETCH_HEAD") | Out-Null  # main 이력의 커밋만
    Invoke-Git @("-C", $repoDir, "checkout", "--detach", "--force", "--quiet", $Sha) | Out-Null
    Invoke-Git @("-C", $repoDir, "clean", "-ffdxq") | Out-Null
    if ((Invoke-Git @("-C", $repoDir, "rev-parse", "HEAD")) -ne $Sha) { throw "체크아웃이 고정한 SHA 와 다릅니다" }

    Write-Host "커밋: $((Invoke-Git @('-C', $repoDir, 'log', '-1', '--format=%H  %ci  %an  %s')) -join ' ')"
    Write-Host "웹에서 보기: https://github.com/$Repo/tree/$Sha"
    $paths = @("apps/api/scripts/deploy_agent.py", "apps/api/scripts/shared_db_deploy.py", "apps/api/scripts/migration_risk.py",
        "apps/api/alembic/env.py", "apps/api/alembic.ini", "apps/api/scripts/check_schema_matches_models.py",
        "apps/api/pyproject.toml", "apps/api/app/shared", "apps/api/app/__init__.py")
    Write-Host "검토할 파일(자격증명으로 실행되는 배포 코드·의존성):"; $paths | ForEach-Object { Write-Host "  $_" }
    $state = Join-Path $DeployHome "state\agent-state.json"
    $prev = if (Test-Path $state) { (Get-Content $state -Raw | ConvertFrom-Json).blessed_sha } else { $null }
    if ($prev -and $prev -ne $Sha) {
        Write-Host "이전에 검토한 커밋 $($prev.Substring(0, 12)) 이후 바뀐 배포 코드:"
        try { Invoke-Git (@("-C", $repoDir, "diff", "--stat", $prev, $Sha, "--") + $paths) | ForEach-Object { Write-Host "  $_" } }
        catch { Write-Host "  (이전 커밋을 찾을 수 없어 비교하지 못함 — 위 파일 전체를 검토하세요)" }
    }
    foreach ($build in "setup.py", "setup.cfg") {
        if (Test-Path (Join-Path $repoDir "apps\api\$build")) { Write-Host "  주의: apps/api/$build 가 있습니다(설치 시 실행되는 빌드 코드 — 반드시 검토)" }
    }
    Write-Host "--- apps/api/pyproject.toml (설치될 의존성·빌드 설정) ---"
    Get-Content (Join-Path $repoDir "apps\api\pyproject.toml") | ForEach-Object { Write-Host "  $_" }
}

# ---- 비관리자 단계 2: 의존성 설치 → 신뢰 기록(bless) → 검증 ----
function Invoke-DepsStage {
    Assert-Sha
    if ((Invoke-Git @("-C", $repoDir, "rev-parse", "HEAD")) -ne $Sha) { throw "체크아웃이 검토한 SHA 와 다릅니다" }
    if (Invoke-Git @("-C", $repoDir, "status", "--porcelain")) { throw "체크아웃에 검토 후 바뀐 파일이 있습니다" }
    if (-not (Test-Path $venvPy)) {
        & python -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "가상환경 생성 실패" }
    }
    & $venvPy -m pip install --disable-pip-version-check -q -e (Join-Path $repoDir "apps\api")
    if ($LASTEXITCODE -ne 0) { throw "의존성 설치 실패(코드 $LASTEXITCODE) — 신뢰 기록을 하지 않았으므로 에이전트는 held 로 멈춥니다" }
    & $venvPy $agentPy --env-file $envFile bless --sha $Sha --yes
    if ($LASTEXITCODE -ne 0) { throw "신뢰 기록(bless) 실패(코드 $LASTEXITCODE)" }
    & $venvPy $agentPy --env-file $envFile check --sha $Sha
    if ($LASTEXITCODE -ne 0) { throw "설치 확인(check) 실패(코드 $LASTEXITCODE)" }
}

if ($Stage) {
    try {
        if (Test-Admin) { throw "이 단계는 관리자 권한 없이 실행해야 합니다" }
        if ($Stage -eq "Checkout") { Invoke-CheckoutStage } else { Invoke-DepsStage }
        exit 0
    } catch { Write-Host "[실패] $_"; exit 1 }
}

# 이 스크립트의 한 단계를 실행 계정의 비관리자 권한으로 실행한다(일회용 작업 스케줄러 작업, 끝나면 삭제)
function Invoke-AsRunUser([string]$StageName) {
    $log = Join-Path $DeployHome "logs\install-$($StageName.ToLower()).log"
    Remove-Item $log -ErrorAction SilentlyContinue
    $setupTask = "$TaskName-Setup"
    $psArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Stage $StageName -DeployHome `"$DeployHome`" -Repo $Repo -GitUrl `"$GitUrl`" -Sha $Sha"
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/d /s /c `"powershell.exe $psArgs > `"$log`" 2>&1`"" -WorkingDirectory $DeployHome
    $principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $setupTask -Action $action -Principal $principal -Settings $settings -Force | Out-Null
    try {
        Start-ScheduledTask -TaskName $setupTask
        $deadline = (Get-Date).AddMinutes(65)
        do { Start-Sleep -Seconds 3 } while ((Get-ScheduledTask -TaskName $setupTask).State -ne "Ready" -and (Get-Date) -lt $deadline)
        $code = (Get-ScheduledTaskInfo -TaskName $setupTask).LastTaskResult
    } finally { Unregister-ScheduledTask -TaskName $setupTask -Confirm:$false }
    if (Test-Path $log) { Get-Content $log | ForEach-Object { Write-Host "  $_" } }
    if ($code -ne 0) { throw "$StageName 단계 실패(결과 코드 $code, 로그 $log). 작업 스케줄러는 등록하지 않았습니다. 원인을 해결하고 다시 실행하세요." }
}

# 1) 사전 확인 ---------------------------------------------------------------
Step "사전 확인"
if (-not (Test-Admin) -and -not $DryRun) { throw "관리자 권한 PowerShell 에서 실행하세요(폴더 권한·작업 등록에 필요)." }

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) { throw "docker 를 찾을 수 없습니다. 이 PC 는 PostgreSQL 을 Docker 로 운영하므로 Docker Desktop 이 필요합니다." }
$null = docker version --format "{{.Server.Version}}" 2>$null
if ($LASTEXITCODE -ne 0) { throw "Docker 엔진에 연결할 수 없습니다. Docker Desktop 을 실행한 계정으로 실행하세요." }

$git = Get-Command git -ErrorAction SilentlyContinue
if (-not $git) { throw "git 이 필요합니다." }
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python 3.12 이상이 필요합니다(python 명령을 찾을 수 없음)." }
$pyVersion = [version](& python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))")
if ($pyVersion -lt [version]"3.12") { throw "Python 3.12 이상이 필요합니다(현재 $pyVersion)." }

$freeGb = [math]::Round((Get-PSDrive -Name ($DeployHome.Substring(0,1))).Free / 1GB, 1)
Write-Host "  Docker $(docker version --format '{{.Server.Version}}'), Python $pyVersion, 배포 드라이브 여유 ${freeGb}GB"
if ($freeGb -lt 5) { throw "배포 드라이브의 여유 공간이 5GB 미만입니다." }
$pgData = docker ps --format "{{.Names}} {{.Ports}}" | Select-String "5432"
Write-Host "  PostgreSQL 컨테이너: $(if ($pgData) { ($pgData | Select-Object -First 1).Line } else { '(5432 를 게시한 컨테이너를 찾지 못함 — 확인 필요)' })"

# 2) 폴더와 권한 -------------------------------------------------------------
Step "폴더 생성과 권한 (실행 계정: $RunAsUser)"
$dirs = @("agent", "repo", "state", "logs", "secrets") | ForEach-Object { Join-Path $DeployHome $_ }
Do-Or-Print "폴더 생성: $DeployHome, $BackupDir" {
    New-Item -ItemType Directory -Force -Path $DeployHome, $BackupDir | Out-Null
    $dirs | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
    # 상속을 끊고 관리자·SYSTEM·실행 계정만 접근. agent\ 와 secrets\ 는 실행 계정이 읽기만(고정된 도구·비밀 변조 방지)
    foreach ($path in @($DeployHome, $BackupDir)) {
        icacls $path /inheritance:r /grant:r "${RunAsUser}:(OI)(CI)M" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
    }
    foreach ($ro in @("agent", "secrets")) {
        icacls (Join-Path $DeployHome $ro) /inheritance:r /grant:r "${RunAsUser}:(OI)(CI)RX" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
    }
}

# 3) 비밀(프롬프트 입력 → 파일. 화면·로그·명령줄에 남지 않음) ---------------------
function Read-Secret($prompt) {
    $secure = Read-Host $prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
}
Step "비밀 저장"
$pgpass = Join-Path $DeployHome "secrets\pgpass"
Do-Or-Print "pgpass 와 토큰 파일 작성" {
    if (-not (Test-Path $tokenFile)) {
        Write-Host "  GitHub 읽기 전용 토큰(fine-grained, 이 저장소 한정: Contents 읽기, Actions 읽기, Metadata 읽기, Issues 쓰기)"
        $token = Read-Secret "  토큰 입력(화면에 표시되지 않음)"
        [IO.File]::WriteAllText($tokenFile, $token.Trim(), (New-Object Text.UTF8Encoding($false)))
    }
    if (-not (Test-Path $pgpass)) {
        $pw = Read-Secret "  gabee_migrator 비밀번호 입력(화면에 표시되지 않음)"
        [IO.File]::WriteAllText($pgpass, "192.168.0.44:5432:gabee:gabee_migrator:$pw`n", (New-Object Text.UTF8Encoding($false)))
    }
    foreach ($f in @($tokenFile, $pgpass)) { icacls $f /inheritance:r /grant:r "${RunAsUser}:R" "SYSTEM:F" "Administrators:F" | Out-Null }
}

Step "agent.env 작성(항상 비활성으로 시작)"
Do-Or-Print "agent.env: GABEE_AGENT_ENABLED=false, GABEE_AGENT_APPLY=false" {
    $lines = @(
        "GABEE_AGENT_ENABLED=false", "GABEE_AGENT_APPLY=false", "GABEE_REPO=$Repo",
        "GABEE_DEPLOY_HOME=$DeployHome", "GABEE_BACKUP_DIR=$BackupDir",
        "GABEE_PGPASS=$pgpass", "GABEE_TOKEN_FILE=$tokenFile"
    )
    if ($GitUrl -ne "https://github.com/$Repo.git") { $lines += "GABEE_GIT_URL=$GitUrl" }
    $lines | Set-Content -Path $envFile -Encoding UTF8
}

# 4) 설치 대상 SHA 고정 → 체크아웃 → 검토 확인 ----------------------------------
Step "① main 최신 커밋 확인 ② 설치 대상 SHA 고정"
Do-Or-Print "git ls-remote 로 main 최신 SHA 를 확인해 이후 모든 단계에서 그 SHA 만 사용" {
    if (-not $Sha) {
        $line = Invoke-Git @("-C", $DeployHome, "ls-remote", $GitUrl, "refs/heads/main") -Auth
        $script:Sha = (($line | Select-Object -First 1) -split "\s+")[0]
    }
    Assert-Sha
    Write-Host "  설치 대상 커밋: $Sha"
}
Step "③ 고정한 SHA 체크아웃과 검토 내용 (관리자 권한 없이)"
Do-Or-Print "비관리자 단계 Checkout: fetch main → SHA 가 main 이력에 있는지 확인 → 그 SHA 체크아웃 → 검토 정보 표시" {
    Invoke-AsRunUser "Checkout"
}
Step "④ 검토 확인"
Do-Or-Print "위 파일들을 검토한 뒤 설치 대상 SHA 앞 12자리를 직접 입력해야 진행" {
    $answer = Read-Host "  위 파일들을 검토했다면 설치 대상 커밋의 앞 12자리를 입력($($Sha.Substring(0, 4))...)"
    if ($answer.Trim() -ne $Sha.Substring(0, 12)) { throw "검토 확인이 SHA 와 일치하지 않아 중단합니다(설치된 파일은 그대로 두었습니다. 다시 실행하면 이어서 진행)." }
}

# 5) 확인한 SHA 의 배포 도구 고정 → 의존성 설치·신뢰 기록·검증 → 작업 등록 ---------------------
Step "⑤ 확인한 SHA 의 배포 도구를 agent\ 에 고정"
Do-Or-Print "agent\ 에 deploy_agent.py, shared_db_deploy.py, migration_risk.py 복사(체크아웃 HEAD 가 SHA 인지 먼저 확인)" {
    # 저장소 코드를 관리자 권한으로 실행하지 않도록 git 대신 HEAD 파일을 직접 읽는다
    if ((Get-Content (Join-Path $repoDir ".git\HEAD") -Raw).Trim() -ne $Sha) { throw "체크아웃이 검토한 SHA 와 다릅니다" }
    Remove-Item (Join-Path $DeployHome "state\trust.json") -ErrorAction SilentlyContinue  # 끝까지 성공해야 다시 생긴다
    foreach ($name in $toolNames) {
        Copy-Item (Join-Path $repoDir "apps\api\scripts\$name") (Join-Path $DeployHome "agent\$name") -Force
    }
}
Step "⑥ 의존성 설치 ⑦ 신뢰 파일 해시 기록·검증 (관리자 권한 없이)"
Do-Or-Print "비관리자 단계 Deps: 체크아웃이 SHA 그대로인지 확인 → pip install -e → bless --sha → check --sha" {
    Invoke-AsRunUser "Deps"
}

Step "작업 스케줄러 등록: $TaskName (${IntervalMinutes}분마다, 부팅·로그온 시 재개) — 위 단계가 모두 성공했을 때만"
Do-Or-Print "Register-ScheduledTask $TaskName" {
    $script = Join-Path $DeployHome "agent\deploy_agent.py"
    $action = New-ScheduledTaskAction -Execute $venvPy -Argument "`"$script`" run-once" -WorkingDirectory $DeployHome
    $triggers = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $RunAsUser),
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650))
    )
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -Priority 7
    $principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
}

Write-Host ""
Write-Host "설치 완료 — 에이전트는 비활성 상태입니다$(if ($Sha) { "(설치 커밋 $Sha)" }). 다음 단계는 deploy\shared-db-agent\README.md 의 '활성화' 절을 따르세요." -ForegroundColor Green
if ($DryRun) { Write-Host "(dry-run: 실제로는 아무것도 만들거나 바꾸지 않았습니다)" -ForegroundColor Yellow }
