#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
yt-dlp GUI dla Linux Mint / Linux

Wersja rozszerzona:
- przewijalne całe okno aplikacji
- nowocześniejszy wygląd oparty o ttk
- zapis ustawień do JSON
- zapis kolejki do JSON
- statusy pozycji w kolejce
- statusy liczbowe dla wpisów wieloelementowych
- pobieranie wielu linków jeden po drugim
- obsługa --download-archive
- obsługa ograniczenia pozycji playlisty/folderu przez --playlist-items
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
        self.root = root
        self.root.title("yt-dlp GUI")
        self.root.geometry("1180x860")
        self.root.minsize(920, 620)

        # Pliki JSON w katalogu domowym użytkownika.
        self.settings_path = os.path.join(os.path.expanduser("~"), ".yt_dlp_gui_settings.json")
        self.queue_path = os.path.join(os.path.expanduser("~"), ".yt_dlp_gui_queue.json")

        # Kolejka logów z wątków roboczych do GUI.
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        # Bieżący proces yt-dlp.
        self.process: subprocess.Popen | None = None

        # Stan aplikacji.
        self.is_queue_running = False
        self.stop_requested = False

        # Dane kolejki przechowujemy jako listę słowników.
        self.queue_items: list[dict] = []

        # Informacje o aktualnie przetwarzanej pozycji kolejki.
        self.current_queue_index: int | None = None

        # Wzorce regex do analizy wyjścia yt-dlp.
        self.re_item_of_total = re.compile(r'item\s+(\d+)\s+of\s+(\d+)', re.IGNORECASE)
        self.re_download_list = re.compile(r'Downloading\s+(\d+)\s+items?\s+of\s+(\d+)', re.IGNORECASE)
        self.re_archive_skip = re.compile(r'has\s+already\s+been\s+recorded\s+in\s+the\s+archive', re.IGNORECASE)
        self.re_error_line = re.compile(r'^\s*ERROR:', re.IGNORECASE)

        # Pola formularza.
        self.url_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=os.path.expanduser("~/Pobrane"))
        self.filename_template_var = tk.StringVar(value="%(title)s [%(id)s].%(ext)s")
        self.subtitles_var = tk.BooleanVar(value=False)
        self.playlist_var = tk.BooleanVar(value=False)
        self.write_thumbnail_var = tk.BooleanVar(value=False)
        self.use_archive_var = tk.BooleanVar(value=True)
        self.archive_file_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~/Pobrane"), "archive.txt")
        )
        self.mode_var = tk.StringVar(value="best_mp4_archive_style")
        self.playlist_items_var = tk.StringVar(value="")

        self._configure_style()
        self._build_ui()
        self.load_settings()
        self.load_queue()
        self._refresh_queue_view()
        self._poll_log_queue()

        self._append_log("Uruchomiono GUI.")
        self._append_log("Ustawienia i kolejka zapisują się do JSON.")
        self._append_log("Całe okno ma pionowe przewijanie.")
        self._append_log("Dla playlist/folderów możesz wpisać zakres, np. 1-20 albo 1,3,5-10.")

    def _configure_style(self) -> None:
        """
        Ustawia styl ttk, żeby aplikacja wyglądała nowocześniej i czytelniej.
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
        accent = "#2563eb"

        self.root.configure(bg=bg_main)

        style.configure(".", font=("Segoe UI", 10))
        style.configure("App.TFrame", background=bg_main)
        style.configure("Card.TFrame", background=bg_card, relief="solid", borderwidth=1)
        style.configure("Header.TLabel", background=bg_main, foreground=text, font=("Segoe UI", 18, "bold"))
        style.configure("SubHeader.TLabel", background=bg_main, foreground=muted, font=("Segoe UI", 10))
        style.configure("Section.TLabelframe", background=bg_card, borderwidth=1, relief="solid")
        style.configure("Section.TLabelframe.Label", background=bg_card, foreground=text, font=("Segoe UI", 10, "bold"))
        style.configure("TLabel", background=bg_main, foreground=text)
        style.configure("FieldLabel.TLabel", background=bg_card, foreground=text, font=("Segoe UI", 10, "bold"))
        style.configure("Hint.TLabel", background=bg_card, foreground=muted, font=("Segoe UI", 9))
        style.configure("TButton", padding=(10, 7))
        style.map("TButton", foreground=[("active", text)])
        style.configure("Accent.TButton", padding=(10, 7), font=("Segoe UI", 10, "bold"))
        style.configure("TEntry", fieldbackground="#ffffff")
        style.configure("TCombobox", fieldbackground="#ffffff")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Vertical.TScrollbar", arrowsize=14)
        style.configure("Horizontal.TScrollbar", arrowsize=14)

        # Tło dla widgetów tk.Text/Listbox/Canvas ustawiamy ręcznie przy tworzeniu.
        self.colors = {
            "bg_main": bg_main,
            "bg_card": bg_card,
            "border": border,
            "text": text,
            "muted": muted,
            "accent": accent,
        }

    def _build_ui(self) -> None:
        """
        Buduje interfejs okna.

        Kluczowa zmiana:
        - całe okno jest umieszczone w przewijalnym Canvasie,
          więc na mniejszych ekranach nic nie ucieka poza dół.
        """
        # Główny kontener.
        outer = ttk.Frame(self.root, style="App.TFrame")
        outer.pack(fill="both", expand=True)

        # Canvas + scrollbar = przewijalne całe okno.
        self.main_canvas = tk.Canvas(
            outer,
            bg=self.colors["bg_main"],
            highlightthickness=0,
            bd=0,
        )
        self.main_canvas.pack(side="left", fill="both", expand=True)

        v_scroll = ttk.Scrollbar(outer, orient="vertical", command=self.main_canvas.yview)
        v_scroll.pack(side="right", fill="y")
        self.main_canvas.configure(yscrollcommand=v_scroll.set)

        # Wewnętrzna ramka, która będzie przewijana.
        self.scrollable_frame = ttk.Frame(self.main_canvas, style="App.TFrame", padding=16)
        self.scrollable_window = self.main_canvas.create_window(
            (0, 0),
            window=self.scrollable_frame,
            anchor="nw",
        )

        self.scrollable_frame.bind("<Configure>", self._on_scrollable_configure)
        self.main_canvas.bind("<Configure>", self._on_canvas_configure)

        # Obsługa scrolla kółkiem myszy.
        self.main_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.main_canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.main_canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

        # Nagłówek.
        header = ttk.Frame(self.scrollable_frame, style="App.TFrame")
        header.pack(fill="x", pady=(0, 14))

        ttk.Label(header, text="yt-dlp GUI", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Dodaj jeden lub wiele linków, ustaw opcje i pobierz wszystko po kolei.",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        # Karta ustawień.
        settings_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=16)
        settings_card.pack(fill="x", pady=(0, 12))

        form = ttk.Frame(settings_card, style="Card.TFrame")
        form.pack(fill="x")

        ttk.Label(form, text="Link do filmu / playlisty / folderu:", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        url_entry = ttk.Entry(form, textvariable=self.url_var)
        url_entry.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        url_entry.focus()

        ttk.Label(form, text="Folder docelowy:", style="FieldLabel.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 6)
        )
        output_entry = ttk.Entry(form, textvariable=self.output_dir_var)
        output_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Button(form, text="Wybierz…", command=self.choose_output_dir).grid(
            row=3, column=2, sticky="ew", padx=(10, 0), pady=(0, 12)
        )

        ttk.Label(form, text="Tryb pobierania:", style="FieldLabel.TLabel").grid(
            row=4, column=0, sticky="w", pady=(0, 6)
        )
        mode_combo = ttk.Combobox(
            form,
            textvariable=self.mode_var,
            state="readonly",
            values=[
                "best_mp4_archive_style",
                "best_mp4",
                "best_any",
                "audio_mp3",
                "audio_m4a",
                "worst_test",
            ],
        )
        mode_combo.grid(row=5, column=0, sticky="ew", pady=(0, 12))

        ttk.Label(form, text="Szablon nazwy pliku:", style="FieldLabel.TLabel").grid(
            row=4, column=1, sticky="w", pady=(0, 6)
        )
        ttk.Entry(form, textvariable=self.filename_template_var).grid(
            row=5, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=(0, 12)
        )

        ttk.Label(form, text="Pozycje playlisty / folderu:", style="FieldLabel.TLabel").grid(
            row=6, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Entry(form, textvariable=self.playlist_items_var).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(0, 4)
        )
        ttk.Label(
            form,
            text="np. 1-20 lub 1,3,5-10; puste pole = wszystko",
            style="Hint.TLabel",
        ).grid(row=7, column=2, sticky="w", padx=(10, 0), pady=(0, 4))

        form.columnconfigure(0, weight=2)
        form.columnconfigure(1, weight=3)
        form.columnconfigure(2, weight=1)

        options_frame = ttk.LabelFrame(settings_card, text="Opcje", style="Section.TLabelframe", padding=14)
        options_frame.pack(fill="x", pady=(6, 12))

        ttk.Checkbutton(
            options_frame,
            text="Pobierz napisy (jeśli są)",
            variable=self.subtitles_var,
            command=self.save_settings,
        ).grid(row=0, column=0, sticky="w", pady=4)

        ttk.Checkbutton(
            options_frame,
            text="Traktuj URL jako playlistę / folder",
            variable=self.playlist_var,
            command=self.save_settings,
        ).grid(row=0, column=1, sticky="w", padx=(20, 0), pady=4)

        ttk.Checkbutton(
            options_frame,
            text="Pobierz miniaturę",
            variable=self.write_thumbnail_var,
            command=self.save_settings,
        ).grid(row=0, column=2, sticky="w", padx=(20, 0), pady=4)

        archive_frame = ttk.LabelFrame(settings_card, text="Archiwum pobrań", style="Section.TLabelframe", padding=14)
        archive_frame.pack(fill="x")

        ttk.Checkbutton(
            archive_frame,
            text="Włącz --download-archive",
            variable=self.use_archive_var,
            command=self.save_settings,
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        ttk.Label(archive_frame, text="Plik archiwum:", style="FieldLabel.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 6)
        )
        ttk.Entry(archive_frame, textvariable=self.archive_file_var).grid(
            row=2, column=0, columnspan=2, sticky="ew"
        )
        ttk.Button(archive_frame, text="Wybierz…", command=self.choose_archive_file).grid(
            row=2, column=2, sticky="ew", padx=(10, 0)
        )

        ttk.Label(
            archive_frame,
            text="Archiwum zapisuje identyfikatory już pobranych elementów, więc kolejne uruchomienia pomijają duplikaty.",
            style="Hint.TLabel",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        archive_frame.columnconfigure(0, weight=3)
        archive_frame.columnconfigure(1, weight=1)
        archive_frame.columnconfigure(2, weight=1)

        # Karta kolejki.
        queue_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=16)
        queue_card.pack(fill="both", expand=True, pady=(0, 12))

        queue_header = ttk.Frame(queue_card, style="Card.TFrame")
        queue_header.pack(fill="x", pady=(0, 10))

        ttk.Label(queue_header, text="Kolejka linków", style="FieldLabel.TLabel").pack(side="left")
        ttk.Label(
            queue_header,
            text="Status pokazuje postęp całego wpisu; dla playlist/folderów pojawi się licznik, np. pobieranie (3/20).",
            style="Hint.TLabel",
        ).pack(side="right")

        queue_actions = ttk.Frame(queue_card, style="Card.TFrame")
        queue_actions.pack(fill="x", pady=(0, 10))

        ttk.Button(queue_actions, text="Dodaj link", command=self.add_url_to_queue, style="Accent.TButton").pack(side="left")
        ttk.Button(queue_actions, text="Dodaj wiele ze schowka", command=self.add_many_from_clipboard).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Wklej do pola", command=self.paste_clipboard).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Usuń zaznaczone", command=self.remove_selected_queue_items).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Wyczyść kolejkę", command=self.clear_queue).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Reset statusów", command=self.reset_queue_statuses).pack(side="left", padx=(8, 0))

        queue_table_wrap = ttk.Frame(queue_card, style="Card.TFrame")
        queue_table_wrap.pack(fill="both", expand=True)

        self.queue_tree = ttk.Treeview(
            queue_table_wrap,
            columns=("status", "url"),
            show="headings",
            height=11,
        )
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("url", text="URL")
        self.queue_tree.column("status", width=220, anchor="w", stretch=False)
        self.queue_tree.column("url", width=860, anchor="w", stretch=True)
        self.queue_tree.pack(side="left", fill="both", expand=True)

        queue_scroll_y = ttk.Scrollbar(queue_table_wrap, orient="vertical", command=self.queue_tree.yview)
        queue_scroll_y.pack(side="right", fill="y")
        self.queue_tree.configure(yscrollcommand=queue_scroll_y.set)

        # Karta akcji głównych.
        actions_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=16)
        actions_card.pack(fill="x", pady=(0, 12))

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

        # Karta logu.
        log_card = ttk.Frame(self.scrollable_frame, style="Card.TFrame", padding=16)
        log_card.pack(fill="both", expand=True)

        ttk.Label(log_card, text="Log", style="FieldLabel.TLabel").pack(anchor="w", pady=(0, 8))

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

        # Zapis ustawień po zmianie ważnych pól.
        self.output_dir_var.trace_add("write", self._on_setting_changed)
        self.filename_template_var.trace_add("write", self._on_setting_changed)
        self.archive_file_var.trace_add("write", self._on_setting_changed)
        self.mode_var.trace_add("write", self._on_setting_changed)
        self.playlist_items_var.trace_add("write", self._on_setting_changed)

    def _on_scrollable_configure(self, _event=None) -> None:
        """
        Aktualizuje obszar przewijania canvasa, gdy zmienia się rozmiar zawartości.
        """
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        """
        Dopasowuje szerokość wewnętrznej ramki do szerokości canvasa.
        Dzięki temu formularz zajmuje pełną szerokość i nie robi się wąski.
        """
        self.main_canvas.itemconfigure(self.scrollable_window, width=event.width)

    def _on_mousewheel(self, event) -> None:
        """
        Obsługa scrolla dla Windows / większości środowisk Linux z MouseWheel.
        """
        self.main_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux(self, event) -> None:
        """
        Obsługa scrolla dla części środowisk Linux korzystających z Button-4/Button-5.
        """
        if event.num == 4:
            self.main_canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            self.main_canvas.yview_scroll(3, "units")

    def _on_setting_changed(self, *_args) -> None:
        """
        Callback po zmianie ustawień formularza.
        """
        self.save_settings()

    def get_settings_dict(self) -> dict:
        """
        Zbiera aktualne ustawienia formularza do słownika.
        """
        return {
            "output_dir": self.output_dir_var.get().strip(),
            "filename_template": self.filename_template_var.get().strip(),
            "subtitles": self.subtitles_var.get(),
            "playlist": self.playlist_var.get(),
            "write_thumbnail": self.write_thumbnail_var.get(),
            "use_archive": self.use_archive_var.get(),
            "archive_file": self.archive_file_var.get().strip(),
            "mode": self.mode_var.get(),
            "playlist_items": self.playlist_items_var.get().strip(),
        }

    def save_settings(self) -> None:
        """
        Zapisuje ustawienia formularza do JSON.
        """
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(self.get_settings_dict(), f, ensure_ascii=False, indent=2)
        except Exception as exc:
            self._append_log(f"Nie udało się zapisać ustawień JSON: {exc}")

    def load_settings(self) -> None:
        """
        Wczytuje ustawienia z JSON, jeśli plik istnieje.
        """
        if not os.path.exists(self.settings_path):
            return

        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)

            self.output_dir_var.set(settings.get("output_dir", self.output_dir_var.get()))
            self.filename_template_var.set(settings.get("filename_template", self.filename_template_var.get()))
            self.subtitles_var.set(settings.get("subtitles", self.subtitles_var.get()))
            self.playlist_var.set(settings.get("playlist", self.playlist_var.get()))
            self.write_thumbnail_var.set(settings.get("write_thumbnail", self.write_thumbnail_var.get()))
            self.use_archive_var.set(settings.get("use_archive", self.use_archive_var.get()))
            self.archive_file_var.set(settings.get("archive_file", self.archive_file_var.get()))
            self.mode_var.set(settings.get("mode", self.mode_var.get()))
            self.playlist_items_var.set(settings.get("playlist_items", self.playlist_items_var.get()))
        except Exception as exc:
            self._append_log(f"Nie udało się wczytać ustawień JSON: {exc}")

    def save_queue(self) -> None:
        """
        Zapisuje aktualną kolejkę do JSON.
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
        Tworzy nowy wpis kolejki z pełnym zestawem pól.
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
        Buduje tekst statusu widoczny w tabeli kolejki.

        Przykłady:
        - oczekuje
        - pobieranie (3/20)
        - gotowe (20/20)
        - gotowe (18/20, pominięte: 2)
        - błąd (7/20, błędy: 1)
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

    def _refresh_queue_view(self) -> None:
        """
        Odtwarza widok tabeli kolejki na podstawie self.queue_items.
        """
        for item_id in self.queue_tree.get_children():
            self.queue_tree.delete(item_id)

        for index, item in enumerate(self.queue_items):
            self.queue_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(self._render_status_text(item), item["url"]),
            )

    def _set_queue_item_status(self, index: int, status: str) -> None:
        """
        Aktualizuje status elementu kolejki i odświeża widok + zapis.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["status"] = status
            self._refresh_queue_view()
            self.save_queue()

    def _reset_queue_item_counters(self, index: int) -> None:
        """
        Zeruje liczniki pozycji kolejki przed nowym przetwarzaniem.
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
        Ustawia całkowitą liczbę elementów dla playlisty/folderu, jeśli udało się ją odczytać z logu.
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
            done = (
                self.queue_items[index]["completed_items"]
                + self.queue_items[index]["skipped_items"]
                + self.queue_items[index]["error_items"]
            )
            self.queue_items[index]["progress_current"] = max(self.queue_items[index]["progress_current"], done)
            self._refresh_queue_view()
            self.save_queue()

    def _mark_skipped_for_queue_item(self, index: int) -> None:
        """
        Zwiększa licznik pominiętych elementów, np. przez archive.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["skipped_items"] += 1
            done = (
                self.queue_items[index]["completed_items"]
                + self.queue_items[index]["skipped_items"]
                + self.queue_items[index]["error_items"]
            )
            self.queue_items[index]["progress_current"] = max(self.queue_items[index]["progress_current"], done)
            self._refresh_queue_view()
            self.save_queue()

    def _mark_error_for_queue_item(self, index: int) -> None:
        """
        Zwiększa licznik błędów dla aktualnego wpisu.
        """
        if 0 <= index < len(self.queue_items):
            self.queue_items[index]["error_items"] += 1
            done = (
                self.queue_items[index]["completed_items"]
                + self.queue_items[index]["skipped_items"]
                + self.queue_items[index]["error_items"]
            )
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
        Pozwala wskazać plik archiwum.
        """
        path = filedialog.asksaveasfilename(
            title="Wybierz plik archiwum",
            initialfile="archive.txt",
            defaultextension=".txt",
            filetypes=[("Pliki tekstowe", "*.txt"), ("Wszystkie pliki", "*.*")],
        )
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
        Dodaje pojedynczy URL z pola do kolejki.
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
        Każda niepusta linia traktowana jest jako osobny wpis.
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
        Usuwa zaznaczone pozycje z kolejki.
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
        Czyści całą kolejkę.
        """
        if not self.queue_items:
            return

        self.queue_items = []
        self._refresh_queue_view()
        self.save_queue()
        self._append_log("Wyczyszczono kolejkę.")

    def reset_queue_statuses(self) -> None:
        """
        Ustawia wszystkim pozycjom status 'oczekuje' oraz zeruje liczniki.
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
        Dopisuje tekst do logu.
        """
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")

    def _poll_log_queue(self) -> None:
        """
        Odbiera logi z kolejki komunikatów od wątku roboczego.
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

    def build_command_for_url(self, url: str) -> list[str]:
        """
        Buduje komendę yt-dlp dla pojedynczego URL-a.

        Ważne:
        - jeżeli URL prowadzi do playlisty/folderu/kolekcji i zaznaczysz tryb playlisty,
          możesz ograniczyć pozycje przez --playlist-items
        - puste pole playlist_items oznacza: pobierz wszystko, co zwróci dany URL
        """
        output_dir = self.output_dir_var.get().strip()
        filename_template = self.filename_template_var.get().strip()
        archive_file = self.archive_file_var.get().strip()
        mode = self.mode_var.get()
        playlist_items = self.playlist_items_var.get().strip()

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
            cmd += [
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", "pl.*,en.*",
                "--embed-subs",
            ]

        if self.write_thumbnail_var.get():
            cmd.append("--write-thumbnail")

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
        Pobiera tylko URL z pola wejściowego.
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

        self._append_log("")
        self._append_log("=== START JEDNEGO POBRANIA ===")
        self._append_log(f"URL: {url}")
        self._append_log("Polecenie:")
        self._append_log(" ".join(f'"{part}"' if " " in part else part for part in cmd))
        self._append_log("")

        thread = threading.Thread(target=self._run_single_download_worker, args=(cmd,), daemon=True)
        thread.start()

    def start_queue_download(self) -> None:
        """
        Startuje pobieranie całej kolejki.
        Każda pozycja kolejki może sama w sobie być pojedynczym filmem
        albo playlistą/folderem zwracającym wiele elementów.
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

        self._append_log("")
        self._append_log("=== START KOLEJKI ===")
        self._append_log(f"Liczba wpisów w kolejce: {len(self.queue_items)}")
        self._append_log("")

        thread = threading.Thread(target=self._run_queue_download_worker, daemon=True)
        thread.start()

    def _run_single_download_worker(self, cmd: list[str]) -> None:
        """
        Wątek roboczy dla pojedynczego pobrania.
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
            self.root.after(0, lambda: self._set_running_state(False))

    def _run_queue_download_worker(self) -> None:
        """
        Wątek roboczy przetwarzający wpisy kolejki po kolei.

        Statusy:
        - oczekuje
        - pobieranie
        - gotowe
        - błąd
        - zatrzymane

        Dla wpisów wieloelementowych:
        - pobieranie (3/20)
        - gotowe (20/20)
        - gotowe (18/20 | pominięte: 2)
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

                item_snapshot = self.queue_items[index]
                if return_code == 0:
                    final_done = (
                        item_snapshot["completed_items"]
                        + item_snapshot["skipped_items"]
                        + item_snapshot["error_items"]
                    )
                    if item_snapshot["progress_total"] > 0 and final_done >= item_snapshot["progress_total"]:
                        self.root.after(0, lambda idx=index: self._set_queue_item_status(idx, "gotowe"))
                    elif item_snapshot["error_items"] > 0:
                        self.root.after(0, lambda idx=index: self._set_queue_item_status(idx, "błąd"))
                    else:
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
            self.root.after(0, lambda: self._set_running_state(False))
            self.root.after(0, self.save_queue)

    def _process_output_line_for_progress(self, line: str) -> None:
        """
        Analizuje pojedynczą linię wyjścia yt-dlp i aktualizuje liczniki
        dla bieżącej pozycji kolejki.

        Uwaga:
        logi różnych extractorów mogą się różnić, więc tu celowo używamy
        kilku prostych heurystyk zamiast jednej sztywnej reguły.
        """
        if self.current_queue_index is None:
            return

        index = self.current_queue_index

        match_items = self.re_item_of_total.search(line)
        if match_items:
            current = int(match_items.group(1))
            total = int(match_items.group(2))
            self.root.after(0, lambda idx=index, tot=total: self._ensure_total_for_queue_item(idx, tot))
            if 0 <= index < len(self.queue_items):
                self.queue_items[index]["progress_current"] = max(
                    self.queue_items[index]["progress_current"],
                    current,
                )
                self.root.after(0, self._refresh_queue_view)
            return

        match_list = self.re_download_list.search(line)
        if match_list:
            selected = int(match_list.group(1))
            total = int(match_list.group(2))
            # Dla naszego GUI ważniejsza jest realnie pobierana liczba pozycji.
            self.root.after(0, lambda idx=index, tot=selected: self._ensure_total_for_queue_item(idx, tot))
            return

        if self.re_archive_skip.search(line):
            self.root.after(0, lambda idx=index: self._mark_skipped_for_queue_item(idx))
            return

        if "[download] Destination:" in line or "[Merger]" in line or "[ExtractAudio]" in line:
            self.root.after(0, lambda idx=index: self._mark_completed_for_queue_item(idx))
            return

        if self.re_error_line.search(line):
            self.root.after(0, lambda idx=index: self._mark_error_for_queue_item(idx))
            return

    def _execute_process_and_stream_output(self, cmd: list[str]) -> int:
        """
        Uruchamia proces yt-dlp, przesyła stdout do logu
        i analizuje postęp dla bieżącej pozycji kolejki.
        """
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert self.process.stdout is not None

        for line in self.process.stdout:
            clean_line = line.rstrip()
            self.log_queue.put(clean_line)
            self._process_output_line_for_progress(clean_line)

        return_code = self.process.wait()
        self.process = None
        return return_code

    def _select_queue_row(self, index: int) -> None:
        """
        Podświetla aktualnie przetwarzany wiersz kolejki.
        """
        item_id = str(index)
        if self.queue_tree.exists(item_id):
            self.queue_tree.selection_set(item_id)
            self.queue_tree.focus(item_id)
            self.queue_tree.see(item_id)

    def _clear_queue_selection(self) -> None:
        """
        Czyści zaznaczenie w tabeli kolejki.
        """
        for item_id in self.queue_tree.selection():
            self.queue_tree.selection_remove(item_id)

    def _set_running_state(self, is_running: bool) -> None:
        """
        Ustawia stan przycisków zależnie od tego, czy trwa pobieranie.
        """
        if is_running:
            self.download_btn.configure(state="disabled")
            self.start_queue_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
        else:
            self.download_btn.configure(state="normal")
            self.start_queue_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")

    def stop_download(self) -> None:
        """
        Zatrzymuje bieżący proces.
        Jeśli trwa kolejka, ustawia także flagę zatrzymania kolejki.
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

    def run(self) -> None:
        """
        Start głównej pętli tkinter.
        """
        self.root.mainloop()


def main() -> None:
    """
    Punkt wejścia programu.
    """
    root = tk.Tk()
    app = YtDlpGuiApp(root)
    app.run()


if __name__ == "__main__":
    main()
