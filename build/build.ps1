<#
Build riproducibile del pacchetto Windows.
Requisiti SOLO sul PC dello sviluppatore: Windows x64, Python 3.14 (launcher "py").
Uso:  pwsh -File build\build.ps1  [-Lavoro C:\gcb]  [-SaltaTest]
Usa un percorso di lavoro breve: alcune librerie superano il limite di 260 caratteri di Windows.
Risultato: <Lavoro>\consegna\HolidayGest\  e  <Lavoro>\consegna\HolidayGest_<versione>.zip
#>
param([string]$Lavoro = "$env:TEMP\gcb", [switch]$SaltaTest)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Lavoro "venv-build"
$Versione = (Select-String -Path "$Root\app\config.py" -Pattern 'VERSION = "([^"]+)"').Matches[0].Groups[1].Value

Write-Host "== 1. Ambiente di build isolato ($Venv)"
if (-not (Test-Path "$Venv\Scripts\python.exe")) { py -3.14 -m venv $Venv }
& "$Venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install --quiet -r "$Root\requirements-lock.txt"

if (-not $SaltaTest) {
    Write-Host "== 2. Test automatici (dati sintetici)"
    & "$Venv\Scripts\python.exe" -m pytest "$Root\tests" -q -p no:cacheprovider
    if ($LASTEXITCODE) { throw "Test non superati: build interrotta." }
}

Write-Host "== 3. PyInstaller (cartella autosufficiente)"
& "$Venv\Scripts\pyinstaller.exe" --noconfirm --clean --workpath "$Lavoro\work" --distpath "$Lavoro\dist" "$Root\build\gestionale.spec"
if ($LASTEXITCODE) { throw "PyInstaller non riuscito." }

Write-Host "== 4. Composizione della consegna"
$Cons = Join-Path $Lavoro "consegna"
$Dest = Join-Path $Cons "HolidayGest"
if (Test-Path $Cons) { Remove-Item -Recurse -Force $Cons }
New-Item -ItemType Directory -Force $Dest | Out-Null
Copy-Item -Recurse "$Lavoro\dist\AvviaGestionale\*" $Dest
Copy-Item "$Root\docs\guida\Guida_rapida.html" (Join-Path $Dest "Guida rapida.html")
Copy-Item "$Root\docs\guida\LEGGIMI.txt" (Join-Path $Dest "LEGGIMI.txt")
$Lic = New-Item -ItemType Directory -Force (Join-Path $Dest "licenze")
& "$Venv\Scripts\python.exe" -I "$Root\build\raccogli_licenze.py" "$Venv" "$Lic"

Write-Host "== 5. Controlli di pulizia (niente dati, chiavi o archivi nel pacchetto)"
$vietati = Get-ChildItem -Recurse -File $Dest | Where-Object {
    $_.Extension -in ".sqlite3", ".gcbak", ".log", ".lock", ".port" -or $_.Name -like "registro_eliminazioni*" }
if ($vietati) { $vietati | ForEach-Object FullName; throw "Il pacchetto contiene file di dati: interrotto." }
$modelli = Get-ChildItem -Recurse -File $Dest -Filter *.onnx
if ($modelli.Count -lt 3) { throw "Modelli OCR mancanti nel pacchetto." }
if (-not (Test-Path (Join-Path $Dest "AvviaGestionale.exe"))) { throw "Eseguibile mancante." }

Write-Host "== 6. Archivio ZIP"
$Zip = Join-Path $Cons "HolidayGest_$Versione.zip"
Compress-Archive -Path $Dest -DestinationPath $Zip -CompressionLevel Optimal
$hash = (Get-FileHash $Zip -Algorithm SHA256).Hash
"$hash  $(Split-Path -Leaf $Zip)" | Set-Content (Join-Path $Cons "SHA256.txt")
Write-Host "Consegna pronta: $Dest"
Write-Host "ZIP: $Zip  (SHA256 $hash)"
