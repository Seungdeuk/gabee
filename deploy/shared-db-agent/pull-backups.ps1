<#
.SYNOPSIS
  개발 PC 에서 공용 DB PC 의 자동 배포 백업을 가져온다(복사만 한다 — 아무것도 삭제하지 않는다).

.DESCRIPTION
  공용 DB PC 에서 백업 폴더를 "읽기 전용" 공유로 한 번 열어 두면(README 참고) 개발 PC 가 이 스크립트로 당겨 받는다.
  받은 파일은 기존 백업 폴더(예: gabee-backups)와 섞이지 않게 하위 폴더(shared-db)에 둔다.
  robocopy /E /XO 만 사용한다(/MIR·/PURGE 없음) — 원본/대상 어느 쪽 파일도 지우지 않는다.

.EXAMPLE
  .\pull-backups.ps1 -ListOnly      # 무엇을 가져올지 목록만
  .\pull-backups.ps1
#>
[CmdletBinding()]
param(
    [string]$Source = "\\192.168.0.44\gabee-deploy-backups",
    [string]$Destination = "$env:USERPROFILE\Documents\gabee-backups\shared-db",
    [switch]$ListOnly
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Source)) { throw "공유 폴더에 접근할 수 없습니다: $Source (공용 DB PC 에서 읽기 전용 공유를 만들었는지 확인)" }
if (-not $ListOnly) { New-Item -ItemType Directory -Force -Path $Destination | Out-Null }

$roboArgs = @($Source, $Destination, "gabee_pg16_deploy_*.dump", "gabee_pg16_deploy_*.dump.sha256", "/E", "/XO", "/R:2", "/W:5", "/NP", "/NDL")
if ($ListOnly) { $roboArgs += "/L" }
robocopy @roboArgs
# robocopy 종료 코드 0~7 은 성공(복사 있음/없음 포함), 8 이상이 오류
if ($LASTEXITCODE -ge 8) { throw "robocopy 오류(코드 $LASTEXITCODE)" }

if (-not $ListOnly) {
    # 해시 검증: .sha256 파일의 값과 실제 파일 해시가 같은지 확인
    Get-ChildItem $Destination -Filter "gabee_pg16_deploy_*.dump" | ForEach-Object {
        $sumFile = "$($_.FullName).sha256"
        if (Test-Path $sumFile) {
            $expected = ((Get-Content $sumFile -Raw).Trim() -split "\s+")[0]
            $actual = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
            $mark = if ($expected -eq $actual) { "OK" } else { "불일치!" }
            Write-Host ("  [{0}] {1}" -f $mark, $_.Name)
        }
    }
}
exit 0
