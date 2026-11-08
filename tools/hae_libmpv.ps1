# Lataa uusin libmpv-2.dll (mpv:n toistomoottori) projektin juureen.
# Käyttö PowerShellissä projektikansiossa:  ./tools/hae_libmpv.ps1
# Lähde: https://github.com/shinchiro/mpv-winbuild-cmake (64-bit, ei AVX2-vaatimusta)
#
# GitHub vastaa joskus hetkellisesti virheellä ("Unicorn! ... couldn't respond in time"), ja tuoreen
# julkaisun tiedostot voivat olla vielä kesken. Siksi jokaista latausta yritetään useita kertoja,
# ja jos uusin julkaisu ei lataudu, käytetään edellisiä julkaisuja.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"     # nopeuttaa Invoke-WebRequestia huomattavasti
$root = Split-Path -Parent $PSScriptRoot
$headers = @{ "User-Agent" = "Mediasoitin" }
if ($env:GH_TOKEN) { $headers["Authorization"] = "Bearer $env:GH_TOKEN" }

function Retry([scriptblock]$Action, [string]$What, [int]$Tries = 5) {
    for ($i = 1; $i -le $Tries; $i++) {
        try { return & $Action }
        catch {
            $msg = $_.Exception.Message
            if ($msg.Length -gt 160) { $msg = $msg.Substring(0, 160) + "..." }
            if ($i -eq $Tries) { throw "$What epäonnistui $Tries kertaa: $msg" }
            $wait = 10 * $i
            Write-Host "$What epäonnistui (yritys $i/$Tries): $msg"
            Write-Host "Yritetään uudelleen $wait sekunnin kuluttua..."
            Start-Sleep -Seconds $wait
        }
    }
}

$sevenZip = (Get-Command 7z -ErrorAction SilentlyContinue).Source
if (-not $sevenZip) { $sevenZip = "C:\Program Files\7-Zip\7z.exe" }
if (-not (Test-Path $sevenZip)) { throw "7-Zip puuttuu. Asenna se osoitteesta https://www.7-zip.org/" }

$releases = Retry { Invoke-RestMethod -Headers $headers "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases?per_page=4" } "Julkaisulistan haku"

foreach ($rel in $releases) {
    $asset = $rel.assets | Where-Object { $_.name -match '^mpv-dev-x86_64-\d{8}-git-.*\.7z$' } | Select-Object -First 1
    if (-not $asset) { Write-Host "Julkaisussa $($rel.tag_name) ei ole libmpv-pakettia, ohitetaan."; continue }

    $tmp = Join-Path ([IO.Path]::GetTempPath()) $asset.name
    try {
        Retry {
            Write-Host "Ladataan $($asset.name)..."
            if (Test-Path $tmp) { Remove-Item $tmp -Force }
            Invoke-WebRequest -Headers $headers $asset.browser_download_url -OutFile $tmp
            # Tarkistetaan, että ladattu paketti on ehjä (ei puolikas tiedosto tai virhesivu).
            & $sevenZip t $tmp | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "ladattu paketti on rikki" }
        } "Lataus ($($asset.name))" 4

        & $sevenZip e $tmp "libmpv-2.dll" "-o$root" -y | Out-Null
        Remove-Item $tmp -Force
        if (-not (Test-Path (Join-Path $root "libmpv-2.dll"))) { throw "libmpv-2.dll:n purku epäonnistui" }
        Write-Host "Valmis: $root\libmpv-2.dll (julkaisu $($rel.tag_name))"
        exit 0
    }
    catch {
        Write-Host "Julkaisua $($rel.tag_name) ei saatu käyttöön: $($_.Exception.Message)"
        Write-Host "Kokeillaan edellistä julkaisua..."
        if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
    }
}
throw "libmpv-2.dll:ää ei saatu ladattua mistään julkaisusta. Kokeile myöhemmin uudelleen (Re-run failed jobs)."
