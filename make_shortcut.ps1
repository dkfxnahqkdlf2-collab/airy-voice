[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$CurrentDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$WshShell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $Desktop "쇼츠 보이스 & 캡션 스튜디오.lnk"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $CurrentDir "run_voice_studio.bat"
$Shortcut.WorkingDirectory = $CurrentDir

$IconPath = Join-Path $CurrentDir "app_icon.ico"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
}

$Shortcut.Save()

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " [성공] 바탕화면에 '쇼츠 보이스 & 캡션 스튜디오' 바로가기가 생성되었습니다!" -ForegroundColor Green
Write-Host " (전용 스튜디오 마이크 아이콘이 적용되었습니다)" -ForegroundColor Yellow
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
