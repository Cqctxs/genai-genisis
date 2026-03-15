# Ensure we are running from the repository root
Set-Location (Split-Path -Parent $PSScriptRoot)

# Use a dedicated isolated environment for the PyInstaller build to prevent locking issues
$VenvDir = "venv"

if (!(Test-Path $VenvDir)) {
    Write-Host "Creating dedicated build environment..."
    python -m venv $VenvDir

    Write-Host "Installing dependencies..."
    & ".\$VenvDir\Scripts\python.exe" -m pip install --upgrade pip
    & ".\$VenvDir\Scripts\python.exe" -m pip install -r backend\requirements.txt
    & ".\$VenvDir\Scripts\python.exe" -m pip install -r mcp-server\requirements.txt
    & ".\$VenvDir\Scripts\python.exe" -m pip install pyinstaller
} else {
    Write-Host "Build environment already exists. Skipping dependency installation."
}

Write-Host "Building standalone executable..."
& ".\$VenvDir\Scripts\pyinstaller.exe" --name benchy-mcp --clean --onefile --paths backend --paths mcp-server mcp-server\main.py

Write-Host "Build complete! The executable is located at dist\benchy-mcp.exe"
