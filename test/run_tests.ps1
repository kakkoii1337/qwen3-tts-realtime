# run_tests.ps1 — Run all tests against the realtime server
# Usage: pwsh -NoProfile -File .\test\run_tests.ps1
# Override URL: $env:TTS_API_URL = "http://my-host:8001/tts" before running

$env:TTS_API_URL = if ($env:TTS_API_URL) { $env:TTS_API_URL } else { "http://localhost:8001/tts" }
Write-Host "Target: $env:TTS_API_URL" -ForegroundColor Yellow

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host " TEST SUITE A: test_custom_voice.ps1   " -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
& "$PSScriptRoot\test_custom_voice.ps1"

Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host " TEST SUITE B: test_voice_design.ps1   " -ForegroundColor Cyan
Write-Host "=======================================" -ForegroundColor Cyan
& "$PSScriptRoot\test_voice_design.ps1"

Write-Host ""
Write-Host "=======================================" -ForegroundColor Green
Write-Host " All test suites complete.             " -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Green
