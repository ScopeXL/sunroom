# Sunroom Screen's installer for Windows 10 and 11: this computer becomes a Sunroom
# screen for the person signed in to it, with no administrator rights and no service
# (docs/KIOSK.md, docs/M7.md T14). In a PowerShell window (Start, then type PowerShell):
#
#   irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1 | iex
#
# With options (iex takes none; a script block made from the same download does), in the window:
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/ScopeXL/sunroom/main/kiosk/install.ps1))) -Url https://calendar.example.com
# or with a copy of this file:
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Url https://calendar.example.com]
#       [-DryRun] [-AgentWheel FILE] [-ServerWheel FILE] [-Uninstall] [-Yes]
#
# Never as `powershell -c "irm ... | iex"`, nor from the Run box: Microsoft Defender stops a
# PowerShell started with a command line that downloads a script and runs it, the way "ClickFix"
# attacks begin, and says it found a threat (ADR 0041). So this runs in the window it's typed in,
# under that window's execution policy (Restricted, unless someone changed it), and it starts no
# other PowerShell itself.
#
# It installs uv (a pinned version, into %USERPROFILE%\.local\bin, only when there's no uv: uv's
# own zip from its GitHub release, checked against the sums below), then Sunroom Screen with uv
# from this version's GitHub Release, its wheel checked against the Release's SHA256SUMS before
# anything installs it; puts a shortcut in the Startup folder, so it starts at sign-in without a
# console window; and starts it. Sunroom Screen opens Microsoft Edge (or Google Chrome) full
# screen, and writes the browser's policy itself, for this user only.
#
# Running it again is safe: it keeps the screen's settings and its pairing. -Uninstall takes it
# off again, and asks before it deletes the pairing; Sunroom run on this computer (ADR 0038) is
# stopped and uninstalled too, its data kept. Windows PowerShell 5.1 runs it, and so does
# PowerShell 7. It never asks for a password, and keeps every file inside this user's folders.
#
# Keep it ASCII (Windows PowerShell 5.1 reads a file without a byte-order mark as ANSI).

param(
    [string]$Url = "",
    [switch]$DryRun,
    [string]$AgentWheel = "",
    [string]$ServerWheel = "",
    [switch]$Uninstall,
    [switch]$Yes
)

# The options, gathered here for the steps below, which run in a scope of their own: piped into
# `iex` in someone's PowerShell window, nothing of this script stays behind in it.
$Options = [pscustomobject]@{
    Url = $Url
    DryRun = $DryRun.IsPresent
    AgentWheel = $AgentWheel
    ServerWheel = $ServerWheel
    Uninstall = $Uninstall.IsPresent
    Yes = $Yes.IsPresent
}

& {
    param($Options)

    Set-StrictMode -Version 3.0
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue" # Invoke-WebRequest's progress bar is very slow on 5.1

    $KioskVersion = "0.17.0" # Sunroom's VERSION (`just bump` sets it), as in install.sh
    $SunroomRepo = "ScopeXL/sunroom"
    # uv when there's none: its own zip for this computer from uv's GitHub release, checked
    # against these sums (that release's .sha256 files) before it's unpacked. Change them together.
    $UvVersion = "0.12.23"
    $UvSums = @{
        "x86_64" = "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90"
        "aarch64" = "13294e232ececbe709c06b74e6ced06f2a225ea5591476685362f22be56a50d5"
        "i686" = "22a92f4374e4716c2848acaa0392f2f8e4a13b0ff65d080e2a5ade167bce96a8"
    }
    $AgentPort = 7800

    $BinDir = Join-Path $HOME ".local\bin"
    $Agent = Join-Path $BinDir "sunroom-kiosk.exe"
    $AgentWindowless = Join-Path $BinDir "sunroom-kioskw.exe" # the same, with no console window
    $DataDir = Join-Path $env:LOCALAPPDATA "sunroom-kiosk" # its settings, browser profile and log
    $WheelsDir = Join-Path $DataDir "wheels" # the running wheel and the one before, for updates
    $LogFile = Join-Path $DataDir "install.log"
    $Shortcut = Join-Path ([Environment]::GetFolderPath("Startup")) "Sunroom Screen.lnk"
    $ReleaseBase = "https://github.com/$SunroomRepo/releases/download/v$KioskVersion"
    $WheelName = "sunroom_kiosk-$KioskVersion-py3-none-any.whl"
    $InstallerUrl = "https://raw.githubusercontent.com/$SunroomRepo/main/kiosk/install.ps1"

    # ---------------------------------------------------------------------------- messages

    function Write-Step([string]$Text) {
        Write-Host ""
        Write-Host "==> $Text"
    }

    function Write-Note([string]$Text) {
        Write-Host "    $Text"
    }

    function Write-HeadsUp([string]$Text) {
        Write-Host "    Heads up: $Text"
    }

    # A stop the family can act on: what went wrong and what to do, never a stack trace.
    function Exit-Install([string[]]$Lines) {
        throw [System.Exception]::new(($Lines -join [Environment]::NewLine))
    }

    # Run a program; give back its exit code and what it printed. Windows PowerShell 5.1 turns a
    # native program's stderr into errors, which "Stop" would throw on (uv reports progress there).
    function Invoke-Native([string]$File, [string[]]$Arguments) {
        $saved = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $printed = & $File @Arguments 2>&1 | ForEach-Object { "$_" }
            return [pscustomobject]@{ Code = $LASTEXITCODE; Output = ($printed -join [Environment]::NewLine) }
        } finally {
            $ErrorActionPreference = $saved
        }
    }

    function Read-YesNo([string]$Question) {
        if ($Options.Yes) {
            Write-Host "$Question yes (-Yes)"
            return $true
        }
        if (-not [Environment]::UserInteractive) {
            Write-Host "$Question (no keyboard to ask, so: no)"
            return $false
        }
        while ($true) {
            $answer = "$(Read-Host "$Question [y/N]")".Trim().ToLowerInvariant()
            if ($answer -eq "" -or $answer -eq "n" -or $answer -eq "no") { return $false }
            if ($answer -eq "y" -or $answer -eq "yes") { return $true }
            Write-Host "Please answer y or n."
        }
    }

    # ---------------------------------------------------------------------------- what's here

    # Microsoft Edge comes with Windows; Google Chrome when it's installed (Sunroom Screen's
    # browser.py looks in the same places, Edge first).
    function Find-Browser {
        $roots = @(${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA) | Where-Object { $_ }
        foreach ($root in $roots) {
            $edge = Join-Path $root "Microsoft\Edge\Application\msedge.exe"
            if (Test-Path -LiteralPath $edge) { return "Microsoft Edge" }
        }
        foreach ($root in $roots) {
            $chrome = Join-Path $root "Google\Chrome\Application\chrome.exe"
            if (Test-Path -LiteralPath $chrome) { return "Google Chrome" }
        }
        return $null
    }

    function Find-Uv {
        $command = Get-Command -Name "uv" -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { return $command.Path }
        $local = Join-Path $BinDir "uv.exe"
        if (Test-Path -LiteralPath $local) { return $local }
        return $null
    }

    # uv's build for this computer, from Windows' own architecture, as uv's own installer picks it
    # (an Intel PowerShell on an Arm computer says AMD64 of itself).
    function Get-UvTarget {
        $key = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
        $machine = Get-ItemPropertyValue -LiteralPath $key -Name "PROCESSOR_ARCHITECTURE"
        if ($machine -eq "ARM64") { return "aarch64" }
        if ($machine -eq "x86") { return "i686" }
        return "x86_64"
    }

    # A file's SHA-256 with .NET alone: Get-FileHash is a script module's function on Windows
    # PowerShell 5.1, and this runs under the window's own execution policy.
    function Get-Sha256([string]$Path) {
        $sha = [Security.Cryptography.SHA256]::Create()
        $stream = [IO.File]::OpenRead($Path)
        try {
            return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace "-", "").ToLowerInvariant()
        } finally {
            $stream.Dispose()
            $sha.Dispose()
        }
    }

    # This installer again with options: its own file when it ran from one, else the same download
    # as a script block, for the PowerShell window (piped into iex, there's no file to point at).
    function Get-InstallerCommand([string]$Arguments) {
        if ($PSCommandPath) {
            return "powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" $Arguments"
        }
        return "& ([scriptblock]::Create((irm $InstallerUrl))) $Arguments"
    }

    function Test-ScreenRunning {
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$AgentPort/api/screen" -TimeoutSec 3
            return $true
        } catch {
            return $false
        }
    }

    # ---------------------------------------------------------------------------- the steps

    # uv installs Sunroom Screen and the Python it runs on (3.14, kept apart from any other). Its
    # zip is checked before it's unpacked (with .NET: Expand-Archive is a script module's too), and
    # no script of uv's runs, so no second PowerShell starts (ADR 0041).
    function Install-Uv {
        $found = Find-Uv
        if ($found) { return $found }
        Write-Note "Installing uv $UvVersion, which installs Sunroom Screen..."
        $target = Get-UvTarget
        $name = "uv-$target-pc-windows-msvc.zip"
        $zip = Join-Path ([IO.Path]::GetTempPath()) $name
        try {
            Invoke-WebRequest -Uri "https://github.com/astral-sh/uv/releases/download/$UvVersion/$name" -OutFile $zip -UseBasicParsing
        } catch {
            Exit-Install @("Couldn't download uv from GitHub. Check the internet connection, then run this again.")
        }
        if ((Get-Sha256 $zip) -ne $UvSums[$target]) {
            Remove-Item -LiteralPath $zip -ErrorAction SilentlyContinue
            Exit-Install @(
                "The download of uv didn't match its checksum, so it wasn't installed.",
                "Run the installer again; if it happens again, tell us on GitHub."
            )
        }
        $unpacked = Join-Path ([IO.Path]::GetTempPath()) "sunroom-uv-$UvVersion"
        try {
            Remove-Item -LiteralPath $unpacked -Recurse -Force -ErrorAction SilentlyContinue
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            [IO.Compression.ZipFile]::ExtractToDirectory($zip, $unpacked)
            $null = New-Item -ItemType Directory -Force -Path $BinDir
            foreach ($file in "uv.exe", "uvx.exe", "uvw.exe") {
                Copy-Item -LiteralPath (Join-Path $unpacked $file) -Destination $BinDir -Force
            }
        } catch {
            Exit-Install @("Couldn't put uv in $BinDir. Running this again is safe.")
        } finally {
            Remove-Item -LiteralPath $zip, $unpacked -Recurse -Force -ErrorAction SilentlyContinue
        }
        return (Join-Path $BinDir "uv.exe")
    }

    # Sunroom Screen's wheel: -AgentWheel's, or this version's from its GitHub Release, checked
    # against the Release's SHA256SUMS before anything installs it. Kept for updates to fall back on.
    function Get-AgentWheel {
        $null = New-Item -ItemType Directory -Force -Path $WheelsDir
        if ($Options.AgentWheel) {
            $name = Split-Path -Leaf $Options.AgentWheel
            $kept = Join-Path $WheelsDir $name
            Copy-Item -LiteralPath $Options.AgentWheel -Destination $kept -Force
            Write-Note "Using Sunroom Screen from $($Options.AgentWheel) (-AgentWheel: not checked against a release)."
            return $kept
        }
        $sums = Join-Path ([IO.Path]::GetTempPath()) "sunroom-SHA256SUMS"
        try {
            Invoke-WebRequest -Uri "$ReleaseBase/SHA256SUMS" -OutFile $sums -UseBasicParsing
        } catch {
            Exit-Install @(
                "Couldn't download Sunroom Screen $KioskVersion's checksums from GitHub.",
                "Either GitHub can't be reached right now, or this version's files are still being",
                "published (it takes a few minutes after a release). Try again in a little while."
            )
        }
        $expected = $null
        foreach ($line in Get-Content -LiteralPath $sums) {
            $parts = $line.Trim() -split "\s+", 2
            if ($parts.Count -eq 2 -and $parts[1].TrimStart("*") -eq $WheelName) { $expected = $parts[0].ToLowerInvariant() }
        }
        Remove-Item -LiteralPath $sums -ErrorAction SilentlyContinue
        if (-not $expected -or $expected -notmatch "^[0-9a-f]{64}$") {
            Exit-Install @(
                "Sunroom Screen $KioskVersion isn't in its release's checksums.",
                "Try again in a little while; if it lasts, run the installer of another version."
            )
        }
        $download = Join-Path ([IO.Path]::GetTempPath()) $WheelName
        try {
            Invoke-WebRequest -Uri "$ReleaseBase/$WheelName" -OutFile $download -UseBasicParsing
        } catch {
            Exit-Install @("Couldn't download Sunroom Screen $KioskVersion from GitHub. Check the internet connection, then run this again.")
        }
        if ((Get-Sha256 $download) -ne $expected) {
            Remove-Item -LiteralPath $download -ErrorAction SilentlyContinue
            Exit-Install @(
                "The download of Sunroom Screen didn't match its checksum, so it wasn't installed.",
                "Run the installer again; if it happens again, tell us on GitHub."
            )
        }
        $kept = Join-Path $WheelsDir $WheelName
        Move-Item -LiteralPath $download -Destination $kept -Force
        Write-Note "Downloaded Sunroom Screen $KioskVersion and checked it."
        return $kept
    }

    # -ServerWheel: Sunroom's own wheel, and its constraints from beside it, where Sunroom Screen
    # looks first when On This Computer is chosen (agent local.py; not checked against a release).
    function Save-ServerWheel {
        if (-not $Options.ServerWheel) { return }
        $null = New-Item -ItemType Directory -Force -Path $WheelsDir
        Copy-Item -LiteralPath $Options.ServerWheel -Destination $WheelsDir -Force
        $constraints = Join-Path (Split-Path -Parent $Options.ServerWheel) "sunroom-$KioskVersion-constraints.txt"
        if (Test-Path -LiteralPath $constraints) {
            Copy-Item -LiteralPath $constraints -Destination $WheelsDir -Force
        }
        Write-Note "Kept Sunroom from $($Options.ServerWheel) for On This Computer (-ServerWheel: not checked against a release)."
    }

    # A running Sunroom Screen holds its own files open, so it quits before uv replaces them (the
    # same Quit as This Screen's); the shortcut or this installer starts it again.
    function Close-RunningScreen {
        if (-not (Test-ScreenRunning)) { return }
        Write-Note "Closing the Sunroom Screen that's running..."
        try {
            $null = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$AgentPort/api/screen/quit" `
                -Headers @{ "X-Sunroom-Screen" = "1" } -TimeoutSec 5
        } catch {
            Write-HeadsUp "it didn't answer, so it's being stopped instead."
        }
        for ($try = 0; $try -lt 20 -and (Test-ScreenRunning); $try++) { Start-Sleep -Milliseconds 500 }
        Get-Process -Name "sunroom-kioskw", "sunroom-kiosk" -ErrorAction SilentlyContinue | Stop-Process -Force
    }

    function Install-Agent([string]$Uv, [string]$Wheel) {
        Write-Note "Installing Sunroom Screen (with its own Python; the first time takes a minute)..."
        $env:UV_TOOL_BIN_DIR = $BinDir
        try {
            $ran = Invoke-Native $Uv @("tool", "install", "--reinstall", "--force", "--python", "3.14", $Wheel)
        } finally {
            Remove-Item -LiteralPath "Env:UV_TOOL_BIN_DIR" -ErrorAction SilentlyContinue
        }
        if ($ran.Code -ne 0) {
            Write-Host $ran.Output
            Exit-Install @("Couldn't install Sunroom Screen; uv's messages are above. Running the installer again is safe.")
        }
        $ran = Invoke-Native $Agent @("--version")
        if ($ran.Code -ne 0) {
            Write-Host $ran.Output
            Exit-Install @("Sunroom Screen was installed but doesn't start; its messages are above.")
        }
        Write-Note "Installed Sunroom Screen $KioskVersion."
    }

    # The address, when -Url gave one; otherwise the screen keeps the one it found or was told
    # before, or finds its Sunroom itself.
    function Write-ScreenSetting {
        if ($Options.Url) {
            $ran = Invoke-Native $Agent @("config", "--url", $Options.Url)
            if ($ran.Code -ne 0) {
                Exit-Install @($ran.Output, "Use the address you open on your other devices, for example http://192.168.1.20:8080")
            }
            Write-Note "The screen will show Sunroom from $($Options.Url)."
        } else {
            Write-Note "The screen finds Sunroom on your network itself, or asks for its address."
        }
    }

    # The Startup folder starts it at sign-in, with no console window (the windowless command).
    function Add-StartupShortcut {
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut($Shortcut)
        $link.TargetPath = $AgentWindowless
        $link.Arguments = "run"
        $link.WorkingDirectory = $DataDir
        $link.Description = "Sunroom Screen: the family calendar on this screen"
        $link.Save()
        Write-Note "Sunroom Screen now starts when you sign in (a shortcut in the Startup folder)."
    }

    function Open-SunroomScreen {
        Start-Process -FilePath $AgentWindowless -ArgumentList "run" -WorkingDirectory $DataDir
        Write-Note "Starting it. To close it: Settings, This Screen, Quit Sunroom Screen, on the screen."
    }

    # ---------------------------------------------------------------------------- the runs

    function Show-Plan {
        $browser = Find-Browser
        Write-Host "Sunroom installer $($KioskVersion): a dry run. Nothing on this computer changes."
        Write-Host ""
        Write-Host "This computer: Windows $([Environment]::OSVersion.Version)."
        if ($Options.Uninstall) {
            Write-Host "A real run would close Sunroom Screen, take it out of the Startup folder and the"
            Write-Host "browser's policy, stop and uninstall Sunroom if it runs on this computer (its data"
            Write-Host "kept), uninstall Sunroom Screen with uv, and ask before deleting its settings and pairing."
            return
        }
        if ($Options.Url) { $shows = $Options.Url } else { $shows = "the Sunroom it finds on the network (or an address typed on it)" }
        if ($Options.AgentWheel) { $from = "from $($Options.AgentWheel)" } else { $from = "from GitHub, checked against its release's SHA256SUMS" }
        Write-Host "A real run would:"
        if ($browser) {
            Write-Host "  - use $browser"
        } else {
            Write-Host "  - stop: it needs Microsoft Edge or Google Chrome, and neither is installed"
            return
        }
        Write-Host "  - install uv $UvVersion in $BinDir when there's no uv: its zip for $(Get-UvTarget)"
        Write-Host "    from GitHub, checked against its checksum"
        Write-Host "  - install Sunroom Screen $KioskVersion with uv ($from)"
        if ($Options.ServerWheel) {
            Write-Host "  - keep Sunroom's own wheel from $($Options.ServerWheel) for On This Computer"
        }
        Write-Host "  - save the screen's settings in $DataDir, where it shows"
        Write-Host "    $shows"
        Write-Host "  - start Sunroom Screen when you sign in ($Shortcut), and start it now"
        Write-Host "Nothing else is installed, nothing needs an administrator, and no other settings change."
    }

    function Install-SunroomScreen {
        Write-Host "Sunroom installer $KioskVersion"
        if ($Options.Url) {
            Write-Host "This sets up a Sunroom screen on this computer, showing Sunroom from $($Options.Url). It takes a few minutes."
        } else {
            Write-Host "This sets up a Sunroom screen on this computer; it finds Sunroom on your network by itself. It takes a few minutes."
        }

        Write-Step "Checking this computer"
        $browser = Find-Browser
        if (-not $browser) {
            Exit-Install @("Sunroom Screen needs Microsoft Edge or Google Chrome, and neither is installed.", "Install one, then run this again.")
        }
        Write-Note "Windows $([Environment]::OSVersion.Version); the browser: $browser."
        if ($Options.AgentWheel -and -not (Test-Path -LiteralPath $Options.AgentWheel)) {
            Exit-Install @("-AgentWheel: there's no file at $($Options.AgentWheel).")
        }
        if ($Options.ServerWheel -and -not (Test-Path -LiteralPath $Options.ServerWheel)) {
            Exit-Install @("-ServerWheel: there's no file at $($Options.ServerWheel).")
        }

        Write-Step "Setting up the screen"
        $uv = Install-Uv
        $wheel = Get-AgentWheel
        Save-ServerWheel
        Close-RunningScreen
        Install-Agent -Uv $uv -Wheel $wheel
        Write-ScreenSetting
        Add-StartupShortcut

        Write-Step "All done"
        Write-Host "The screen is set up. When it starts, it shows a six-character code: on a device"
        Write-Host "signed in to Sunroom, open Settings, then Devices, then Pair a Display (on a phone,"
        Write-Host "it's under More), and type that code."
        Open-SunroomScreen
        Write-Host "Remove it later, in PowerShell:  $(Get-InstallerCommand '-Uninstall')"
        Write-Host "This install's log:  $LogFile"
    }

    function Uninstall-SunroomScreen {
        Write-Host "Removing Sunroom Screen from this computer..."
        Close-RunningScreen
        if (Test-Path -LiteralPath $Shortcut) {
            Remove-Item -LiteralPath $Shortcut -Force
            Write-Note "Took it out of the Startup folder."
        }
        if (Test-Path -LiteralPath $Agent) {
            $null = Invoke-Native $Agent @("policy", "--remove")
            Write-Note "Took Sunroom Screen's settings out of the browser's policy."
            # Sunroom run on this computer: nothing but Sunroom Screen runs it here, so it goes
            # too; the family's data stays (its folder is said).
            $ran = Invoke-Native $Agent @("sunroom", "remove")
            if ($ran.Code -eq 0 -and $ran.Output -notmatch "wasn't set up") {
                foreach ($line in ($ran.Output -split "`r?`n")) { if ($line) { Write-Note $line } }
            }
        }
        $uv = Find-Uv
        if ($uv) {
            $null = Invoke-Native $uv @("tool", "uninstall", "sunroom-kiosk")
            Write-Note "Uninstalled Sunroom Screen."
        }
        if (Test-Path -LiteralPath (Join-Path $DataDir "profile")) {
            Write-Host ""
            Write-Host "The screen's browser data holds its pairing with Sunroom."
            if (Read-YesNo "Delete it too? The screen would need to be paired again.") {
                Remove-Item -LiteralPath $DataDir -Recurse -Force
                Write-Note "Deleted the screen's browser data and settings."
            } else {
                Write-Note "Kept the browser data (and the pairing) in $(Join-Path $DataDir 'profile')."
            }
        }
        Write-Host ""
        Write-Host "Sunroom Screen is removed. uv stays, in $BinDir; uv's own guide says how to remove it:"
        Write-Host "https://docs.astral.sh/uv/getting-started/installation/#uninstallation"
    }

    # ---------------------------------------------------------------------------- main

    # The install is logged; the uninstall isn't, since it may delete the folder the log is in.
    function Invoke-Main {
        if ($Options.Uninstall) {
            Uninstall-SunroomScreen
            return
        }
        $null = New-Item -ItemType Directory -Force -Path $DataDir
        Start-Transcript -LiteralPath $LogFile -Append | Out-Null
        try {
            Install-SunroomScreen
        } finally {
            Stop-Transcript | Out-Null
        }
    }

    try {
        if ($Options.DryRun) { Show-Plan } else { Invoke-Main }
    } catch {
        Write-Host ""
        Write-Host $_.Exception.Message -ForegroundColor Red
        Write-Host "Running the installer again is safe."
        # Run as a file, say so to whatever started it; piped into iex, leave the window open.
        if ($PSCommandPath) { exit 1 }
    }
} $Options
