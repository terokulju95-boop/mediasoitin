"""Mediasoitin – käynnistä:  python mediasoitin.py [tiedostot...]"""
import sys


def main():
    try:
        from soitin.app import main as run
    except OSError as e:  # libmpv-2.dll puuttuu
        from PySide6.QtWidgets import QApplication, QMessageBox
        QApplication(sys.argv)
        QMessageBox.critical(
            None, "Mediasoitin",
            "Toistomoottoria (libmpv-2.dll) ei löytynyt.\n\n"
            "Lataa valmis versio GitHubin Releases-sivulta tai aja\n"
            "tools/hae_libmpv.ps1 projektikansiossa.\n\n" + str(e))
        sys.exit(1)
    run()


if __name__ == "__main__":
    main()
