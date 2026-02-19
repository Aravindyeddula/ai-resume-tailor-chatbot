Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Write-Host "== Proximal Energy Sanity Check (Windows) =="

if (Test-Path artifacts) {
    Remove-Item artifacts -Recurse -Force
}
New-Item -ItemType Directory -Path artifacts | Out-Null

Write-Host "Running: python -m app.cli sanity"
python -m app.cli sanity

$out = "artifacts/sanity_output.json"
if (-not (Test-Path $out)) {
    Write-Error "Missing $out. Your sanity flow must generate artifacts/sanity_output.json."
}

python scripts/verify_output.py $out
Write-Host "OK: sanity check passed"

