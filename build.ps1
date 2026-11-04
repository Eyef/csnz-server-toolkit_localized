# Build dist/CSNZ.GMTool.exe (onefile, windowed, locales embedded).
#
# Usage (from the repository root):
#   powershell -ExecutionPolicy Bypass -File build.ps1
#   powershell -ExecutionPolicy Bypass -File build.ps1 -SkipTests
#   powershell -ExecutionPolicy Bypass -File build.ps1 -WithAuthServer
#
# Requirements: Python 3.8+ on PATH. PyInstaller is installed automatically
# from requirements-build.txt unless -NoInstall is given.
#
# -WithAuthServer additionally builds dist/AuthServer/CSNZ.AuthServer.exe,
# which needs fastapi and uvicorn (auth-server/requirements.txt).
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$NoInstall,
    [switch]$WithAuthServer
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $Root

try {
    Write-Host "==> Python"
    python --version
    if ($LASTEXITCODE -ne 0) {
        throw "python was not found in PATH"
    }

    if (-not $SkipTests) {
        Write-Host "==> Self-test"
        python scripts/selftest.py
        if ($LASTEXITCODE -ne 0) {
            throw "self-test failed"
        }
    }

    python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) {
        if ($NoInstall) {
            throw "PyInstaller is missing. Run: python -m pip install -r requirements-build.txt"
        }
        Write-Host "==> Installing build dependencies"
        python -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) {
            throw "failed to install PyInstaller"
        }
    }

    Write-Host "==> Building"
    python -m PyInstaller --noconfirm --clean packaging/CSNZ.GMTool.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed"
    }

    # The exe usually sits directly in the server root, so the default
    # server_root differs from the source-tree layout ("..").
    $dist = Join-Path $Root "dist"
    $exe = Join-Path $dist "CSNZ.GMTool.exe"
    if (-not (Test-Path $exe)) {
        throw "build finished but $exe was not created"
    }
    $config = Join-Path $dist "config.json"
    if (-not (Test-Path $config)) {
        python -c "import json,pathlib; src=pathlib.Path('gm-tool/config.example.json'); dst=pathlib.Path('dist/config.json'); data=json.loads(src.read_text(encoding='utf-8')); data['server_root']='.'; dst.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')"
        if ($LASTEXITCODE -ne 0) {
            throw "failed to create dist/config.json"
        }
    }
    Copy-Item (Join-Path $Root "LICENSE") (Join-Path $dist "LICENSE") -Force

    $authExe = $null
    if ($WithAuthServer) {
        Write-Host "==> Checking auth-server dependencies"
        python -c "import fastapi, uvicorn" 2>$null
        if ($LASTEXITCODE -ne 0) {
            if ($NoInstall) {
                throw "fastapi/uvicorn are missing. Run: python -m pip install -r auth-server/requirements.txt"
            }
            Write-Host "==> Installing auth-server dependencies"
            python -m pip install -r auth-server/requirements.txt
            if ($LASTEXITCODE -ne 0) {
                throw "failed to install auth-server dependencies"
            }
        }

        Write-Host "==> Building auth server"
        $authDist = Join-Path $dist "AuthServer"
        python -m PyInstaller --noconfirm --clean --distpath $authDist packaging/CSNZ.AuthServer.spec
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed for the auth server"
        }
        $authExe = Join-Path $authDist "CSNZ.AuthServer.exe"
        if (-not (Test-Path $authExe)) {
            throw "build finished but $authExe was not created"
        }

        # Keep a template config next to the exe; it must live in the
        # AuthServer folder so the exe can find the server root at "..".
        $authConfig = Join-Path $authDist "config.json"
        if (-not (Test-Path $authConfig)) {
            Copy-Item (Join-Path $Root "auth-server\config.example.json") $authConfig
        }
    }

    # Release parity with the upstream assets: a plain SHA256 list.
    $hashFile = Join-Path $dist "SHA256.txt"
    $built = @($exe) + @($authExe) | Where-Object { $_ -and (Test-Path $_) }
    $hashes = foreach ($item in $built) {
        $digest = (Get-FileHash -Algorithm SHA256 -Path $item).Hash.ToLower()
        # Paths relative to dist/, so "sha256sum -c SHA256.txt" works there.
        $rel = (Resolve-Path $item).Path.Substring($dist.Length + 1).Replace('\', '/')
        "$digest  $rel"
    }
    Set-Content -Path $hashFile -Value $hashes -Encoding ASCII

    Write-Host ""
    Write-Host "Build OK:"
    Write-Host ("  " + $exe)
    Write-Host ("  " + $config)
    Write-Host ("  " + $hashFile)
    if ($authExe) {
        Write-Host ("  " + $authExe)
        Write-Host ("  " + (Join-Path $dist "AuthServer\config.json"))
    }
    Write-Host ""
    Write-Host "Deploy: copy CSNZ.GMTool.exe and config.json into the CSNZ server root"
    Write-Host "(next to CSNZ_Server.exe), then run the exe."
    if ($authExe) {
        Write-Host "Also copy the AuthServer folder next to it; the GM tool will"
        Write-Host "start the packaged auth service without needing Python."
    }
}
finally {
    Pop-Location
}
