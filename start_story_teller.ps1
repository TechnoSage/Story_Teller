#Requires -Version 5.0
<#
.SYNOPSIS
    Story Teller - Windows Launcher

.DESCRIPTION
    1. Checks whether the Flask server is already running on port 5000.
    2. If not, locates Python and starts run.py in a minimised window.
    3. Polls until the server is ready (up to 30 seconds).
    4. Opens the dashboard in Google Chrome, or the default browser.

.NOTES
    Called by the desktop shortcut.
    Do NOT move this file without updating the shortcut.
#>

$AppDir = $PSScriptRoot
$AppUrl = "http://127.0.0.1:5000"
$Port   = 5000
$MutexName = "Global\StoryTellerLauncher"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Show-Error($Msg) {
    Add-Type -AssemblyName PresentationFramework | Out-Null
    [System.Windows.MessageBox]::Show(
        $Msg,
        "Story Teller",
        [System.Windows.MessageBoxButton]::OK,
        [System.Windows.MessageBoxImage]::Error
    ) | Out-Null
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32_StoryTeller {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
}
"@ -ErrorAction SilentlyContinue

function Open-Or-Focus-Browser($Url) {
    $existing = Get-Process -Name "chrome" -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero -and
                       $_.MainWindowTitle -like "*Story Teller*" } |
        Select-Object -First 1

    if ($existing) {
        $hwnd = $existing.MainWindowHandle
        if ([Win32_StoryTeller]::IsIconic($hwnd)) { [Win32_StoryTeller]::ShowWindow($hwnd, 9) }
        [Win32_StoryTeller]::SetForegroundWindow($hwnd)
        return
    }

    $chromePaths = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
    )
    foreach ($cp in $chromePaths) {
        if (Test-Path $cp) {
            Start-Process -FilePath $cp -ArgumentList "--new-window", $Url
            return
        }
    }
    Start-Process $Url
}

function Test-PortListening($Port) {
    $hits = netstat -an 2>$null | Select-String "127\.0\.0\.1:$Port\s.*LISTENING"
    return ($null -ne $hits -and @($hits).Count -gt 0)
}

function Test-ServerAlive($Url) {
    try {
        $req         = [System.Net.WebRequest]::Create($Url)
        $req.Timeout = 2500
        $resp        = $req.GetResponse()
        $resp.Dispose()
        return $true
    } catch [System.Net.WebException] {
        if ($null -ne $_.Exception.Response) { $_.Exception.Response.Dispose(); return $true }
        return $false
    } catch {
        return $false
    }
}

function Get-PortPid($Port) {
    $line = netstat -ano 2>$null |
            Select-String "127\.0\.0\.1:$Port\s.*LISTENING" |
            Select-Object -First 1
    if ($line) {
        $parts  = ($line.Line).Trim() -split '\s+'
        $pidStr = $parts[-1]
        $pidVal = 0
        if ([int]::TryParse($pidStr, [ref]$pidVal) -and $pidVal -gt 4) { return $pidVal }
    }
    return $null
}

function Find-Python {
    $waRoot = [System.IO.Path]::Combine($env:LOCALAPPDATA, 'Microsoft', 'WindowsApps')

    foreach ($root in @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles\Python",
        "C:\Python313", "C:\Python312", "C:\Python311", "C:\Python310", "C:\Python39"
    )) {
        if (Test-Path $root) {
            $exe = Get-ChildItem $root -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue |
                   Where-Object { $_.FullName -notmatch "\\Scripts\\" } |
                   Select-Object -First 1
            if ($exe) { return $exe.FullName }
        }
    }

    foreach ($cmd in @("python3", "python")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            $src = $found.Source
            if ([System.IO.Path]::GetDirectoryName($src) -ieq $waRoot) { continue }
            return $src
        }
    }

    try {
        $pkg = Get-AppxPackage -Name "PythonSoftwareFoundation.Python*" -ErrorAction SilentlyContinue |
               Sort-Object Version -Descending | Select-Object -First 1
        if ($pkg) {
            $exe = Join-Path $waRoot (Join-Path $pkg.PackageFamilyName "python.exe")
            if (Test-Path $exe) { return $exe }
        }
    } catch {}

    if (Test-Path $waRoot) {
        $subDirs = Get-ChildItem $waRoot -Directory -ErrorAction SilentlyContinue |
                   Where-Object { $_.Name -like "PythonSoftwareFoundation*" } |
                   Sort-Object LastWriteTime -Descending
        foreach ($dir in $subDirs) {
            $exe = Join-Path $dir.FullName "python.exe"
            if (Test-Path $exe) { return $exe }
        }
    }

    return $null
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

$mutex = [System.Threading.Mutex]::new($false, $MutexName)
if (-not $mutex.WaitOne(0)) {
    $mutex.Dispose()
    exit 0
}

try {
    if (Test-PortListening $Port) {
        if (Test-ServerAlive $AppUrl) {
            Open-Or-Focus-Browser $AppUrl
            Start-Sleep -Seconds 2
            exit 0
        }
        $oldPid = Get-PortPid $Port
        if ($oldPid) {
            try { Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue } catch {}
            Start-Sleep -Milliseconds 800
        }
    }

    $pythonExe = Find-Python
    if (-not $pythonExe) {
        Show-Error (
            "Python was not found on this computer." + [Environment]::NewLine + [Environment]::NewLine +
            "Please install Python from https://www.python.org" + [Environment]::NewLine +
            "and check 'Add Python to PATH' during installation."
        )
        exit 1
    }

    $runPy = Join-Path $AppDir "run.py"
    if (-not (Test-Path $runPy)) {
        Show-Error (
            "Cannot find run.py in:" + [Environment]::NewLine + $AppDir + [Environment]::NewLine +
            [Environment]::NewLine +
            "Please ensure the shortcut points to the Story Teller folder."
        )
        exit 1
    }

    Start-Process -FilePath $pythonExe `
                  -ArgumentList "`"$runPy`"" `
                  -WorkingDirectory $AppDir `
                  -WindowStyle Minimized

    $maxSeconds = 30
    for ($i = 0; $i -lt $maxSeconds; $i++) {
        Start-Sleep -Seconds 1
        if (Test-PortListening $Port) { break }
    }

    Open-Or-Focus-Browser $AppUrl
    Start-Sleep -Seconds 2
    exit 0

} finally {
    try { $mutex.ReleaseMutex() } catch {}
    $mutex.Dispose()
}
