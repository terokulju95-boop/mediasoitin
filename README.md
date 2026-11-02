# Mediasoitin

Windows-mediasoitin, joka toistaa musiikkia ja videoita tietokoneen levyiltä, CD/DVD-asemalta ja ulkoisilta kiintolevyiltä tai muistitikuilta. Se ei tallenna mitään, se vain toistaa.

Toistomoottorina on **mpv (libmpv + FFmpeg)**, joten käytännössä kaikki tiedostomuodot toimivat, myös ne, joita Windows Media Player ei suostu toistamaan.

## Ominaisuudet

- **Kaikki yleiset ja harvinaisemmat muodot**
  - Ääni: FLAC, ALAC, APE, WavPack, DSD (DSF/DFF), WMA, Opus, Ogg, MP3, AAC, AC3, DTS, TrueHD, WAV, AIFF ym.
  - Video: MKV, MP4, AVI, MOV, WMV, TS/M2TS, VOB, WebM ym. Koodekit H.264, HEVC, AV1, VP9, MPEG-2 ym. HDR-videot toimivat.
- **Musiikki-CD:t.** Raidat luetaan suoraan levyltä digitaalisena äänenä (ei muunnosta). Kappaleet näkyvät soittolistassa, ja toisto on saumaton.
- **DVD-levyt** valikkoineen sekä VIDEO_TS-kansiot ja .iso-levykuvat.
- **Ulkoiset levyt ja muistitikut** näkyvät asemaluettelossa automaattisesti, kun ne kytketään.
- **Bit-perfect-ääni** (WASAPI exclusive): ääni menee äänikortille/DAC:lle täsmälleen sellaisenaan. Tilarivin merkkivalo kertoo, onko ääni bit-perfect, ja jos ei ole, miksi.
- **Saumaton toisto** (gapless) albumeille ja live-levyille.
- **Paras kuvanlaatu.** Käytössä on mpv:n *high-quality*-profiili ja laitteistopurku, joka ei heikennä kuvaa.
- Soittolista (sekoitus, toisto, järjestely), ääniraidan ja tekstityksen valinta, äänilaitteen valinta, koko näyttö sekä raahaa ja pudota.

## Lataus ja asennus (helpoin tapa)

1. Avaa GitHubissa tämän repon **Releases**-sivu.
2. Lataa `Mediasoitin-windows-x64.zip`.
3. Pura zip haluamaasi kansioon (esim. `C:\Ohjelmat\Mediasoitin`).
4. Käynnistä `Mediasoitin.exe`.

Asennusta ei tarvita. Jos haluat avata tiedostot aina tällä soittimella, valitse tiedostosta *Avaa sovelluksessa → Valitse toinen sovellus → Mediasoitin.exe*.

## Käyttö

| Toiminto | Miten |
|---|---|
| Toista tiedosto | Tuplaklikkaa tiedostoa. Saman kansion muut kappaleet tulevat jonoon. |
| Toista CD tai DVD | Tuplaklikkaa levyä asemaluettelossa, tai *Tiedosto → Toista levy*. |
| Toista koko kansio | ▶-painike polun vieressä, tai hiiren oikea → *Toista kansio* |
| Koko näyttö | Tuplaklikkaa videota tai paina F. Esc palaa. |
| Toista/tauko | Välilyönti, tai hiiren oikea videon päällä |
| Kelaus | Videon päällä ← → (5 s), muualla Shift + ← → (10 s) |
| Äänenvoimakkuus | Videon päällä ↑ ↓ tai hiiren rulla, muualla Ctrl + ↑ ↓ |
| Seuraava/edellinen | Ctrl + → / Ctrl + ←, tai mediapainikkeet |
| Tiedoston tekniset tiedot | Ctrl + I |

### Bit-perfect-ääni

Laita **Bit-perfect** päälle ohjainpalkista (tai *Ääni → Bit-perfect*). Silloin:

- Windows ei miksaa eikä muunna ääntä, ja esim. 96 kHz / 24-bit FLAC menee DAC:lle sellaisenaan.
- Muiden ohjelmien äänet eivät kuulu sillä aikaa.
- **Windowsin äänenvoimakkuussäädin ei vaikuta.** Pidä soittimen äänenvoimakkuus 100 %:ssa ja säädä vahvistimesta tai kuulokevahvistimesta. ⚠️ Laske vahvistimen voimakkuus ennen kuin otat tilan käyttöön, ettei ääni tule yllättäen täysillä.

Tilarivin oikeassa reunassa näkyy ● **Bit-perfect** (vihreä) tai ● **Ei bit-perfect** (oranssi). Vie hiiri merkin päälle, niin näet syyn.

## Kehittäjälle: ajo lähdekoodista

Tarvitset Python 3.10+:n ja [7-Zipin](https://www.7-zip.org/).

```powershell
git clone https://github.com/<käyttäjä>/mediasoitin.git
cd mediasoitin
pip install -r requirements.txt
./tools/hae_libmpv.ps1        # lataa libmpv-2.dll projektikansioon
python mediasoitin.py
```

### Uuden version julkaisu

GitHub Actions rakentaa `.exe`:n automaattisesti (`.github/workflows/build.yml`):

- Jokaisen pushin jälkeen valmis zip löytyy **Actions**-välilehdeltä kohdasta *Artifacts*.
- Kun haluat julkaista version Releases-sivulle:
  ```
  git tag v1.0.0
  git push origin v1.0.0
  ```

### Rakenne

```
mediasoitin.py          käynnistys
soitin/app.py           pääikkuna: selain, soittolista, ohjaimet
soitin/player.py        mpv-moottori upotettuna ikkunaan, laatuasetukset
soitin/cdaudio.py       musiikki-CD:n suora digitaalinen luku (Windows)
soitin/drives.py        asemien tunnistus (kiintolevy, USB, CD/DVD)
soitin/media.py         tiedostotyypit ja apufunktiot
tools/hae_libmpv.ps1    libmpv:n lataus
```

## Rajoitukset

- Kopiosuojattuja Blu-ray-levyjä (AACS) ei voi toistaa. Tämä koskee kaikkia vapaita soittimia.
- Suojattuja DVD-levyjä (CSS) toistetaan libdvdcss-kirjaston avulla, jos se sisältyy libmpv-pakettiin.

## Lisenssi

Soitin käyttää mpv:tä ja FFmpegiä, jotka ovat GPL/LGPL-lisensoituja. Jos jaat ohjelmaa, julkaise myös sen lähdekoodi (tämä repo riittää).
