<#
.SYNOPSIS
  공용 DB PC(192.168.0.44)에 Pull Agent 를 설치한다. 최초 1회, "관리자 권한 PowerShell" 에서 실행.

.DESCRIPTION
  - 배포 폴더(DB 데이터·Docker 볼륨과 분리)에 클론·파이썬 가상환경·고정된 배포 도구(agent\)·비밀 폴더를 만든다.
  - 비밀(깃허브 읽기 토큰, gabee_migrator 비밀번호)은 프롬프트로 받아 파일에만 쓴다(명령줄·로그에 남지 않음).
  - 5분마다 실행되는 작업 스케줄러 작업(GabeeSharedDbDeployAgent)을 등록한다. 에이전트는 기본 "비활성"으로 설치된다.
  - 공용 DB 를 바꾸지 않는다. 활성화는 설치 후 agent.env 의 값을 직접 바꿔서 한다.
  - -DryRun 이면 확인만 하고 아무것도 만들거나 바꾸지 않는다.

.EXAMPLE
  .\install.ps1 -DryRun
  .\install.ps1 -DeployHome D:\gabee-deploy
#>
[CmdletBinding()]
param(
    [string]$DeployHome = "D:\gabee-deploy",
    [string]$BackupDir = "",
    [string]$Repo = "kangminhun/gabee",
    [int]$IntervalMinutes = 5,
    # Docker Desktop 을 실행하는 Windows 계정. 작업은 이 계정으로 실행된다(Docker Desktop 은 로그인한 계정에서 동작).
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
if (-not $BackupDir) { $BackupDir = Join-Path $DeployHome "backups" }
$TaskName = "GabeeSharedDbDeployAgent"

function Step($text) { Write-Host "[설치] $text" -ForegroundColor Cyan }
function Do-Or-Print($text, [scriptblock]$action) {
    if ($DryRun) { Write-Host "  (dry-run) $text" -ForegroundColor DarkGray } else { & $action }
}

# 1) 사전 확인 ---------------------------------------------------------------
Step "사전 확인"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $DryRun) { throw "관리자 권한 PowerShell 에서 실행하세요(폴더 권한·작업 등록에 필요)." }

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
$tokenFile = Join-Path $DeployHome "secrets\github-token"
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

# 4) 저장소 클론(읽기 전용 토큰은 환경변수로만 git 에 전달) + 가상환경 + 의존성 ---------
Step "저장소 클론과 파이썬 환경"
$repoDir = Join-Path $DeployHome "repo"
$venv = Join-Path $DeployHome "venv"
Do-Or-Print "git clone https://github.com/$Repo.git → $repoDir; venv; pip install -e repo\apps\api" {
    $tokenText = (Get-Content $tokenFile -Raw).Trim()
    $basic = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("x-access-token:$tokenText"))
    $env:GIT_TERMINAL_PROMPT = "0"; $env:GIT_CONFIG_COUNT = "1"
    $env:GIT_CONFIG_KEY_0 = "http.https://github.com/.extraheader"; $env:GIT_CONFIG_VALUE_0 = "AUTHORIZATION: basic $basic"
    try {
        if (-not (Test-Path (Join-Path $repoDir ".git"))) { git clone --depth 100 --branch main "https://github.com/$Repo.git" $repoDir }
        else { git -C $repoDir fetch --depth 100 origin main; git -C $repoDir checkout --detach --force FETCH_HEAD }
    } finally { Remove-Item Env:GIT_CONFIG_COUNT, Env:GIT_CONFIG_KEY_0, Env:GIT_CONFIG_VALUE_0 -ErrorAction SilentlyContinue }
    if (-not (Test-Path $venv)) { python -m venv $venv }
    & (Join-Path $venv "Scripts\python.exe") -m pip install -q -e (Join-Path $repoDir "apps\api")
}

# 5) 배포 도구 고정(검토) -----------------------------------------------------
Step "배포 도구 고정(bless) — 관리자가 코드를 검토한 뒤에만"
$envFile = Join-Path $DeployHome "agent.env"
Do-Or-Print "agent.env 작성(기본 비활성)" {
    @(
        "GABEE_AGENT_ENABLED=false", "GABEE_AGENT_APPLY=false", "GABEE_REPO=$Repo",
        "GABEE_DEPLOY_HOME=$DeployHome", "GABEE_BACKUP_DIR=$BackupDir",
        "GABEE_PGPASS=$pgpass", "GABEE_TOKEN_FILE=$tokenFile"
    ) | Set-Content -Path $envFile -Encoding UTF8
}
if (-not $DryRun) {
    $tip = (git -C $repoDir rev-parse HEAD).Trim()
    Write-Host "  검토 대상 main 커밋: $tip"
    Write-Host "  배포 도구: apps\api\scripts\deploy_agent.py, shared_db_deploy.py, migration_risk.py / apps\api\alembic\env.py"
    $answer = Read-Host "  위 파일들을 검토했습니까? 검토했다면 yes 입력"
    if ($answer -ne "yes") { throw "검토 확인이 없어 중단합니다(설치된 파일은 그대로 두었습니다. 다시 실행하면 이어서 진행)." }
    foreach ($name in "deploy_agent.py", "shared_db_deploy.py", "migration_risk.py") {
        Copy-Item (Join-Path $repoDir "apps\api\scripts\$name") (Join-Path $DeployHome "agent\$name") -Force
    }
    & (Join-Path $venv "Scripts\python.exe") (Join-Path $DeployHome "agent\deploy_agent.py") --env-file $envFile bless --sha $tip --yes
} else { Write-Host "  (dry-run) 검토 확인 후 agent\ 에 도구 복사 및 bless" -ForegroundColor DarkGray }

# 6) 작업 스케줄러 등록 --------------------------------------------------------
Step "작업 스케줄러 등록: $TaskName (${IntervalMinutes}분마다, 부팅·로그온 시 재개)"
Do-Or-Print "Register-ScheduledTask $TaskName" {
    $python = Join-Path $venv "Scripts\python.exe"
    $script = Join-Path $DeployHome "agent\deploy_agent.py"
    $action = New-ScheduledTaskAction -Execute $python -Argument "`"$script`" run-once" -WorkingDirectory $DeployHome
    $triggers = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $RunAsUser),
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650))
    )
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -Priority 7
    $principal = New-ScheduledTaskPrincipal -UserId $RunAsUser -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Force | Out-Null
}

Write-Host ""
Write-Host "설치 완료 — 에이전트는 비활성 상태입니다. 다음 단계는 deploy\shared-db-agent\README.md 의 '활성화' 절을 따르세요." -ForegroundColor Green
if ($DryRun) { Write-Host "(dry-run: 실제로는 아무것도 만들거나 바꾸지 않았습니다)" -ForegroundColor Yellow }
