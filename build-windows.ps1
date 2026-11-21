param([string]$PyInstallerModules)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
Push-Location $PSScriptRoot
try {
    if ($PyInstallerModules) {
        $modules = (Resolve-Path -LiteralPath $PyInstallerModules).Path
        python -c 'import sys; sys.path.insert(0, sys.argv[1]); from PyInstaller.__main__ import run; run(sys.argv[2:])' `
            $modules --onefile --windowed --name BandoriLovePetRoleBuilder role_builder.py
    } else {
        python -m PyInstaller --onefile --windowed --name BandoriLovePetRoleBuilder role_builder.py
    }
} finally {
    Pop-Location
}
