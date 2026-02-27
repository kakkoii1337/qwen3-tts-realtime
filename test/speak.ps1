# speak.ps1 — Stream TTS audio from the API and play immediately via ffplay,
#             or save to a file when -n is given.
# Usage: .\speak.ps1 "Hello, world!" [-Language English] [-Speaker Aiden] [-Instruct "..."] [-n output.mp3]

param(
    [Parameter(Mandatory=$true)]
    [string]$Text,
    [string]$Language = "English",
    [string]$Speaker = "",
    [string]$Instruct = "",
    [string]$n = ""          # output file path; empty = play via ffplay
)

$ApiUrl = if ($env:TTS_API_URL) { $env:TTS_API_URL } else { "http://localhost:8000/tts" }

# Locate ffplay and ffmpeg — try PATH first, fall back to known install dir
$KnownBin = "C:\Users\laikm\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin"
$FfplayPath = if (Get-Command "ffplay" -ErrorAction SilentlyContinue) { "ffplay" } else { "$KnownBin\ffplay.exe" }
$FfmpegPath = if (Get-Command "ffmpeg" -ErrorAction SilentlyContinue) { "ffmpeg" } else { "$KnownBin\ffmpeg.exe" }

$body = [ordered]@{ text = $Text; language = $Language }
if ($Speaker -ne "") { $body["speaker"]  = $Speaker }
if ($Instruct -ne "") { $body["instruct"] = $Instruct }

# Write JSON to a temp file to avoid shell quoting issues (UTF-8 safe for curl -d @file)
$bodyJson = $body | ConvertTo-Json -Compress
$tmpJson = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($tmpJson, $bodyJson, [System.Text.Encoding]::UTF8)

try {
    if ($n -ne "") {
        # Save mode: curl writes the WAV to a temp file (binary-safe via -o),
        # then ffmpeg converts it.  Using & instead of cmd /c avoids shell
        # quoting issues with the output path.
        $tmpWav = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), ".wav")
        try {
            & curl.exe -sS -X POST $ApiUrl -H "Content-Type: application/json; charset=utf-8" -d "@$tmpJson" -o $tmpWav
            & $FfmpegPath -i $tmpWav -y $n
            if ($LASTEXITCODE -eq 0) { Write-Host "Saved to $n" }
        } finally {
            Remove-Item $tmpWav -ErrorAction SilentlyContinue
        }
    } else {
        # Play mode: stream audio directly to ffplay using curl -d @file for proper UTF-8 handling
        # curl -N (no buffer) + -d @file (UTF-8 safe) | ffplay stdin (-i -)
        $pipeCmd = "curl.exe -sS -N -X POST `"$ApiUrl`" -H `"Content-Type: application/json; charset=utf-8`" -d @" + $tmpJson + " | " + $FfplayPath + " -nodisp -autoexit -f wav -i -"
        cmd /c $pipeCmd
    }
} finally {
    Remove-Item $tmpJson -ErrorAction SilentlyContinue
}
