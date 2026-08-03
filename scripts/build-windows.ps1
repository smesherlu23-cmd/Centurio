<#
.SYNOPSIS
    Собрать Centurio для прода: тесты, flet build, инсталлятор Inno Setup.

.DESCRIPTION
    Повторяет то, что описано в README ("Сборка Windows-инсталлятора") и что
    делает workflow Build Windows installer, одной командой. В конце
    откладывает в сторону %APPDATA%\Centurio, если она есть на этой машине —
    иначе собранный .exe при первом запуске для проверки открылся бы с той
    библиотекой, что накопилась за разработку, а не пустым, как у нового
    пользователя.

.PARAMETER KeepData
    Не трогать %APPDATA%\Centurio. Без этого флага существующая папка
    переименовывается в Centurio.before-build-<время>, а не удаляется —
    ничего не пропадает, просто убирается с дороги.

.PARAMETER SkipTests
    Не гонять тесты перед сборкой. Тест-сьют не про Windows-специфику
    (флаг существует на случай, если он уже прогнан отдельно), а не про
    доверие к результату по умолчанию.

.EXAMPLE
    .\scripts\build-windows.ps1
    Тесты -> flet build windows -> инсталлятор -> чистая библиотека для проверки.
#>
param(
    [switch]$KeepData,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    Write-Error "flet build windows и Inno Setup собираются только на Windows."
    exit 1
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    Write-Host "== Зависимости для сборки ==" -ForegroundColor Cyan
    pip install "flet[all]==0.28.3"
    if ($LASTEXITCODE -ne 0) { throw "pip install flet[all] завершился с ошибкой." }

    if (-not $SkipTests) {
        Write-Host "== Тесты ==" -ForegroundColor Cyan
        python tests/test_centurio.py
        if ($LASTEXITCODE -ne 0) {
            throw "Тесты не прошли — сборка остановлена. Пропустить: -SkipTests."
        }
    }

    Write-Host "== flet build windows ==" -ForegroundColor Cyan
    flet build windows -v
    if ($LASTEXITCODE -ne 0) { throw "flet build windows завершился с ошибкой." }

    Write-Host "== Инсталлятор (Inno Setup) ==" -ForegroundColor Cyan
    $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $iscc)) {
        throw "Не нашёл $iscc. Поставить: choco install innosetup, " +
              "или указать свой путь прямо в этом скрипте."
    }
    & $iscc "installer\centurio.iss"
    if ($LASTEXITCODE -ne 0) { throw "ISCC завершился с ошибкой." }

    if (-not $KeepData) {
        $dataDir = Join-Path $env:APPDATA "Centurio"
        if (Test-Path $dataDir) {
            $asideName = "Centurio.before-build-{0}" -f (Get-Date -Format "yyyyMMdd-HHmmss")
            Write-Host "== Откладываю $dataDir в сторону ($asideName) ==" -ForegroundColor Cyan
            Rename-Item -Path $dataDir -NewName $asideName
        }
    }

    Write-Host ""
    Write-Host "Готово." -ForegroundColor Green
    Write-Host "  Приложение:  $repoRoot\build\windows"
    Write-Host "  Инсталлятор: $repoRoot\installer\Output\CenturioSetup.exe"
    if (-not $KeepData) {
        Write-Host "  Библиотека для первого запуска пустая — как у нового пользователя."
    }
}
finally {
    Pop-Location
}
