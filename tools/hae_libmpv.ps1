# Lataa uusin libmpv-2.dll (mpv:n toistomoottori) projektin juureen.
# Käyttö PowerShellissä projektikansiossa:  ./tools/hae_libmpv.ps1
# Lähde: https://github.com/shinchiro/mpv-winbuild-cmake (64-bit, ei AVX2-vaatimusta)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$headers = @{ "User-Agent" = "Mediasoitin" }
if ($env:GH_TOKEN) { $headers["Authorization"] = "Bearer $env:GH_TOKEN" }

$rel = Invoke-RestMethod -Headers $headers "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
$asset = $rel.assets | Where-Object { $_.name -match '^mpv-dev-x86_64-\d{8}-git-.*\.7z$' } | Select-Object -First 1
if (-not $asset) { throw "libmpv-pakettia ei löytynyt julkaisusta $($rel.tag_name)" }

Write-Host "Ladataan $($asset.name)..."
$tmp = Join-Path ([IO.Path]::GetTempPath()) $asset.name
Invoke-WebRequest -Headers $headers $asset.browser_download_url -OutFile $tmp

$sevenZip = (Get-Command 7z -ErrorAction SilentlyContinue).Source
if (-not $sevenZip) { $sevenZip = "C:\Program Files\7-Zip\7z.exe" }
if (-not (Test-Path $sevenZip)) { throw "7-Zip puuttuu. Asenna se osoitteesta https://www.7-zip.org/" }

& $sevenZip e $tmp "libmpv-2.dll" "-o$root" -y | Out-Null
Remove-Item $tmp
if (-not (Test-Path (Join-Path $root "libmpv-2.dll"))) { throw "libmpv-2.dll:n purku epäonnistui" }
Write-Host "Valmis: $root\libmpv-2.dll"
