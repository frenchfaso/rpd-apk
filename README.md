# Raspberry Pi Desktop per Lenovo M10

Desktop Raspberry Pi OS **ARM Trixie** su postmarketOS/Alpine, con menu, tema,
LightDM, Chromium, VLC e utility essenziali. Include le integrazioni M10 per touch,
rotazione, tastiera virtuale, Bluetooth, USB OTG, luminosità e batteria.
È un port del desktop: il sistema resta postmarketOS, aggiornabile tramite APK.

## Installazione

Per **Lenovo Tab M10 TB-X505L**, già avviato con **postmarketOS edge aarch64,
systemd**, Wi-Fi funzionante e un utente esistente con `sudo`.
Usare un’installazione senza il profilo console/Buffyboard: LightDM sarà il login principale.
Questi comandi non installano postmarketOS e non sbloccano il tablet.

```sh
# Aggiungi repository e chiave di firma; aggiorna l’indice APK.
wget https://raw.githubusercontent.com/frenchfaso/rpd-apk/main/scripts/install-repository.sh
sudo sh install-repository.sh

# Installa il desktop e configura i servizi.
sudo apk add rpd-desktop-m10
sudo rpd-configure-host frenchfaso
sudo reboot
```

Sostituisci `frenchfaso` con il tuo utente. Al riavvio accedi dal login grafico.

## Aggiornamenti

```sh
sudo apk update && sudo apk upgrade
```

GitHub Actions segue le release ufficiali dei componenti Raspberry e pubblica gli APK
firmati dopo build e verifiche. Le modifiche upstream incompatibili possono richiedere
intervento manuale. I pacchetti specifici delle board Raspberry sono esclusi.
Gli aggiornamenti del kernel non vengono bloccati: i moduli M10 richiedono una build
compatibile e possono restare temporaneamente inattivi.

Il metapacchetto ricrea desktop e integrazioni, non file personali, credenziali Wi-Fi
o storico di calibrazione. Percentuale e autonomia della batteria sono stime.

Dettagli: [desktop](docs/DESKTOP.md), [batteria](docs/BATTERY-TELEMETRY.md),
[USB OTG](docs/M10-USB-OTG.md), [build e repository](docs/REPOSITORY.md).
