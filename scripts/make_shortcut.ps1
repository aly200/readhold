# Creates "Readhold" shortcuts with the app logo: one on your desktop and one in the Start menu
# (so you can also pin it to the taskbar: right-click it in Start -> Pin to taskbar).
# They start the app with pythonw, so no console window opens.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File scripts\make_shortcut.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
$launcher = Join-Path $root "Readhold.pyw"
$icon = Join-Path $root "assets\readhold.ico"

if (-not (Test-Path $pythonw)) {
    Write-Host "No virtual environment yet. Run 'uv sync' in $root first, then run this script again."
    exit 1
}

$shell = New-Object -ComObject WScript.Shell
$places = @(
    [Environment]::GetFolderPath("Desktop"),
    (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs")
)
foreach ($dir in $places) {
    $path = Join-Path $dir "Readhold.lnk"
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "`"$launcher`""
    $lnk.WorkingDirectory = $root
    $lnk.Description = "Readhold - a calm reader for papers, articles and notes"
    if (Test-Path $icon) { $lnk.IconLocation = "$icon,0" }
    $lnk.Save()
    Write-Host "Created $path"
}
Write-Host "Done. Double-click Readhold on your desktop, or type 'Readhold' in Start."
