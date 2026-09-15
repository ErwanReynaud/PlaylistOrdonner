"""Point d'entrée : interface graphique par défaut, ligne de commande sinon."""

import sys


def main():
    argv = sys.argv[1:]
    if argv:
        from .cli import main as cli_main

        return cli_main(argv)
    try:
        from .gui import main as gui_main
    except ImportError as exc:  # Tkinter absent de cette installation de Python
        print(
            "L'interface graphique n'est pas disponible (%s).\n"
            "Utilise la ligne de commande, par exemple :\n"
            "  python3 -m playlistordonner playlists" % exc
        )
        return 1
    try:
        return gui_main()
    except Exception as exc:  # pas d'écran disponible
        if "display" in str(exc).lower() or "DISPLAY" in str(exc):
            print("Aucun écran disponible : utilise la ligne de commande.")
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
