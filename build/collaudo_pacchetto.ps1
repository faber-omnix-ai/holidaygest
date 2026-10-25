<#
Collaudo automatico del PACCHETTO (non dei sorgenti). Solo dati sintetici, nessun contatto con i portali.
Uso: pwsh -File build\collaudo_pacchetto.ps1 -Zip <zip> -Lavoro <cartella breve> -Python <python per lo script e2e>
Il Python indicato serve SOLO al client di prova (tests/e2e_pacchetto.py): l'eseguibile è avviato con un
ambiente minimo (PATH = System32 e Windows) e non usa quel Python.
#>
param([string]$Zip, [string]$Lavoro = "$env:TEMP\gcb\collaudo", [string]$Python)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$E2E = Join-Path $Root "tests\e2e_pacchetto.py"
if (Test-Path $Lavoro) { Remove-Item -Recurse -Force $Lavoro }
$Usb = Join-Path $Lavoro "Chiavetta E è"
$Pc = Join-Path $Lavoro "PC prova\Documenti à"
$Lad = Join-Path $Lavoro "PC prova\AppData Local"
New-Item -ItemType Directory -Force $Usb, $Pc, $Lad | Out-Null
$risultati = @()
function Esito($nome, $ok, $dett = "") {
    $script:risultati += [pscustomobject]@{Prova = $nome; Esito = $(if ($ok) { "OK" } else { "FALLITO" }); Dettaglio = $dett }
    Write-Host ("{0:HH:mm:ss} {1} {2}" -f (Get-Date), $(if ($ok) { "OK  " } else { "FAIL" }), $nome)
}

function Avvia([string]$exe, [string[]]$argomenti, [string]$lad) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo $exe
    $psi.Arguments = ($argomenti -join " ")
    $psi.UseShellExecute = $false
    $psi.Environment.Clear()
    foreach ($k in 'SystemRoot','SystemDrive','WINDIR','TEMP','TMP','USERPROFILE','APPDATA','COMPUTERNAME','USERNAME',
                   'HOMEDRIVE','HOMEPATH','ProgramData','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS','ComSpec') {
        $psi.Environment[$k] = [Environment]::GetEnvironmentVariable($k)
    }
    $psi.Environment['PATH'] = "$env:SystemRoot\System32;$env:SystemRoot"
    $psi.Environment['LOCALAPPDATA'] = $lad   # cartella dati predefinita = %LOCALAPPDATA%\HolidayGest
    return [System.Diagnostics.Process]::Start($psi)
}
function Attendi([int]$porta) {
    for ($i = 0; $i -lt 80; $i++) {
        Start-Sleep -Milliseconds 500
        try { return Invoke-RestMethod "http://127.0.0.1:$porta/api/status" -TimeoutSec 2 } catch {}
    }
    return $null
}

# 1. Dalla chiavetta al PC
Expand-Archive -Path $Zip -DestinationPath $Usb
Copy-Item -Recurse (Join-Path $Usb "HolidayGest") $Pc
$App = Join-Path $Pc "HolidayGest"
$Exe = Join-Path $App "AvviaGestionale.exe"
Esito "Estrazione ZIP su chiavetta e copia sul PC (percorsi con spazi e accenti)" (Test-Path $Exe) $App

# 2. Primo avvio e flusso completo
$p = Avvia $Exe @("--headless", "--no-browser", "--port", "47740") $Lad
$st = Attendi 47740
Esito "Avvio senza Python/Node nel PATH" ($null -ne $st) "dati: $($st.data_dir)"
Esito "Cartella dati predefinita nel profilo, separata dal programma" ($st.data_dir -eq (Join-Path $Lad "HolidayGest")) $st.data_dir
$mods = (Get-Process -Id $p.Id).Modules | Where-Object { $_.FileName -notlike "$env:SystemRoot*" -and $_.FileName -notlike "$App*" -and $_.FileName -notlike "*Bitdefender*" -and $_.FileName -notlike "$env:ProgramData\Microsoft\Windows Defender\*" }  # antivirus: iniettati in ogni processo
Esito "Nessuna DLL caricata da installazioni esterne (Python, Node)" (-not $mods) (($mods | ForEach-Object FileName) -join "; ")
$out = & $Python $E2E "http://127.0.0.1:47740" --salva (Join-Path $Lavoro "file_generati") 2>&1
Esito "Flusso end-to-end sul pacchetto (tests/e2e_pacchetto.py, file verificati da build/verifica_tracciati.py)" ($LASTEXITCODE -eq 0) (($out | Select-Object -Last 1) -join "")
$out | Set-Content (Join-Path $Lavoro "e2e_primo_avvio.txt")
$p.WaitForExit(30000) | Out-Null
$bk = Get-ChildItem (Join-Path $Lad "HolidayGest\backup") -Filter "*_chiusura.gcbak" -ErrorAction SilentlyContinue
Esito "Chiusura ordinata con backup automatico" ($p.HasExited -and $bk) ($bk.Name -join ", ")

# 3. Riavvio e persistenza
$p = Avvia $Exe @("--headless", "--no-browser", "--port", "47740") $Lad
$null = Attendi 47740
$out = & $Python $E2E "http://127.0.0.1:47740" --riavvio 2>&1
Esito "Riavvio: dati conservati" ($LASTEXITCODE -eq 0) (($out | Select-Object -Last 1) -join "")
$p.WaitForExit(30000) | Out-Null

# 4. Aggiornamento del programma: la cartella programma viene sostituita, i dati restano
Remove-Item -Recurse -Force $App
Copy-Item -Recurse (Join-Path $Usb "HolidayGest") $Pc
$p = Avvia $Exe @("--headless", "--no-browser", "--port", "47740") $Lad
$null = Attendi 47740
$out = & $Python $E2E "http://127.0.0.1:47740" --riavvio 2>&1
Esito "Sostituzione della cartella programma: dati conservati" ($LASTEXITCODE -eq 0) (($out | Select-Object -Last 1) -join "")
$p.WaitForExit(30000) | Out-Null

# 5. Porta predefinita occupata + seconda istanza
$occupante = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 47615)
$occupante.Start()
$p = Avvia $Exe @("--headless", "--no-browser") $Lad
Start-Sleep 4
$porta = [int](Get-Content (Join-Path $Lad "HolidayGest\gestionale.port"))
$st = Attendi $porta
Esito "Porta predefinita occupata: usata un'altra porta locale" ($porta -ne 47615 -and $st) "porta $porta"
$p2 = Avvia $Exe @("--headless", "--no-browser") $Lad
Write-Host "attesa seconda istanza"; $p2.WaitForExit(20000) | Out-Null; Write-Host "seconda istanza terminata: $($p2.HasExited)"
Esito "Seconda istanza: non avvia un secondo server" ($p2.HasExited -and $p2.ExitCode -eq 3 -and -not $p.HasExited) "codice uscita $($p2.ExitCode)"
$net = netstat -ano | Select-String ":$porta " | Select-String "LISTENING"
Esito "Servizio in ascolto solo su 127.0.0.1" (($net | Where-Object { $_ -notmatch "127\.0\.0\.1:$porta" }).Count -eq 0) (($net | ForEach-Object { $_.Line.Trim() }) -join " | ")
$occupante.Stop()
$p.Kill(); $p.WaitForExit(10000) | Out-Null   # chiusura forzata: simula anche uno spegnimento improvviso
Write-Host "passo 5 concluso"

# 6. Modalità portatile (distinta): dati accanto al programma
New-Item -ItemType File (Join-Path $App "MODALITA_PORTATILE.txt") | Out-Null
$p = Avvia $Exe @("--headless", "--no-browser", "--port", "47741") $Lad
$st = Attendi 47741
Esito "Modalità portatile: dati nella cartella del programma" ($st.portable -and $st.data_dir -eq (Join-Path $App "DatiGestionale")) $st.data_dir
$p.Kill(); $p.WaitForExit(10000) | Out-Null
Remove-Item (Join-Path $App "MODALITA_PORTATILE.txt")
Remove-Item -Recurse -Force (Join-Path $App "DatiGestionale")

# 7. Pacchetto e log puliti
$pkg = Join-Path $Usb "HolidayGest"
$trovati = Get-ChildItem -Recurse -File $pkg | Select-String -SimpleMatch -Pattern "Referente Collaudo", "collaudo-pacchetto-2026", "COLLAUDO" -List -ErrorAction SilentlyContinue
$dati = Get-ChildItem -Recurse -File $pkg | Where-Object { $_.Extension -in ".sqlite3", ".gcbak", ".log" }
Esito "Pacchetto di consegna senza dati di prova, archivi o log" (-not $trovati -and -not $dati)
$log = Get-ChildItem -Recurse -File (Join-Path $Lad "HolidayGest\log")
$inLog = $log | Select-String -SimpleMatch -Pattern "COLLAUDO", "Referente Collaudo", "CA00000", "ERIKSSON" -List
Esito "Log senza dati personali o documentali" (-not $inLog) (($log | ForEach-Object Name) -join ", ")

$risultati | Format-Table -AutoSize -Wrap | Out-String -Width 220
$risultati | Export-Csv -NoTypeInformation -Encoding utf8 (Join-Path $Lavoro "esito_collaudo.csv")
if ($risultati.Esito -contains "FALLITO") { exit 1 }
