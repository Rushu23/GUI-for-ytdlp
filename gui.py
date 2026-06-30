#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
yt-dlp GUI dla Linux Mint / Linux

Wersja naprawiona:
- uproszczony widok podstawowy
- wszystkie mniej używane opcje w panelu "Zaawansowane"
- przycisk "Dodaj link" pod polem URL
- tooltipy dla opcji zaawansowanych
- zapis ustawień i kolejki do JSON
- kolorowe statusy kolejki
- pasek postępu
- ograniczenie spamu w logu
- wsparcie dla archive / retry / metadata / download-sections
"""

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class ToolTip:
    """
    Prosty tooltip dla widgetów tkinter/ttk.
    """

    def __init__(self, widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip_window = None

        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)
        self.widget.bind("<ButtonPress>", self.hide_tip)

    def show_tip(self, _event=None) -> None:
        """
        Pokazuje tooltip obok widgetu.
        """
        if self.tip_window or not self.text:
            return

        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            tw,
            text=self.text,
            justify="left",
            background="#111827",
            foreground="#f9fafb",
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=6,
            font=("Segoe UI", 9),
        )
        label.pack()

    def hide_tip(self, _event=None) -> None:
        """
        Ukrywa tooltip.
        """
        if self.tip_window is not None:
            self.tip_window.destroy()
            self.tip_window = None


class YtDlpGuiApp:
    """
    Główna klasa aplikacji.

    Odpowiada za:
    - budowę GUI
    - zapis/odczyt ustawień
    - zapis/odczyt kolejki
    - budowanie komend yt-dlp
    - uruchamianie pobrań w tle
    - pokazywanie logu i statusów
    """

    def __init__(self, root: tk.Tk) -> None:
        """
        Inicjalizacja aplikacji.
        """
        self.root = root
        self.root.title("yt-dlp GUI")
        self.root.geometry("1180x920")
        self.root.minsize(920, 620)

        self.settings_path = os.path.join(os.path.expanduser("~"), ".yt_dlp_gui_settings.json")
        self.queue_path = os.path.join(os.path.expanduser("~"), ".yt_dlp_gui_queue.json")

        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.process: subprocess.Popen | None = None
        self.is_queue_running = False
        self.stop_requested = False
        self.queue_items: list[dict] = []
        self.current_queue_index: int | None = None

        self.re_item_of_total = re.compile(r'item\s+(\d+)\s+of\s+(\d+)', re.IGNORECASE)
        self.re_download_list = re.compile(r'Downloading\s+(\d+)\s+items?\s+of\s+(\d+)', re.IGNORECASE)
        self.re_archive_skip = re.compile(r'has\s+already\s+been\s+recorded\s+in\s+the\s+archive', re.IGNORECASE)
        self.re_error_line = re.compile(r'^\s*ERROR:', re.IGNORECASE)
        self.re_percent = re.compile(r'\[download\]\s+(\d+(?:\.\d+)?)%')
        self.re_speed = re.compile(r'at\s+([0-9A-Za-z./~]+(?:B/s|iB/s))')
        self.re_eta = re.compile(r'ETA\s+([0-9:]+)')

        self.mousewheel_accumulator = 0.0

        self.progress_percent_var = tk.DoubleVar(value=0.0)
        self.progress_primary_var = tk.StringVar(value="Brak aktywnego pobierania")
        self.progress_secondary_var = tk.StringVar(value="")

        self.url_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=os.path.expanduser("~/Pobrane"))
        self.filename_template_var = tk.StringVar(value="%(title)s [%(id)s].%(ext)s")
        self.mode_var = tk.StringVar(value="best_mp4_archive_style")

        self.advanced_expanded_var = tk.BooleanVar(value=False)

        self.subtitles_var = tk.BooleanVar(value=False)
        self.playlist_var = tk.BooleanVar(value=False)
        self.write_thumbnail_var = tk.BooleanVar(value=False)
        self.playlist_items_var = tk.StringVar(value="")

        self.use_archive_var = tk.BooleanVar(value=True)
        self.archive_file_var = tk.StringVar(value=os.path.join(os.path.expanduser("~/Pobrane"), "archive.txt"))

        self.retries_var = tk.StringVar(value="")
        self.fragment_retries_var = tk.StringVar(value="")
        self.write_info_json_var = tk.BooleanVar(value=False)
        self.embed_metadata_var = tk.BooleanVar(value=False)
        self.embed_chapters_var = tk.BooleanVar(value=False)
        self.download_sections_var = tk.StringVar(value="")

        self._configure_style()
        self._build_ui()
        self._bind_shortcuts()
        self.load_settings()
        self.load_queue()
        self._refresh_queue_view()
        self._poll_log_queue()

        self._append_log("Uruchomiono GUI.")
        self._append_log("Naprawiona wersja została załadowana poprawnie.")

    def _configure_style(self) -> None:
        """
        Konfiguruje styl ttk.
        """
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")

        bg_main = "#f5f7fb"
        bg_card = "#ffffff"
        border = "#d8e0ea"
        text = "#1f2937"
        muted = "#5b6472"
        accent = "#16a34a"
        accent_hover = "#15803d"
        accent_disabled = "#9ccfb0"

        self.root.configure(bg=bg_main)

        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background=bg_main)
        style.configure("Card.TFrame", background=bg_card, relief="flat", borderwidth=0)
        style.configure("Header.TLabel", background=bg_main, foreground=text, font=("Segoe UI", 18, "bold"))
        style.configure("SubHeader.TLabel", background=bg_main, foreground=muted, font=("Segoe UI", 10))
        style.configure("Section.TLabelframe", background=bg_card, borderwidth=1, relief="solid")
        style.configure("Section.TLabelframe.Label", background=bg_card, foreground=text, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=bg_main, foreground=text)
        style.configure("FieldLabel.TLabel", background=bg_card, foreground=text, font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", background=bg_card, foreground=muted, font=("Segoe UI", 9))
        style.configure("CardTitle.TLabel", background=bg_card, foreground=text, font=("Segoe UI", 10, "bold"))
        style.configure("CardText.TLabel", background=bg_card, foreground=muted, font=("Segoe UI", 9))
        style.configure("TButton", padding=(10, 7))

        style.configure(
            "Accent.TButton",
            padding=(12, 8),
            font=("Segoe UI", 10, "bold"),
            background=accent,
            foreground="#ffffff",
            borderwidth=0,
            focusthickness=0,
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", accent_disabled), ("pressed", accent_hover), ("active", accent_hover)],
            foreground=[("disabled", "#f3f4f6"), ("pressed", "#ffffff"), ("active", "#ffffff")],
        )

        style.configure("Toggle.TButton", padding=(10, 7), font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", fieldbackground="#ffffff")
        style.configure("TCombobox", fieldbackground="#ffffff")
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Vertical.TScrollbar", arrowsize=14)
        style.configure(
            "Download.Horizontal.TProgressbar",
            troughcolor="#e5e7eb",
            background=accent,
            bordercolor="#e5e7eb",
            lightcolor=accent,
            darkcolor=accent,
            thickness=14,
        )

        self.colors = {
            "bg_main": bg_main,
            "bg_card": bg_card,
            "border": border,
            "text": text,
            "muted": muted,
            "accent": accent,
            "ok_bg": "#dcfce7",
            "ok_fg": "#166534",
            "run_bg": "#dbeafe",
            "run_fg": "#1d4ed8",
            "wait_bg": "#f3f4f6",
            "wait_fg": "#374151",
            "err_bg": "#fee2e2",
            "err_fg": "#b91c1c",
            "stop_bg": "#fef3c7",
            "stop_fg": "#92400e",
        }

    def _bind_shortcuts(self) -> None:
        """
        Rejestruje skróty klawiaturowe.
        """
        self.root.bind_class("Entry", "<Control-a>", self._select_all_in_entry)
        self.root.bind_class("TEntry", "<Control-a>", self._select_all_in_entry)
        self.root.bind_class("Entry", "<Control-A>", self._select_all_in_entry)
        self.root.bind_class("TEntry", "<Control-A>", self._select_all_in_entry)

    def _select_all_in_entry(self, event) -> str:
        """
        Zaznacza cały tekst w Entry.
        """
        widget = event.widget
        try:
            widget.selection_range(0, "end")
            widget.icursor("end")
        except Exception:
            return ""
        return "break"

    def _build_ui(self) -> None:
        """
        Buduje cały interfejs aplikacji.
        """
        outer = ttk.Frame(self.root, style="App.TFrame")
        outer.pack(fill="both", expand=True)

        self.main_canvas = tk.Canvas(outer, bg=self.colors["bg_main"], highlightthickness=0, bd=0)
        self.main_canvas.pack(side="left", fill="both", expand=True)

        v_scroll = ttk.Scrollbar(outer, orient="vertical", command=self.main_canvas.yview)
        v_scroll.pack(side="right", fill="y")
        self.main_canvas.configure(yscrollcommand=v_scroll.set)

        self.scrollable_frame = ttk.Frame(self.main_canvas, style="App.TFrame", padding=16)
        self.scrollable_window = self.main_canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")

        self.scrollable_frame.bind("<Configure>", self._on_scrollable_configure)
        self.main_canvas.bind("<Configure>", self._on_canvas_configure)
        self.main_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.main_canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.main_canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

        header = ttk.Frame(self.scrollable_frame, style="App.TFrame")
        header.pack(fill="x", pady=(0, 14))
        ttk.Label(header, text="yt-dlp GUI", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text="Prostszy widok podstawowy, reszta opcji schowana w „Zaawansowane”.", style="SubHeader.TLabel").pack(anchor="w", pady=(4, 0))

        settings_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=18)
        settings_card.pack(fill="x", pady=(0, 12))
        ttk.Label(settings_card, text="Ustawienia pobierania", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(settings_card, text="Najczęściej wystarczy wkleić link, wybrać folder i kliknąć pobieranie.", style="CardText.TLabel").pack(anchor="w", pady=(2, 14))

        form = ttk.Frame(settings_card, style="Card.TFrame")
        form.pack(fill="x")

        ttk.Label(form, text="Link do filmu / playlisty / folderu:", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        url_entry = ttk.Entry(form, textvariable=self.url_var)
        url_entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        url_entry.focus()

        self.add_link_top_btn = ttk.Button(form, text="Dodaj link", command=self.add_url_to_queue, style="Accent.TButton")
        self.add_link_top_btn.grid(row=2, column=0, sticky="w", pady=(0, 14))

        ttk.Label(form, text="Folder docelowy:", style="FieldLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(form, textvariable=self.output_dir_var).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        ttk.Button(form, text="Wybierz…", command=self.choose_output_dir).grid(row=4, column=2, sticky="ew", padx=(10, 0), pady=(0, 14))

        ttk.Label(form, text="Tryb pobierania:", style="FieldLabel.TLabel").grid(row=5, column=0, sticky="w", pady=(0, 6))
        mode_combo = ttk.Combobox(form, textvariable=self.mode_var, state="readonly", values=[
            "best_mp4_archive_style",
            "best_mp4",
            "best_any",
            "audio_mp3",
            "audio_m4a",
            "worst_test",
        ])
        mode_combo.grid(row=6, column=0, sticky="ew", pady=(0, 14))

        ttk.Label(form, text="Szablon nazwy pliku:", style="FieldLabel.TLabel").grid(row=5, column=1, sticky="w", pady=(0, 6))
        ttk.Entry(form, textvariable=self.filename_template_var).grid(row=6, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(0, 14))

        form.columnconfigure(0, weight=2)
        form.columnconfigure(1, weight=3)
        form.columnconfigure(2, weight=1)

        advanced_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=18)
        advanced_card.pack(fill="x", pady=(0, 12))

        self.advanced_toggle_button = ttk.Button(advanced_card, text="▶ Zaawansowane", command=self.toggle_advanced_panel, style="Toggle.TButton")
        self.advanced_toggle_button.pack(anchor="w")
        ttk.Label(advanced_card, text="Tutaj znajdziesz napisy, playlisty, miniatury, archive, retry i metadata.", style="CardText.TLabel").pack(anchor="w", pady=(6, 0))

        self.advanced_panel_frame = ttk.Frame(advanced_card, style="Card.TFrame")
        advanced_inner = ttk.Frame(self.advanced_panel_frame, style="Card.TFrame")
        advanced_inner.pack(fill="x", pady=(14, 0))

        options_frame = ttk.LabelFrame(advanced_inner, text="Opcje", style="Section.TLabelframe", padding=12)
        options_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        cb_subs = ttk.Checkbutton(options_frame, text="Pobierz napisy (jeśli są)", variable=self.subtitles_var, command=self.save_settings)
        cb_subs.grid(row=0, column=0, sticky="w", pady=4)
        ToolTip(cb_subs, "Dodaje pobieranie napisów i auto-napisów, a potem próbuje osadzić je w pliku.")

        cb_playlist = ttk.Checkbutton(options_frame, text="Traktuj URL jako playlistę / folder", variable=self.playlist_var, command=self.save_settings)
        cb_playlist.grid(row=1, column=0, sticky="w", pady=4)
        ToolTip(cb_playlist, "Pozwala potraktować URL jako listę wielu elementów. Wtedy działa też ograniczenie pozycji playlisty/folderu.")

        cb_thumb = ttk.Checkbutton(options_frame, text="Pobierz miniaturę", variable=self.write_thumbnail_var, command=self.save_settings)
        cb_thumb.grid(row=2, column=0, sticky="w", pady=4)
        ToolTip(cb_thumb, "Pobiera miniaturę udostępnioną przez serwis, jeśli extractor ją obsługuje.")

        ttk.Label(options_frame, text="Pozycje playlisty / folderu:", style="FieldLabel.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 6))
        entry_playlist_items = ttk.Entry(options_frame, textvariable=self.playlist_items_var)
        entry_playlist_items.grid(row=4, column=0, sticky="ew")
        ToolTip(entry_playlist_items, "Przykłady: 1-20 lub 1,3,5-10. Puste pole oznacza pobranie wszystkich pozycji.")
        ttk.Label(options_frame, text="np. 1-20 lub 1,3,5-10; puste pole = wszystko", style="Hint.TLabel").grid(row=5, column=0, sticky="w", pady=(8, 0))
        options_frame.columnconfigure(0, weight=1)

        archive_frame = ttk.LabelFrame(advanced_inner, text="Archiwum pobrań", style="Section.TLabelframe", padding=12)
        archive_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        cb_archive = ttk.Checkbutton(archive_frame, text="Włącz --download-archive", variable=self.use_archive_var, command=self.save_settings)
        cb_archive.grid(row=0, column=0, sticky="w", pady=(0, 8))
        ToolTip(cb_archive, "yt-dlp zapisuje identyfikatory już pobranych elementów do pliku archive.txt i przy kolejnych uruchomieniach pomija duplikaty.")

        ttk.Label(archive_frame, text="Plik archiwum:", style="FieldLabel.TLabel").grid(row=1, column=0, sticky="w", pady=(0, 6))
        entry_archive = ttk.Entry(archive_frame, textvariable=self.archive_file_var)
        entry_archive.grid(row=2, column=0, columnspan=2, sticky="ew")
        ToolTip(entry_archive, "Ścieżka do archive.txt. Najczęściej warto trzymać jeden plik archiwum dla danego folderu pobierania.")
        ttk.Button(archive_frame, text="Wybierz…", command=self.choose_archive_file).grid(row=2, column=2, sticky="ew", padx=(10, 0))
        ttk.Label(archive_frame, text="Najczęściej warto zostawić jeden archive.txt dla danego folderu pobierania.", style="Hint.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        archive_frame.columnconfigure(0, weight=3)
        archive_frame.columnconfigure(1, weight=1)
        archive_frame.columnconfigure(2, weight=1)

        retry_frame = ttk.LabelFrame(advanced_inner, text="Ponowienia", style="Section.TLabelframe", padding=12)
        retry_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        ttk.Label(retry_frame, text="Liczba ponowień (retries):", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        entry_retries = ttk.Entry(retry_frame, textvariable=self.retries_var)
        entry_retries.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ToolTip(entry_retries, "Ogólna liczba prób przy błędach pobierania. Puste pole = domyślne zachowanie yt-dlp.")

        ttk.Label(retry_frame, text="Liczba ponowień fragmentów (fragment-retries):", style="FieldLabel.TLabel").grid(row=0, column=1, sticky="w", padx=(14, 0), pady=(0, 6))
        entry_fragment_retries = ttk.Entry(retry_frame, textvariable=self.fragment_retries_var)
        entry_fragment_retries.grid(row=1, column=1, sticky="ew", padx=(14, 0), pady=(0, 10))
        ToolTip(entry_fragment_retries, "Przydatne przy HLS/DASH i niestabilnym połączeniu. Dotyczy fragmentów strumienia.")
        ttk.Label(retry_frame, text="Puste pola = nie dodawaj parametrów retry do komendy.", style="Hint.TLabel").grid(row=2, column=0, columnspan=2, sticky="w")
        retry_frame.columnconfigure(0, weight=1)
        retry_frame.columnconfigure(1, weight=1)

        metadata_frame = ttk.LabelFrame(advanced_inner, text="Metadata i pliki dodatkowe", style="Section.TLabelframe", padding=12)
        metadata_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        cb_info_json = ttk.Checkbutton(metadata_frame, text="Zapisz info JSON (.info.json)", variable=self.write_info_json_var, command=self.save_settings)
        cb_info_json.grid(row=0, column=0, sticky="w", pady=4)
        ToolTip(cb_info_json, "Zapisuje obok pliku dodatkowy plik .info.json zawierający metadane materiału: tytuł, opis, uploadera, id, tagi i inne pola.")

        cb_embed_meta = ttk.Checkbutton(metadata_frame, text="Osadź metadata w pliku", variable=self.embed_metadata_var, command=self.save_settings)
        cb_embed_meta.grid(row=1, column=0, sticky="w", pady=4)
        ToolTip(cb_embed_meta, "Próbuje wpisać metadane bezpośrednio do pobranego pliku multimedialnego.")

        cb_embed_chapters = ttk.Checkbutton(metadata_frame, text="Osadź chaptery / rozdziały", variable=self.embed_chapters_var, command=self.save_settings)
        cb_embed_chapters.grid(row=2, column=0, sticky="w", pady=4)
        ToolTip(cb_embed_chapters, "Przenosi chaptery / rozdziały do finalnego pliku, jeśli źródło je udostępnia.")

        sections_frame = ttk.LabelFrame(advanced_inner, text="Wycinanie fragmentu materiału", style="Section.TLabelframe", padding=12)
        sections_frame.grid(row=4, column=0, columnspan=2, sticky="ew")

        ttk.Label(sections_frame, text="Sekcja do pobrania (--download-sections):", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        entry_sections = ttk.Entry(sections_frame, textvariable=self.download_sections_var)
        entry_sections.grid(row=1, column=0, sticky="ew")
        ToolTip(entry_sections, "Przykład: *00:30-01:15. Wymaga ffmpeg. Pozwala pobrać tylko fragment materiału.")
        ttk.Label(sections_frame, text='Przykład: *00:30-01:15  → pobiera fragment od 00:30 do 01:15. Puste pole = bez wycinania.', style="Hint.TLabel").grid(row=2, column=0, sticky="w", pady=(8, 0))
        sections_frame.columnconfigure(0, weight=1)

        advanced_inner.columnconfigure(0, weight=1)
        advanced_inner.columnconfigure(1, weight=1)

        queue_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=18)
        queue_card.pack(fill="both", expand=True, pady=(0, 12))
        ttk.Label(queue_card, text="Kolejka linków", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(queue_card, text="Status pokazuje postęp całego wpisu. Dla playlist i folderów pojawi się licznik, np. pobieranie (3/20).", style="CardText.TLabel").pack(anchor="w", pady=(2, 12))

        queue_actions = ttk.Frame(queue_card, style="Card.TFrame")
        queue_actions.pack(fill="x", pady=(0, 10))
        ttk.Button(queue_actions, text="Dodaj wiele ze schowka", command=self.add_many_from_clipboard).pack(side="left")
        ttk.Button(queue_actions, text="Wklej do pola", command=self.paste_clipboard).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Usuń zaznaczone", command=self.remove_selected_queue_items).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Wyczyść kolejkę", command=self.clear_queue).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Reset statusów", command=self.reset_queue_statuses).pack(side="left", padx=(8, 0))

        queue_table_wrap = ttk.Frame(queue_card, style="Card.TFrame")
        queue_table_wrap.pack(fill="both", expand=True)

        self.queue_tree = ttk.Treeview(queue_table_wrap, columns=("status", "url"), show="headings", height=11)
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("url", text="URL")
        self.queue_tree.column("status", width=240, anchor="w", stretch=False)
        self.queue_tree.column("url", width=840, anchor="w", stretch=True)
        self.queue_tree.pack(side="left", fill="both", expand=True)

        queue_scroll_y = ttk.Scrollbar(queue_table_wrap, orient="vertical", command=self.queue_tree.yview)
        queue_scroll_y.pack(side="right", fill="y")
        self.queue_tree.configure(yscrollcommand=queue_scroll_y.set)

        self.queue_tree.tag_configure("waiting", background=self.colors["wait_bg"], foreground=self.colors["wait_fg"])
        self.queue_tree.tag_configure("running", background=self.colors["run_bg"], foreground=self.colors["run_fg"])
        self.queue_tree.tag_configure("done", background=self.colors["ok_bg"], foreground=self.colors["ok_fg"])
        self.queue_tree.tag_configure("error", background=self.colors["err_bg"], foreground=self.colors["err_fg"])
        self.queue_tree.tag_configure("stopped", background=self.colors["stop_bg"], foreground=self.colors["stop_fg"])

        actions_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=18)
        actions_card.pack(fill="x", pady=(0, 12))
        ttk.Label(actions_card, text="Sterowanie", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(actions_card, text="Bieżący procent pobierania jest pokazywany poniżej zamiast spamować log.", style="CardText.TLabel").pack(anchor="w", pady=(2, 12))

        actions_bar = ttk.Frame(actions_card, style="Card.TFrame")
        actions_bar.pack(fill="x")
        self.download_btn = ttk.Button(actions_bar, text="Pobierz bieżący link", command=self.start_single_download, style="Accent.TButton")
        self.download_btn.pack(side="left")
        self.start_queue_btn = ttk.Button(actions_bar, text="Start kolejki", command=self.start_queue_download, style="Accent.TButton")
        self.start_queue_btn.pack(side="left", padx=(8, 0))
        self.stop_btn = ttk.Button(actions_bar, text="Zatrzymaj", command=self.stop_download, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        ttk.Button(actions_bar, text="Wyczyść log", command=self.clear_log).pack(side="left", padx=(8, 0))
        ttk.Button(actions_bar, text="Ustaw archive.txt w folderze pobierania", command=self.sync_archive_to_output).pack(side="left", padx=(8, 0))
        ttk.Button(actions_bar, text="Zapisz ustawienia teraz", command=self.save_settings).pack(side="left", padx=(8, 0))
        ttk.Button(actions_bar, text="Sprawdź zależności", command=self.check_dependencies).pack(side="right")

        progress_wrap = ttk.Frame(actions_card, style="Card.TFrame")
        progress_wrap.pack(fill="x", pady=(14, 0))
        ttk.Label(progress_wrap, textvariable=self.progress_primary_var, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(progress_wrap, textvariable=self.progress_secondary_var, style="CardText.TLabel").pack(anchor="w", pady=(2, 8))
        self.download_progressbar = ttk.Progressbar(progress_wrap, variable=self.progress_percent_var, maximum=100.0, style="Download.Horizontal.TProgressbar")
        self.download_progressbar.pack(fill="x")

        log_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=18)
        log_card.pack(fill="both", expand=True)
        ttk.Label(log_card, text="Log", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(log_card, text="Pokazywane są tylko ważniejsze zdarzenia: start, nowe pliki, scalanie, konwersja audio, błędy i zakończenie.", style="CardText.TLabel").pack(anchor="w", pady=(2, 12))

        log_wrap = ttk.Frame(log_card, style="Card.TFrame")
        log_wrap.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_wrap,
            wrap="word",
            height=18,
            bd=0,
            highlightthickness=1,
            relief="solid",
            background="#fbfdff",
            foreground=self.colors["text"],
            insertbackground=self.colors["text"],
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            font=("Consolas", 10),
            padx=10,
            pady=10,
        )
        self.log_text.pack(side="left", fill="both", expand=True)
        log_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log_text.yview)
        log_scroll.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.output_dir_var.trace_add("write", self._on_setting_changed)
        self.filename_template_var.trace_add("write", self._on_setting_changed)
        self.mode_var.trace_add("write", self._on_setting_changed)
        self.playlist_items_var.trace_add("write", self._on_setting_changed)
        self.archive_file_var.trace_add("write", self._on_setting_changed)
        self.retries_var.trace_add("write", self._on_setting_changed)
        self.fragment_retries_var.trace_add("write", self._on_setting_changed)
        self.download_sections_var.trace_add("write", self._on_setting_changed)

    def toggle_advanced_panel(self) -> None:
        """
        Otwiera albo zamyka panel „Zaawansowane”.
        """
        is_expanded = self.advanced_expanded_var.get()
        if is_expanded:
            self.advanced_panel_frame.pack_forget()
            self.advanced_toggle_button.configure(text="▶ Zaawansowane")
            self.advanced_expanded_var.set(False)
        else:
            self.advanced_panel_frame.pack(fill="x", pady=(0, 0))
            self.advanced_toggle_button.configure(text="▼ Zaawansowane")
            self.advanced_expanded_var.set(True)

        self.root.after(50, self._on_scrollable_configure)
        self.save_settings()

    def _on_scrollable_configure(self, _event=None) -> None:
        """
        Aktualizuje obszar przewijania canvasa.
        """
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        """
        Dopasowuje szerokość kontenera do szerokości canvasa.
        """
        self.main_canvas.itemconfigure(self.scrollable_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        """
        Płynniejsze przewijanie dla MouseWheel.
        """
        self.mousewheel_accumulator += (-event.delta / 120.0)
        steps = int(self.mousewheel_accumulator)
        if steps != 0:
            self.main_canvas.yview_scroll(steps, "units")
            self.mousewheel_accumulator -= steps

    def _on_mousewheel_linux(self, event) -> None:
        """
        Obsługa Button-4 / Button-5 w części środowisk Linux.
        """
        if event.num == 4:
            self.main_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.main_canvas.yview_scroll(1, "units")

    def _on_setting_changed(self, *_args) -> None:
        """
        Zapisuje ustawienia po zmianie pól.
        """
        self.save_settings()

    def _set_progress_state(self, primary: str, secondary: str = "", percent: float = 0.0) -> None:
        """
        Ustawia stan paska postępu.
        """
        self.progress_primary_var.set(primary)
        self.progress_secondary_var.set(secondary)
        self.progress_percent_var.set(max(0.0, min(100.0, percent)))

    def _reset_progress_state(self) -> None:
        """
        Resetuje pasek postępu.
        """
        self._set_progress_state("Brak aktywnego pobierania", "", 0.0)

    def get_settings_dict(self) -> dict:
        """
        Zbiera ustawienia do słownika JSON.
        """
        return {
            "output_dir": self.output_dir_var.get().strip(),
            "filename_template": self.filename_template_var.get().strip(),
            "mode": self.mode_var.get(),
            "advanced_expanded": self.advanced_expanded_var.get(),
            "subtitles": self.subtitles_var.get(),
            "playlist": self.playlist_var.get(),
            "write_thumbnail": self.write_thumbnail_var.get(),
            "playlist_items": self.playlist_items_var.get().strip(),
            "use_archive": self.use_archive_var.get(),
            "archive_file": self.archive_file_var.get().strip(),
            "retries": self.retries_var.get().strip(),
            "fragment_retries": self.fragment_retries_var.get().strip(),
            "write_info_json": self.write_info_json_var.get(),
            "embed_metadata": self.embed_metadata_var.get(),
            "embed_chapters": self.embed_chapters_var.get(),
            "download_sections": self.download_sections_var.get().strip(),
        }

    def save_settings(self) -> None:
        """
        Zapisuje ustawienia do pliku JSON.
        """
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.get_settings_dict(), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self._append_log(f"Nie udało się zapisać ustawień JSON: {exc}")

    def load_settings(self) -> None:
        """
        Wczytuje ustawienia z JSON.
        """
        if not os.path.exists(self.settings_path):
            return
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)

            self.output_dir_var.set(settings.get("output_dir", self.output_dir_var.get()))
            self.filename_template_var.set(settings.get("filename_template", self.filename_template_var.get()))
            self.mode_var.set(settings.get("mode", self.mode_var.get()))
            self.advanced_expanded_var.set(settings.get("advanced_expanded", False))

            self.subtitles_var.set(settings.get("subtitles", False))
            self.playlist_var.set(settings.get("playlist", False))
            self.write_thumbnail_var.set(settings.get("write_thumbnail", False))
            self.playlist_items_var.set(settings.get("playlist_items", ""))

            self.use_archive_var.set(settings.get("use_archive", True))
            self.archive_file_var.set(settings.get("archive_file", self.archive_file_var.get()))

            self.retries_var.set(settings.get("retries", ""))
            self.fragment_retries_var.set(settings.get("fragment_retries", ""))
            self.write_info_json_var.set(settings.get("write_info_json", False))
            self.embed_metadata_var.set(settings.get("embed_metadata", False))
            self.embed_chapters_var.set(settings.get("embed_chapters", False))
            self.download_sections_var.set(settings.get("download_sections", ""))

            if self.advanced_expanded_var.get():
                self.toggle_advanced_panel()
        except Exception as exc:
            self._append_log(f"Nie udało się wczytać ustawień JSON: {exc}")

    def save_queue(self) -> None:
        """
        Zapisuje kolejkę do JSON.
        """
        try:
            with open(self.queue_path, "w", encoding="utf-8") as f:
                json.dump(self.queue_items, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self._append_log(f"Nie udało się zapisać kolejki JSON: {exc}")

    def load_queue(self) -> None:
        """
        Wczytuje kolejkę z JSON.
        """
        if not os.path.exists(self.queue_path):
            return
        try:
            with open(self.queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                normalized = []
                for item in data:
                    if isinstance(item, dict) and "url" in item:
                        normalized.append({
                            "url": item.get("url", ""),
                            "status": item.get("status", "oczekuje"),
                            "progress_current": int(item.get("progress_current", 0) or 0),
                            "progress_total": int(item.get("progress_total", 0) or 0),
                            "completed_items": int(item.get("completed_items", 0) or 0),
                            "skipped_items": int(item.get("skipped_items", 0) or 0),
                            "error_items": int(item.get("error_items", 0) or 0),
                        })
                self.queue_items = normalized
        except Exception as exc:
            self._append_log(f"Nie udało się wczytać kolejki JSON: {exc}")

    def _normalize_queue_item(self, url: str) -> dict:
        """
        Tworzy nowy wpis kolejki.
        """
        return {
            "url": url,
            "status": "oczekuje",
            "progress_current": 0,
            "progress_total": 0,
            "completed_items": 0,
            "skipped_items": 0,
            "error_items": 0,
        }

    def _render_status_text(self, item: dict) -> str:
        """
        Buduje tekst statusu widoczny w kolejce.
        """
        base_status = item.get("status", "oczekuje")
        progress_total = int(item.get("progress_total", 0) or 0)
        completed = int(item.get("completed_items", 0) or 0)
        skipped = int(item.get("skipped_items", 0) or 0)
        errors = int(item.get("error_items", 0) or 0)
        progress_current = int(item.get("progress_current", 0) or 0)

        if progress_total <= 0:
            return base_status

        if base_status == "pobieranie":
            parts = [f"{base_status} ({max(progress_current, completed + skipped + errors)}/{progress_total})"]
        else:
            done = min(progress_total, completed + skipped + errors)
            parts = [f"{base_status} ({done}/{progress_total})"]

        extras = []
        if skipped > 0:
            extras.append(f"pominięte: {skipped}")
        if errors > 0:
            extras.append(f"błędy: {errors}")
        if extras:
            parts.append(", ".join(extras))
        return " | ".join(parts)

    def _status_tag_for_item(self, item: dict) -> str:
        """
        Zwraca nazwę taga kolorystycznego dla statusu.
        """
        status = item.get("status", "oczekuje")
        if status == "pobieranie":
            return "running"
        if status == "gotowe":
            return "done"
        if status == "błąd":
            return "error"
        if status == "zatrzymane":
            return "stopped"
        return "waiting"

    def _refresh_queue_view(self) -> None:
        """
        Odtwarza widok tabeli kolejki.
        """
        for item_id in self.queue_tree.get_children():
            self.queue_tree.delete(item_id)
        for index, item in enumerate(self.queue_items):
            self.queue_tree.insert("", "end", iid=str(index), values=(self._render_status_text(item), item["url"]), tags=(self._status_tag_for_item(item),))

    def _set_queue_item_status(self, index: int, status: str) -> None:
        """
        Ustawia status elementu kolejki.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["status"] = status
            self._refresh_queue_view()
            self.save_queue()

    def _reset_queue_item_counters(self, index: int) -> None:
        """
        Zeruje liczniki postępu dla wpisu kolejki.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["progress_current"] = 0
            self.queue_items[index]["progress_total"] = 0
            self.queue_items[index]["completed_items"] = 0
            self.queue_items[index]["skipped_items"] = 0
            self.queue_items[index]["error_items"] = 0
            self._refresh_queue_view()
            self.save_queue()

    def _ensure_total_for_queue_item(self, index: int, total: int) -> None:
        """
        Ustawia całkowitą liczbę elementów wpisu, jeśli udało się ją odczytać z logu.
        """
        if 0 <= index < len(self.queue_items) and total > 0:
            current_total = int(self.queue_items[index].get("progress_total", 0) or 0)
            if total > current_total:
                self.queue_items[index]["progress_total"] = total
                self._refresh_queue_view()
                self.save_queue()

    def _mark_completed_for_queue_item(self, index: int) -> None:
        """
        Zwiększa licznik ukończonych elementów.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["completed_items"] += 1
            done = self.queue_items[index]["completed_items"] + self.queue_items[index]["skipped_items"] + self.queue_items[index]["error_items"]
            self.queue_items[index]["progress_current"] = max(self.queue_items[index]["progress_current"], done)
            self._refresh_queue_view()
            self.save_queue()

    def _mark_skipped_for_queue_item(self, index: int) -> None:
        """
        Zwiększa licznik pominiętych elementów.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["skipped_items"] += 1
            done = self.queue_items[index]["completed_items"] + self.queue_items[index]["skipped_items"] + self.queue_items[index]["error_items"]
            self.queue_items[index]["progress_current"] = max(self.queue_items[index]["progress_current"], done)
            self._refresh_queue_view()
            self.save_queue()

    def _mark_error_for_queue_item(self, index: int) -> None:
        """
        Zwiększa licznik błędów.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["error_items"] += 1
            done = self.queue_items[index]["completed_items"] + self.queue_items[index]["skipped_items"] + self.queue_items[index]["error_items"]
            self.queue_items[index]["progress_current"] = max(self.queue_items[index]["progress_current"], done)
            self._refresh_queue_view()
            self.save_queue()

    def choose_output_dir(self) -> None:
        """
        Otwiera wybór folderu docelowego.
        """
        directory = filedialog.askdirectory(initialdir=self.output_dir_var.get() or os.path.expanduser("~"))
        if directory:
            self.output_dir_var.set(directory)
            self.save_settings()

    def choose_archive_file(self) -> None:
        """
        Otwiera wybór pliku archive.txt.
        """
        path = filedialog.asksaveasfilename(title="Wybierz plik archiwum", initialfile="archive.txt", defaultextension=".txt", filetypes=[("Pliki tekstowe", "*.txt"), ("Wszystkie pliki", "*.*")])
        if path:
            self.archive_file_var.set(path)
            self.save_settings()

    def sync_archive_to_output(self) -> None:
        """
        Ustawia archive.txt w aktualnym folderze pobierania.
        """
        output_dir = self.output_dir_var.get().strip()
        if not output_dir:
            messagebox.showwarning("Brak folderu", "Najpierw wybierz folder docelowy.")
            return
        archive_path = os.path.join(output_dir, "archive.txt")
        self.archive_file_var.set(archive_path)
        self.save_settings()
        self._append_log(f"Ustawiono plik archiwum: {archive_path}")

    def paste_clipboard(self) -> None:
        """
        Wkleja tekst ze schowka do pola URL.
        """
        try:
            text = self.root.clipboard_get().strip()
            if text:
                self.url_var.set(text)
                self._append_log("Wklejono link ze schowka do pola URL.")
        except tk.TclError:
            messagebox.showwarning("Schowek", "Schowek jest pusty albo niedostępny.")

    def add_url_to_queue(self) -> None:
        """
        Dodaje pojedynczy URL do kolejki.
        """
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Brak linku", "Wklej link do pola URL.")
            return
        self.queue_items.append(self._normalize_queue_item(url))
        self._refresh_queue_view()
        self.save_queue()
        self._append_log(f"Dodano do kolejki: {url}")

    def add_many_from_clipboard(self) -> None:
        """
        Dodaje wiele URL-i ze schowka.
        """
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("Schowek", "Schowek jest pusty albo niedostępny.")
            return
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            messagebox.showwarning("Brak linków", "W schowku nie znaleziono niepustych linii.")
            return
        for line in lines:
            self.queue_items.append(self._normalize_queue_item(line))
        self._refresh_queue_view()
        self.save_queue()
        self._append_log(f"Dodano ze schowka {len(lines)} linków do kolejki.")

    def remove_selected_queue_items(self) -> None:
        """
        Usuwa zaznaczone wpisy z kolejki.
        """
        selected = self.queue_tree.selection()
        if not selected:
            return
        indexes = sorted((int(item_id) for item_id in selected), reverse=True)
        for index in indexes:
            url = self.queue_items[index]["url"]
            del self.queue_items[index]
            self._append_log(f"Usunięto z kolejki: {url}")
        self._refresh_queue_view()
        self.save_queue()

    def clear_queue(self) -> None:
        """
        Czyści kolejkę.
        """
        if not self.queue_items:
            return
        self.queue_items = []
        self._refresh_queue_view()
        self.save_queue()
        self._append_log("Wyczyszczono kolejkę.")

    def reset_queue_statuses(self) -> None:
        """
        Resetuje statusy i liczniki kolejki.
        """
        for item in self.queue_items:
            item["status"] = "oczekuje"
            item["progress_current"] = 0
            item["progress_total"] = 0
            item["completed_items"] = 0
            item["skipped_items"] = 0
            item["error_items"] = 0
        self._refresh_queue_view()
        self.save_queue()
        self._append_log("Zresetowano statusy kolejki.")

    def clear_log(self) -> None:
        """
        Czyści log.
        """
        self.log_text.delete("1.0", "end")

    def _append_log(self, text: str) -> None:
        """
        Dopisuje linię do logu.
        """
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def _poll_log_queue(self) -> None:
        """
        Odbiera wpisy logu z kolejki wątku roboczego.
        """
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            else:
                self._append_log(line)
        self.root.after(150, self._poll_log_queue)


    def check_dependencies(self) -> None:
        """
        Sprawdza obecność yt-dlp i ffmpeg.
        """
        yt_dlp_path = shutil.which("yt-dlp")
        ffmpeg_path = shutil.which("ffmpeg")

        self._append_log("=== Sprawdzanie zależności ===")
        if yt_dlp_path:
            self._append_log(f"OK: yt-dlp znaleziony: {yt_dlp_path}")
        else:
            self._append_log("BRAK: yt-dlp nie został znaleziony w PATH.")

        if ffmpeg_path:
            self._append_log(f"OK: ffmpeg znaleziony: {ffmpeg_path}")
        else:
            self._append_log("UWAGA: ffmpeg nie został znaleziony w PATH.")

        if not yt_dlp_path:
            messagebox.showerror("Brak yt-dlp", "Nie znaleziono polecenia yt-dlp w PATH.")

    def _safe_int_or_none(self, value: str):
        """
        Zamienia tekst na int albo None.

        Puste pole -> None
        Niepoprawna liczba -> ValueError
        """
        value = value.strip()
        if not value:
            return None
        try:
            parsed = int(value)
        except ValueError:
            raise ValueError(f"Nieprawidłowa liczba: {value}")
        if parsed < 0:
            raise ValueError(f"Liczba nie może być ujemna: {value}")
        return parsed

    def build_command_for_url(self, url: str):
        """
        Buduje komendę yt-dlp dla pojedynczego URL-a.
        """
        output_dir = self.output_dir_var.get().strip()
        filename_template = self.filename_template_var.get().strip()
        archive_file = self.archive_file_var.get().strip()
        mode = self.mode_var.get()

        playlist_items = self.playlist_items_var.get().strip()
        retries = self._safe_int_or_none(self.retries_var.get())
        fragment_retries = self._safe_int_or_none(self.fragment_retries_var.get())
        download_sections = self.download_sections_var.get().strip()

        if not url:
            raise ValueError("Brak URL do pobrania.")
        if not output_dir:
            raise ValueError("Wybierz folder docelowy.")
        if not filename_template:
            raise ValueError("Podaj szablon nazwy pliku.")

        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, filename_template)

        cmd = ["yt-dlp", "--newline", "-o", output_path]

        if not self.playlist_var.get():
            cmd.append("--no-playlist")
        if self.playlist_var.get() and playlist_items:
            cmd += ["--playlist-items", playlist_items]

        if self.use_archive_var.get():
            if not archive_file:
                raise ValueError("Archiwum jest włączone, ale nie wskazano pliku archive.txt.")
            archive_dir = os.path.dirname(archive_file)
            if archive_dir:
                os.makedirs(archive_dir, exist_ok=True)
            cmd += ["--download-archive", archive_file]

        if self.subtitles_var.get():
            cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "pl.*,en.*", "--embed-subs"]
        if self.write_thumbnail_var.get():
            cmd.append("--write-thumbnail")

        if retries is not None:
            cmd += ["--retries", str(retries)]
        if fragment_retries is not None:
            cmd += ["--fragment-retries", str(fragment_retries)]
        if self.write_info_json_var.get():
            cmd.append("--write-info-json")
        if self.embed_metadata_var.get():
            cmd.append("--embed-metadata")
        if self.embed_chapters_var.get():
            cmd.append("--embed-chapters")
        if download_sections:
            cmd += ["--download-sections", download_sections]

        if mode == "best_mp4_archive_style":
            cmd += ["-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"]
        elif mode == "best_mp4":
            cmd += ["-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b", "--merge-output-format", "mp4"]
        elif mode == "best_any":
            cmd += ["-f", "bv*+ba/b"]
        elif mode == "audio_mp3":
            cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
        elif mode == "audio_m4a":
            cmd += ["-x", "--audio-format", "m4a"]
        elif mode == "worst_test":
            cmd += ["-f", "worst"]
        else:
            raise ValueError("Nieznany tryb pobierania.")

        cmd.append(url)
        return cmd

    def start_single_download(self) -> None:
        """
        Uruchamia pobieranie bieżącego URL-a.
        """
        if self.process is not None or self.is_queue_running:
            messagebox.showinfo("Pobieranie", "Pobieranie już trwa.")
            return

        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Brak linku", "Wklej link do pola URL.")
            return

        try:
            cmd = self.build_command_for_url(url)
        except ValueError as exc:
            messagebox.showwarning("Błąd formularza", str(exc))
            return

        if shutil.which("yt-dlp") is None:
            messagebox.showerror("Brak yt-dlp", "Nie znaleziono polecenia yt-dlp w PATH.")
            return

        self.stop_requested = False
        self.current_queue_index = None
        self._set_running_state(True)
        self._set_progress_state("Przygotowanie pobierania…", url, 0.0)

        self._append_log("")
        self._append_log("=== START JEDNEGO POBRANIA ===")
        self._append_log(f"URL: {url}")
        self._append_log("Polecenie:")
        self._append_log(" ".join(f'"{part}"' if " " in part else part for part in cmd))
        self._append_log("")

        threading.Thread(target=self._run_single_download_worker, args=(cmd,), daemon=True).start()

    def start_queue_download(self) -> None:
        """
        Uruchamia pobieranie całej kolejki.
        """
        if self.process is not None or self.is_queue_running:
            messagebox.showinfo("Pobieranie", "Pobieranie już trwa.")
            return

        if not self.queue_items:
            messagebox.showwarning("Pusta kolejka", "Dodaj przynajmniej jeden link do kolejki.")
            return

        if shutil.which("yt-dlp") is None:
            messagebox.showerror("Brak yt-dlp", "Nie znaleziono polecenia yt-dlp w PATH.")
            return

        try:
            self.build_command_for_url(self.queue_items[0]["url"])
        except ValueError as exc:
            messagebox.showwarning("Błąd formularza", str(exc))
            return

        self.stop_requested = False
        self.is_queue_running = True
        self._set_running_state(True)
        self._set_progress_state("Start kolejki…", f"Liczba wpisów: {len(self.queue_items)}", 0.0)

        self._append_log("")
        self._append_log("=== START KOLEJKI ===")
        self._append_log(f"Liczba wpisów w kolejce: {len(self.queue_items)}")
        self._append_log("")

        threading.Thread(target=self._run_queue_download_worker, daemon=True).start()

    def _process_output_line_for_progress(self, line):
        """
        Analizuje linię logu yt-dlp.
        """
        if self.current_queue_index is not None:
            index = self.current_queue_index

            match_items = self.re_item_of_total.search(line)
            if match_items:
                current = int(match_items.group(1))
                total = int(match_items.group(2))
                self.root.after(0, lambda idx=index, tot=total: self._ensure_total_for_queue_item(idx, tot))
                if 0 <= index < len(self.queue_items):
                    self.queue_items[index]["progress_current"] = max(self.queue_items[index]["progress_current"], current)
                    self.root.after(0, self._refresh_queue_view)

            match_list = self.re_download_list.search(line)
            if match_list:
                selected = int(match_list.group(1))
                self.root.after(0, lambda idx=index, tot=selected: self._ensure_total_for_queue_item(idx, tot))
                return True

            if self.re_archive_skip.search(line):
                self.root.after(0, lambda idx=index: self._mark_skipped_for_queue_item(idx))
                self.root.after(0, lambda: self._set_progress_state(self.progress_primary_var.get() or "Pomijanie przez archive", "Element już był w archive — pominięto", self.progress_percent_var.get()))
                return True

            if self.re_error_line.search(line):
                self.root.after(0, lambda idx=index: self._mark_error_for_queue_item(idx))
                return True

            if "[download] Destination:" in line:
                title = line.split("Destination:", 1)[1].strip()
                self.root.after(0, lambda txt=title: self._set_progress_state("Pobieranie pliku", txt, 0.0))
                self.root.after(0, lambda idx=index: self._mark_completed_for_queue_item(idx))
                return True

            if "[Merger]" in line:
                self.root.after(0, lambda txt=line: self._set_progress_state("Scalanie plików", txt, 100.0))
                return True

            if "[ExtractAudio]" in line:
                self.root.after(0, lambda txt=line: self._set_progress_state("Konwersja audio", txt, 100.0))
                return True

        percent_match = self.re_percent.search(line)
        if percent_match:
            percent = float(percent_match.group(1))
            speed_match = self.re_speed.search(line)
            eta_match = self.re_eta.search(line)

            secondary_parts = [f"{percent:.1f}%"]
            if speed_match:
                secondary_parts.append(f"Prędkość: {speed_match.group(1)}")
            if eta_match:
                secondary_parts.append(f"ETA: {eta_match.group(1)}")

            primary = self.progress_primary_var.get()
            if not primary or primary == "Brak aktywnego pobierania":
                primary = "Pobieranie"

            self.root.after(0, lambda p=percent, pri=primary, sec=" | ".join(secondary_parts): self._set_progress_state(pri, sec, p))
            return False

        return True

    def _execute_process_and_stream_output(self, cmd):
        """
        Uruchamia proces yt-dlp i kieruje log:
        - ważne wpisy do logu
        - procenty na pasek postępu
        """
        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert self.process.stdout is not None
        for line in self.process.stdout:
            clean_line = line.rstrip()
            should_log = self._process_output_line_for_progress(clean_line)
            if should_log:
                self.log_queue.put(clean_line)
        return_code = self.process.wait()
        self.process = None
        return return_code

    def _run_single_download_worker(self, cmd):
        """
        Wątek roboczy dla jednego pobrania.
        """
        try:
            return_code = self._execute_process_and_stream_output(cmd)
            if return_code == 0:
                self.log_queue.put("")
                self.log_queue.put("=== ZAKOŃCZONO POMYŚLNIE ===")
            else:
                self.log_queue.put("")
                self.log_queue.put(f"=== ZAKOŃCZONO Z BŁĘDEM, kod: {return_code} ===")
        except Exception as exc:
            self.log_queue.put(f"Błąd uruchomienia: {exc}")
        finally:
            self.process = None
            self.current_queue_index = None
            self.root.after(0, self._reset_progress_state)
            self.root.after(0, lambda: self._set_running_state(False))

    def _run_queue_download_worker(self):
        """
        Wątek roboczy dla całej kolejki.
        """
        try:
            total = len(self.queue_items)
            for index, item in enumerate(self.queue_items):
                if self.stop_requested:
                    self.log_queue.put("Kolejka została zatrzymana przez użytkownika.")
                    break

                self.current_queue_index = index
                url = item["url"]

                self.root.after(0, lambda idx=index: self._select_queue_row(idx))
                self.root.after(0, lambda idx=index: self._reset_queue_item_counters(idx))
                self.root.after(0, lambda idx=index: self._set_queue_item_status(idx, "pobieranie"))
                self.root.after(0, lambda idx=index, tot=total, current_url=url: self._set_progress_state(f"Kolejka {idx + 1}/{tot}", current_url, 0.0))

                self.log_queue.put("")
                self.log_queue.put(f"--- KOLEJKA {index + 1}/{total} ---")
                self.log_queue.put(f"URL: {url}")

                try:
                    cmd = self.build_command_for_url(url)
                except ValueError as exc:
                    self.log_queue.put(f"Pominięto przez błąd ustawień: {exc}")
                    self.root.after(0, lambda idx=index: self._set_queue_item_status(idx, "błąd"))
                    continue

                self.log_queue.put("Polecenie:")
                self.log_queue.put(" ".join(f'"{part}"' if " " in part else part for part in cmd))
                self.log_queue.put("")

                return_code = self._execute_process_and_stream_output(cmd)

                if self.stop_requested:
                    self.root.after(0, lambda idx=index: self._set_queue_item_status(idx, "zatrzymane"))
                    self.log_queue.put("Przerwano bieżące pobieranie i zatrzymano kolejkę.")
                    break

                if return_code == 0:
                    self.root.after(0, lambda idx=index: self._set_queue_item_status(idx, "gotowe"))
                    self.log_queue.put(f"Pozycja {index + 1}/{total} zakończona.")
                else:
                    self.root.after(0, lambda idx=index: self._set_queue_item_status(idx, "błąd"))
                    self.log_queue.put(f"Pozycja {index + 1}/{total} zakończona z błędem, kod: {return_code}")

            if not self.stop_requested:
                self.log_queue.put("")
                self.log_queue.put("=== KONIEC KOLEJKI ===")
        except Exception as exc:
            self.log_queue.put(f"Błąd działania kolejki: {exc}")
        finally:
            self.process = None
            self.current_queue_index = None
            self.is_queue_running = False
            self.root.after(0, self._clear_queue_selection)
            self.root.after(0, self._reset_progress_state)
            self.root.after(0, lambda: self._set_running_state(False))
            self.root.after(0, self.save_queue)

    def _select_queue_row(self, index):
        """
        Zaznacza bieżący wiersz kolejki.
        """
        item_id = str(index)
        if self.queue_tree.exists(item_id):
            self.queue_tree.selection_set(item_id)
            self.queue_tree.focus(item_id)
            self.queue_tree.see(item_id)

    def _clear_queue_selection(self):
        """
        Czyści zaznaczenie w tabeli kolejki.
        """
        for item_id in self.queue_tree.selection():
            self.queue_tree.selection_remove(item_id)

    def _set_running_state(self, is_running):
        """
        Włącza lub wyłącza odpowiednie przyciski.
        """
        if is_running:
            self.download_btn.configure(state="disabled")
            self.start_queue_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
        else:
            self.download_btn.configure(state="normal")
            self.start_queue_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")

    def stop_download(self):
        """
        Zatrzymuje bieżące pobieranie.
        """
        self.stop_requested = True
        if self.process is None:
            self._append_log("Nie ma aktywnego procesu do zatrzymania.")
            return
        try:
            self.process.terminate()
            self._append_log("Wysłano sygnał zatrzymania procesu.")
        except Exception as exc:
            self._append_log(f"Nie udało się zatrzymać procesu: {exc}")

    def run(self):
        """
        Startuje pętlę główną tkinter.
        """
        self.root.mainloop()


def main():
    """
    Punkt wejścia programu.
    """
    root = tk.Tk()
    app = YtDlpGuiApp(root)
    app.run()


if __name__ == "__main__":
    main()
