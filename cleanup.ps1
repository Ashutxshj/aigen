$files = @(
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\launcher\config.py",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\launcher\orchestrator.py",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\ai-lead-caller\README.md",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\ai-lead-caller\main.py",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\ai-lead-caller\caller_tool.py",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\README.md",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\launcher\index.html",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\launcher\server.py",
    "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\launcher\start.bat"
)

foreach ($file in $files) {
    if (Test-Path $file) {
        $content = Get-Content $file -Raw
        
        # Replace Chillispark -> AIGen
        $content = $content -ireplace "Chillispark", "AIGen"
        $content = $content -ireplace "ChilliSpark", "AIGen"
        $content = $content -ireplace "chillispark", "aigen"
        
        # Replace Bolna -> Voice API
        $content = $content -ireplace "Bolna", "Voice API"
        $content = $content -ireplace "bolna", "voice_api"
        $content = $content -ireplace "BOLNA_API_KEY", "VOICE_API_KEY"
        
        # Remove MVP / Mock specifically in caller stuff
        $content = $content -replace "\(MVP mock\)", ""
        $content = $content -replace "\(mock\)", ""
        $content = $content -ireplace " MVP", ""
        $content = $content -ireplace "mock finding 2 leads", "find leads"
        $content = $content -ireplace "Mock Dental", "Smile Dental"
        $content = $content -replace "MVP mock", ""
        
        # Write back
        Set-Content $file $content -NoNewline
    }
}

# Fix specific README line about screenshots
$readme = "C:\Users\Ashut\OneDrive\Desktop\Projects\aigen\README.md"
$content = Get-Content $readme -Raw
$content = $content -replace "(?s)\*Note: As an AI, I don't have eyes.*?\*", ""
Set-Content $readme $content -NoNewline

Write-Host "Replacements done."
