"""Interface graphique Tkinter de PlaylistOrdonner."""

import queue
import threading
import traceback
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, __version__, sorter
from .auth import REDIRECT_URI, AuthError, Authenticator
from .engine import DEST_IN_PLACE, DEST_NEW, Cancelled, Engine

DASHBOARD_URL = "https://developer.spotify.com/dashboard"
GREEN = "#1db954"
DARK = "#191414"

AIDE = """Pour que l'application puisse parler à ton compte Spotify, il lui faut
l'identifiant d'une « application Spotify » à ton nom. C'est gratuit et ça
prend deux minutes :

1. Ouvre le tableau de bord développeur Spotify et connecte-toi.
2. Clique sur « Create app ». Nom et description : ce que tu veux
   (par exemple « PlaylistOrdonner »).
3. Dans « Redirect URIs », colle exactement :  {redirect}
4. Coche « Web API », accepte les conditions, puis « Save ».
5. Ouvre l'app créée, « Settings », et copie le « Client ID ».
6. Colle-le ci-dessous. Le « Client Secret » n'est pas nécessaire.
""".format(redirect=REDIRECT_URI)


class App(tk.Tk):
    def __init__(self):
        tk.Tk.__init__(self)
        self.title("%s %s" % (APP_NAME, __version__))
        self.geometry("980x720")
        self.minsize(860, 620)

        self.auth = Authenticator()
        self.queue = queue.Queue()
        self.worker = None
        self.stop_flag = threading.Event()
        self.report = None
        self.playlists = []
        self.selected_id = None

        self._build()
        self._refresh_auth_state()
        self.after(80, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ mise en page
    def _build(self):
        header = tk.Frame(self, bg=DARK, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="  ⇅  " + APP_NAME, bg=DARK, fg="white",
            font=("Helvetica", 18, "bold"),
        ).pack(side="left", padx=(14, 0))
        tk.Label(
            header, text="genres du plus calme au plus énergique, puis BPM croissant",
            bg=DARK, fg="#b3b3b3", font=("Helvetica", 12),
        ).pack(side="left", padx=12)
        self.account_label = tk.Label(
            header, text="", bg=DARK, fg=GREEN, font=("Helvetica", 12, "bold")
        )
        self.account_label.pack(side="right", padx=14)

        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)

        self.setup_frame = self._build_setup(self.body)
        self.main_frame = self._build_main(self.body)

        footer = ttk.Frame(self, padding=(12, 0, 12, 10))
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        self.status = ttk.Label(footer, text="Prêt.", anchor="w")
        self.status.pack(fill="x", pady=(4, 0))

    def _build_setup(self, parent):
        frame = ttk.Frame(parent)
        ttk.Label(
            frame, text="Première configuration", font=("Helvetica", 15, "bold")
        ).pack(anchor="w")
        text = tk.Text(frame, height=13, wrap="word", relief="flat",
                       background="#f4f4f4", font=("Helvetica", 12))
        text.insert("1.0", AIDE)
        text.configure(state="disabled")
        text.pack(fill="x", pady=10)

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Button(row, text="Ouvrir le tableau de bord Spotify",
                   command=lambda: webbrowser.open(DASHBOARD_URL)).pack(side="left")
        ttk.Button(row, text="Copier l'adresse de redirection",
                   command=self._copy_redirect).pack(side="left", padx=8)

        row2 = ttk.Frame(frame)
        row2.pack(fill="x", pady=16)
        ttk.Label(row2, text="Client ID :").pack(side="left")
        self.client_id_var = tk.StringVar(value=self.auth.client_id)
        entry = ttk.Entry(row2, textvariable=self.client_id_var, width=44)
        entry.pack(side="left", padx=8)
        entry.bind("<Return>", lambda _event: self._save_client_id())
        ttk.Button(row2, text="Enregistrer et se connecter",
                   command=self._save_client_id).pack(side="left")
        return frame

    def _build_main(self, parent):
        frame = ttk.Frame(parent)

        panes = ttk.Frame(frame)
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Tes playlists", font=("Helvetica", 13, "bold")).pack(anchor="w")

        search_row = ttk.Frame(left)
        search_row.pack(fill="x", pady=(6, 4))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_a: self._fill_playlists())
        ttk.Entry(search_row, textvariable=self.search_var).pack(side="left", fill="x", expand=True)
        ttk.Button(search_row, text="Actualiser", width=11,
                   command=self.load_playlists).pack(side="left", padx=(6, 0))

        columns = ("titres",)
        self.tree = ttk.Treeview(left, columns=columns, show="tree headings", height=14)
        self.tree.heading("#0", text="Nom")
        self.tree.heading("titres", text="Titres")
        self.tree.column("#0", width=300, stretch=True)
        self.tree.column("titres", width=70, anchor="e", stretch=False)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(panes, padding=(14, 0, 0, 0))
        right.pack(side="left", fill="y")
        ttk.Label(right, text="Options", font=("Helvetica", 13, "bold")).pack(anchor="w")

        self.group_var = tk.StringVar(value=sorter.GROUP_BY_FAMILY)
        box = ttk.LabelFrame(right, text="Regroupement des genres", padding=8)
        box.pack(fill="x", pady=8)
        ttk.Radiobutton(box, text="Par famille (Pop, Rock, Techno…)",
                        variable=self.group_var, value=sorter.GROUP_BY_FAMILY).pack(anchor="w")
        ttk.Radiobutton(box, text="Genre Spotify exact (plus fin)",
                        variable=self.group_var, value=sorter.GROUP_BY_GENRE).pack(anchor="w")

        self.dest_var = tk.StringVar(value=DEST_NEW)
        box2 = ttk.LabelFrame(right, text="Destination", padding=8)
        box2.pack(fill="x", pady=8)
        ttk.Radiobutton(box2, text="Créer une nouvelle playlist",
                        variable=self.dest_var, value=DEST_NEW,
                        command=self._sync_dest).pack(anchor="w")
        ttk.Radiobutton(box2, text="Réordonner la playlist d'origine",
                        variable=self.dest_var, value=DEST_IN_PLACE,
                        command=self._sync_dest).pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Label(box2, text="Nom de la nouvelle playlist :").pack(anchor="w", pady=(6, 0))
        self.name_entry = ttk.Entry(box2, textvariable=self.name_var, width=30)
        self.name_entry.pack(fill="x")
        self.public_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(box2, text="Playlist publique", variable=self.public_var).pack(anchor="w", pady=(4, 0))

        box3 = ttk.LabelFrame(right, text="BPM et énergie", padding=8)
        box3.pack(fill="x", pady=8)
        self.deezer_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            box3, text="Compléter les BPM via Deezer", variable=self.deezer_var
        ).pack(anchor="w")
        self.refine_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            box3, text="Affiner l'ordre des genres avec\nl'énergie mesurée des titres",
            variable=self.refine_var,
        ).pack(anchor="w")

        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=10)
        self.analyse_btn = ttk.Button(actions, text="1 · Analyser et classer",
                                      command=self.start_analyse)
        self.analyse_btn.pack(fill="x")
        self.write_btn = ttk.Button(actions, text="2 · Enregistrer sur Spotify",
                                    command=self.start_write, state="disabled")
        self.write_btn.pack(fill="x", pady=6)
        self.export_btn = ttk.Button(actions, text="Exporter la liste (.txt)",
                                     command=self.export, state="disabled")
        self.export_btn.pack(fill="x")
        self.cancel_btn = ttk.Button(actions, text="Annuler", command=self.cancel,
                                     state="disabled")
        self.cancel_btn.pack(fill="x", pady=6)
        ttk.Button(actions, text="Se connecter à Spotify",
                   command=self.start_login).pack(fill="x")
        ttk.Button(actions, text="Se déconnecter",
                   command=self.logout).pack(fill="x", pady=(6, 0))
        ttk.Button(actions, text="Changer d'application Spotify",
                   command=self.change_client_id).pack(fill="x", pady=(6, 0))

        ttk.Label(frame, text="Journal", font=("Helvetica", 13, "bold")).pack(anchor="w", pady=(10, 2))
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=12, wrap="word", relief="flat",
                                background="#fbfbfb", font=("Menlo", 11))
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="left", fill="y")
        return frame

    # ------------------------------------------------------------------ état
    def _refresh_auth_state(self):
        self.setup_frame.pack_forget()
        self.main_frame.pack_forget()
        if not self.auth.has_client_id:
            self.setup_frame.pack(fill="both", expand=True)
            self.account_label.config(text="non configuré")
            return
        self.main_frame.pack(fill="both", expand=True)
        if self.auth.is_logged_in:
            self.account_label.config(text="connecté")
            self.load_playlists()
        else:
            self.account_label.config(text="déconnecté")
            self.start_login()

    def _copy_redirect(self):
        self.clipboard_clear()
        self.clipboard_append(REDIRECT_URI)
        self.set_status("Adresse copiée : %s" % REDIRECT_URI)

    def _save_client_id(self):
        value = self.client_id_var.get().strip()
        if len(value) < 20:
            messagebox.showwarning(
                APP_NAME, "Ce Client ID semble incomplet. Copie-le entièrement "
                "depuis le tableau de bord Spotify."
            )
            return
        self.auth.set_client_id(value)
        self._refresh_auth_state()

    def logout(self):
        self.auth.logout()
        self.report = None
        self.tree.delete(*self.tree.get_children())
        self.playlists = []
        self.write_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.account_label.config(text="déconnecté")
        self.log("Déconnecté. Relance la connexion quand tu veux.")
        self.start_login()

    def change_client_id(self):
        """Revient à l'écran de configuration pour saisir un autre Client ID.

        Nécessaire quand l'application Spotify déclarée est bloquée côté
        Spotify : il faut alors en créer une autre et repartir de son
        identifiant.
        """
        self.stop_flag.set()
        self.auth.logout()
        self.report = None
        self.playlists = []
        self.tree.delete(*self.tree.get_children())
        self.client_id_var.set(self.auth.client_id)
        self.main_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True)
        self.account_label.config(text="non configuré")
        self.set_status(
            "Colle le Client ID de ta nouvelle application Spotify, puis "
            "enregistre."
        )

    def _sync_dest(self):
        state = "normal" if self.dest_var.get() == DEST_NEW else "disabled"
        self.name_entry.config(state=state)

    def _on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        self.selected_id = selection[0]
        playlist = self._playlist(self.selected_id)
        if playlist:
            self.name_var.set(_suffixed(playlist["name"]))
            if not playlist.get("accessible", True):
                self.log(
                    "Attention : « %s » a été créée par Spotify. Depuis fin "
                    "2024, ces playlists sont fermées aux applications "
                    "récentes et l'analyse échouera avec une erreur 403."
                    % playlist["name"]
                )
            if not playlist["editable"] and self.dest_var.get() == DEST_IN_PLACE:
                self.dest_var.set(DEST_NEW)
                self._sync_dest()
                self.log(
                    "« %s » ne t'appartient pas : le résultat ira dans une "
                    "nouvelle playlist." % playlist["name"]
                )
        self.report = None
        self.write_btn.config(state="disabled")
        self.export_btn.config(state="disabled")

    def _playlist(self, playlist_id):
        for playlist in self.playlists:
            if playlist["id"] == playlist_id:
                return playlist
        return None

    def _fill_playlists(self):
        needle = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        seen = set()
        for playlist in self.playlists:
            if playlist["id"] in seen:
                continue
            seen.add(playlist["id"])
            if needle and needle not in playlist["name"].lower():
                continue
            total = playlist["total"]
            self.tree.insert(
                "", "end", iid=playlist["id"], text=playlist["name"],
                values=("" if total is None else total,),
            )

    # ------------------------------------------------------------------ journal
    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def set_status(self, message):
        self.status.config(text=message)

    def set_progress(self, done, total, label=""):
        total = max(1, total or 1)
        self.progress.config(value=100.0 * min(done, total) / total)
        if label:
            self.set_status("%s… %d/%d" % (label, done, total))

    # ------------------------------------------------------------------ tâches de fond
    def busy(self, active):
        state = "disabled" if active else "normal"
        self.analyse_btn.config(state=state)
        self.cancel_btn.config(state="normal" if active else "disabled")
        if active:
            self.write_btn.config(state="disabled")

    def run_async(self, work, done_message=None):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_NAME, "Une opération est déjà en cours.")
            return
        self.stop_flag.clear()
        self.busy(True)

        def runner():
            try:
                result = work()
                self.queue.put(("done", result, done_message))
            except Cancelled:
                self.queue.put(("cancelled", None, None))
            except Exception as exc:  # remonté proprement dans l'interface
                self.queue.put(("error", exc, traceback.format_exc()))

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def cancel(self):
        self.stop_flag.set()
        self.set_status("Annulation en cours…")

    def _drain(self):
        try:
            while True:
                kind, payload, extra = self.queue.get_nowait()
                self._handle(kind, payload, extra)
        except queue.Empty:
            pass
        self.after(80, self._drain)

    def _handle(self, kind, payload, extra):
        try:
            if kind == "log":
                self.log(payload)
            elif kind == "progress":
                self.set_progress(payload[0], payload[1], payload[2])
            elif kind == "done":
                self.busy(False)
                self.progress.config(value=0)
                self._on_done(payload, extra)
            elif kind == "cancelled":
                self.busy(False)
                self.progress.config(value=0)
                self.set_status("Annulé.")
                self.log("Opération annulée.")
            elif kind == "error":
                self.busy(False)
                self.progress.config(value=0)
                self._on_error(payload, extra)
        except tk.TclError:
            pass

    def _on_done(self, result, message):
        if isinstance(result, list):  # liste de playlists
            self.playlists = result
            self._fill_playlists()
            self.set_status("%d playlist(s) chargée(s)." % len(result))
            return
        if result == "login":
            self.account_label.config(text="connecté")
            self.set_status("Connexion réussie.")
            self.load_playlists()
            return
        if hasattr(result, "groups"):
            self.report = result
            self.log("")
            self.log(result.text())
            self.log("")
            self.log(result.tracklist())
            self.export_btn.config(state="normal")
            if result.written:
                self.write_btn.config(state="disabled")
                self.set_status(message or "Terminé.")
                if result.target_url and messagebox.askyesno(
                    APP_NAME,
                    "C'est fait, chef !\n\n« %s » contient %d titres classés par "
                    "genre puis par BPM.\n\nL'ouvrir dans Spotify ?"
                    % (result.target_name, len(result.tracks)),
                ):
                    webbrowser.open(result.target_url)
            else:
                self.write_btn.config(state="normal")
                self.set_status(
                    "Classement prêt — vérifie la liste puis clique sur "
                    "« 2 · Enregistrer sur Spotify »."
                )
            return
        self.set_status(message or "Terminé.")

    def _on_error(self, exc, details):
        self.log("Erreur : %s" % exc)
        if details:
            self.log(details.strip().splitlines()[-1])
        self.set_status("Erreur.")
        if self.report is not None and not self.report.written:
            self.write_btn.config(state="normal")
        if isinstance(exc, AuthError):
            self.account_label.config(text="déconnecté")
            messagebox.showerror(APP_NAME, str(exc))
        else:
            messagebox.showerror(APP_NAME, str(exc) or exc.__class__.__name__)

    def _engine(self):
        return Engine(
            self.auth,
            log=lambda message: self.queue.put(("log", message, None)),
            progress=lambda done, total, label="": self.queue.put(
                ("progress", (done, total, label), None)
            ),
            stop=self.stop_flag.is_set,
        )

    # ------------------------------------------------------------------ actions
    def start_login(self):
        self.log("Ouverture de Spotify dans ton navigateur pour autoriser l'accès…")

        def work():
            self.auth.login(
                on_open_url=lambda url: self.queue.put(
                    ("log", "Si rien ne s'ouvre, copie cette adresse :\n" + url, None)
                )
            )
            return "login"

        self.run_async(work)

    def load_playlists(self):
        if not self.auth.is_logged_in:
            self.start_login()
            return
        self.set_status("Chargement des playlists…")
        self.run_async(lambda: self._engine().list_playlists())

    def start_analyse(self):
        if not self.selected_id:
            messagebox.showinfo(APP_NAME, "Choisis d'abord une playlist dans la liste.")
            return
        playlist_id = self.selected_id
        group_mode = self.group_var.get()
        use_deezer = self.deezer_var.get()
        refine = self.refine_var.get()
        self.report = None
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        self.run_async(
            lambda: self._engine().analyse(
                playlist_id, group_mode=group_mode,
                use_deezer=use_deezer, refine_with_audio=refine,
            )
        )

    def start_write(self):
        if not self.report:
            return
        report = self.report
        playlist_id = self.selected_id
        destination = self.dest_var.get()
        name = self.name_var.get()
        public = self.public_var.get()
        if destination == DEST_IN_PLACE and not messagebox.askyesno(
            APP_NAME,
            "La playlist « %s » va être réécrite dans le nouvel ordre.\n"
            "Les titres restent les mêmes, seul l'ordre change.\n\nOn y va ?"
            % report.playlist_name,
        ):
            return

        engine = self._engine()
        self.run_async(
            lambda: engine.write(report, playlist_id, destination, name, public),
            done_message="Enregistré sur Spotify.",
        )

    def export(self):
        if not self.report:
            return
        path = filedialog.asksaveasfilename(
            title="Exporter le classement",
            defaultextension=".txt",
            initialfile="%s - classement.txt" % self.report.playlist_name,
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("%s — %s\n\n" % (APP_NAME, self.report.playlist_name))
                fh.write(self.report.text())
                fh.write("\n\n")
                fh.write(self.report.tracklist())
                fh.write("\n")
        except OSError as exc:
            messagebox.showerror(APP_NAME, "Écriture impossible : %s" % exc)
            return
        self.set_status("Exporté dans %s" % path)

    def _on_close(self):
        self.stop_flag.set()
        self.destroy()


def _suffixed(name):
    base = (name or "Playlist").strip()
    suffix = " (ordonnée)"
    if len(base) + len(suffix) > 100:
        base = base[: 100 - len(suffix)].rstrip()
    return base + suffix


def main():
    app = App()
    try:
        app.tk.call("tk", "scaling", 1.4)
    except tk.TclError:
        pass
    app.mainloop()
    return 0
