"""Single-deck DJ console using Tkinter, PortAudio and USB CDC telemetry."""
import os
import math
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import sounddevice as sd
from serial.tools import list_ports

from audio_engine import AudioEngine
from protocol import SLIDER_INDICES, normalize
from serial_link import SerialLink

# A restrained palette keeps the controls readable in a dark booth.
BG = "#090d16"
PANEL = "#111a25"
PANEL_DEEP = "#0d1520"
LINE = "#253442"
TEXT = "#e6f0ed"
MUTED = "#83939b"
DIM = "#526a72"
MINT = "#4ce7ba"
GOLD = "#ffd45b"
RED = "#ff6d77"
FONT = "Segoe UI"
MONO = "Consolas"


def label(parent, text="", *, size=9, color=TEXT, bg=None, weight="normal", **kwargs):
    font = kwargs.pop("font", (FONT, size, weight))
    return tk.Label(parent, text=text, font=font, fg=color,
                    bg=bg or parent.cget("bg"), **kwargs)


def button(parent, text, command, *, accent=False, danger=False, **kwargs):
    fg = BG if accent else RED if danger else TEXT
    normal = MINT if accent else "#20202b" if danger else "#1b2a35"
    active = "#8af6d7" if accent else "#49303a" if danger else "#293e49"
    padx = kwargs.pop("padx", 13)
    pady = kwargs.pop("pady", 8)
    return tk.Button(parent, text=text, command=command, bg=normal, fg=fg,
                     activebackground=active, activeforeground=fg, relief="flat",
                     bd=0, highlightthickness=0, cursor="hand2",
                     font=(FONT, 9, "bold"), padx=padx, pady=pady, **kwargs)


class Fader(tk.Frame):
    """Canvas fader shares its DoubleVar with the audio and hardware inputs."""
    def __init__(self, parent, title, channel, variable, callback, index):
        super().__init__(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        self.variable = variable
        self.callback = callback
        self.index = index
        self.top = 18
        self.bottom = 128
        self.accent = GOLD if index < 2 else MINT
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill="x", padx=12, pady=(11, 2))
        label(head, title, size=10, weight="bold").pack(anchor="w")
        label(head, channel, size=8, color=MUTED, font=(MONO, 8)).pack(anchor="w", pady=(1, 0))
        self.canvas = tk.Canvas(self, bg=PANEL, width=90, height=146, highlightthickness=0,
                                cursor="hand2", takefocus=True)
        self.canvas.pack(fill="both", expand=True, padx=10)
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<Button-1>", self.move)
        self.canvas.bind("<B1-Motion>", self.move)
        self.canvas.bind("<Up>", lambda _: self.nudge(0.02))
        self.canvas.bind("<Down>", lambda _: self.nudge(-0.02))
        self.variable.trace_add("write", lambda *_: self.draw())
        self.readout = label(self, size=11, color=self.accent, weight="bold", anchor="center")
        self.readout.pack(fill="x", padx=8, pady=(0, 2))
        self.detail = label(self, size=8, color=MUTED, anchor="center")
        self.detail.pack(fill="x", pady=(0, 10))
        self.draw()

    def nudge(self, delta):
        self.variable.set(max(0.0, min(1.0, self.variable.get() + delta)))
        self.callback()
        return "break"

    def move(self, event):
        self.canvas.focus_set()
        self.variable.set(max(0.0, min(1.0, (self.bottom - event.y) / (self.bottom - self.top))))
        self.callback()

    def draw(self):
        if not hasattr(self, "canvas"):
            return
        c = self.canvas
        c.delete("all")
        width = max(c.winfo_width(), 90)
        center = width / 2
        value = max(0.0, min(1.0, self.variable.get()))
        y = self.bottom - value * (self.bottom - self.top)
        # Scales, illuminated track and the physical handle are independently drawn.
        for tick in range(11):
            ty = self.top + tick * (self.bottom - self.top) / 10
            thick = tick in (0, 5, 10)
            c.create_line(center - 31, ty, center - (23 if thick else 26), ty, fill="#49606b")
            c.create_line(center + (23 if thick else 26), ty, center + 31, ty, fill="#49606b")
        c.create_line(center, self.top, center, self.bottom, fill="#263a43", width=6, capstyle="round")
        c.create_line(center, self.bottom, center, y, fill=self.accent, width=4, capstyle="round")
        c.create_rectangle(center - 13, y - 8, center + 13, y + 8, fill="#d9e7e3", outline="#eafff8")
        c.create_line(center - 8, y, center + 8, y, fill="#536e70", width=2)
        if hasattr(self, "readout"):
            if self.index == 0:
                self.readout.config(text=f"{value * 100:04.1f}%")
                self.detail.config(text="OUTPUT LEVEL")
            elif self.index == 1:
                self.readout.config(text=f"{0.5 + value:.2f}x")
                self.detail.config(text="RATE MULTIPLIER")
            else:
                self.readout.config(text=f"{-12 + 18 * value:+.1f} dB")
                self.detail.config(text="EQ GAIN")


class SpeedSlider(tk.Canvas):
    """Keyboard-accessible target speed in milliradians per second."""
    def __init__(self, parent, variable):
        super().__init__(parent, bg=PANEL, height=35, highlightthickness=0,
                         cursor="hand2", takefocus=True)
        self.variable = variable
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Button-1>", self.move)
        self.bind("<B1-Motion>", self.move)
        self.bind("<Left>", lambda _: self.nudge(-100))
        self.bind("<Right>", lambda _: self.nudge(100))
        variable.trace_add("write", lambda *_: self.draw())

    def nudge(self, amount):
        self.variable.set(max(-10000, min(10000, self.variable.get() + amount)))
        return "break"

    def move(self, event):
        self.focus_set()
        width = max(self.winfo_width() - 24, 1)
        fraction = max(0.0, min(1.0, (event.x - 12) / width))
        self.variable.set(round((-10000 + 20000 * fraction) / 100) * 100)

    def draw(self):
        self.delete("all")
        width = max(self.winfo_width(), 40)
        x = 12 + (width - 24) * (self.variable.get() + 10000) / 20000
        self.create_line(12, 17, width - 12, 17, fill="#31454e", width=5, capstyle="round")
        self.create_line(width / 2, 9, width / 2, 25, fill="#78918c")
        self.create_oval(x - 7, 10, x + 7, 24, fill=GOLD, outline=GOLD)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PULSE / XIAO DJ Controller")
        self.geometry("1280x820")
        self.minsize(800, 540)
        self.configure(bg=BG)
        self.engine = AudioEngine()
        self.link = None
        self.wave = None
        self.recent_tracks = []
        self.cue_fraction = 0.0
        self.motor_angle = 0.0
        self.motor_rpm = 0.0
        self.motor_online = False
        self.last_telemetry = 0.0
        self.calibration = [(0, 3300000)] * 5  # per-channel measured voltage endpoints, µV
        self.slider_inverted = [True] * 5  # Change individual entries if wiring differs.
        self.output_ids = [None]
        self.hardware = tk.BooleanVar(value=True)
        self.jog_enabled = tk.BooleanVar(value=False)
        self.motor_text = tk.StringVar(value="Feedback offline · output not confirmed")
        self.status = tk.StringVar(value="USB DISCONNECTED")
        self.track = tk.StringVar(value="NO TRACK LOADED")
        self.values = [tk.DoubleVar(value=x) for x in self.engine.controls]
        self._make_styles()
        self._build_interface()
        self.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.after(30, self.update_loop)

    def _make_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Console.TCombobox", fieldbackground="#1b2a35", background="#1b2a35",
                        foreground=TEXT, arrowcolor=MINT, bordercolor=LINE,
                        lightcolor=LINE, darkcolor=LINE, padding=6)
        style.map("Console.TCombobox", fieldbackground=[("readonly", "#1b2a35")],
                  foreground=[("readonly", TEXT)], selectbackground=[("readonly", "#1b2a35")],
                  selectforeground=[("readonly", TEXT)])
        self.option_add("*TCombobox*Listbox.background", "#1b2a35")
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", "#31544e")

    def _check(self, parent, text, variable, command=None):
        return tk.Checkbutton(parent, text=text, variable=variable, command=command,
                              bg=parent.cget("bg"), fg=TEXT, activebackground=parent.cget("bg"),
                              activeforeground=TEXT, selectcolor="#223e3b", font=(FONT, 9),
                              highlightthickness=0, bd=0, anchor="w", cursor="hand2")

    def _build_interface(self):
        # Scrollbars keep all controls reachable on small or high-DPI displays.
        viewport = tk.Frame(self, bg=BG)
        viewport.pack(fill="both", expand=True)
        self.viewport = tk.Canvas(viewport, bg=BG, highlightthickness=0, bd=0)
        vertical = tk.Scrollbar(viewport, orient="vertical", command=self.viewport.yview,
                                bg="#263a43", troughcolor=BG, relief="flat", width=10)
        horizontal = tk.Scrollbar(viewport, orient="horizontal", command=self.viewport.xview,
                                  bg="#263a43", troughcolor=BG, relief="flat", width=10)
        self.viewport.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side="right", fill="y")
        horizontal.pack(side="bottom", fill="x")
        self.viewport.pack(side="left", fill="both", expand=True)
        self.shell = tk.Frame(self.viewport, bg=BG)
        self.shell_id = self.viewport.create_window((0, 0), window=self.shell, anchor="nw")
        self.viewport.bind("<Configure>", self._viewport_resize)
        self.shell.bind("<Configure>", self._viewport_bounds)
        self.bind_all("<MouseWheel>", self._scroll_wheel)

        header = tk.Frame(self.shell, bg=BG, height=66)
        header.pack(fill="x", padx=23, pady=(12, 0))
        header.pack_propagate(False)
        brand = tk.Frame(header, bg=BG); brand.pack(side="left", fill="y")
        label(brand, "PULSE", size=20, color=GOLD, weight="bold").pack(side="left")
        label(brand, "  /  XIAO DJ", size=11, color=TEXT, weight="bold").pack(side="left", pady=(7, 0))
        label(brand, "   SINGLE DECK CONSOLE", size=8, color=DIM, font=(MONO, 8)).pack(side="left", pady=(9, 0))
        self.header_status = label(header, textvariable=self.status, size=9, color=MUTED, font=(MONO, 9))
        self.header_status.pack(side="right", pady=(5, 0))
        tk.Frame(self.shell, bg=LINE, height=1).pack(fill="x", padx=23)

        body = tk.Frame(self.shell, bg=BG)
        body.pack(fill="both", expand=True, padx=23, pady=(14, 16))
        side_width = max(274, int(210 * float(self.tk.call("tk", "scaling"))))
        body.columnconfigure(0, weight=1, minsize=660)
        body.columnconfigure(1, minsize=side_width)
        body.rowconfigure(0, weight=1)
        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        right = tk.Frame(body, bg=BG, width=side_width)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_propagate(False)

        deck = tk.Frame(left, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        deck.pack(fill="both", expand=True)
        top = tk.Frame(deck, bg=PANEL); top.pack(fill="x", padx=18, pady=(13, 8))
        label(top, "DECK 01", size=9, color=GOLD, weight="bold", font=(MONO, 9, "bold")).pack(side="left")
        label(top, " /  AUDIO SOURCE", size=8, color=MUTED, font=(MONO, 8)).pack(side="left")
        self.play_badge = label(top, "STANDBY", size=8, color=MUTED, font=(MONO, 8, "bold"))
        self.play_badge.pack(side="right")
        info = tk.Frame(deck, bg=PANEL); info.pack(fill="x", padx=18, pady=(0, 3))
        info.columnconfigure(0, weight=1)
        self.track_label = label(info, textvariable=self.track, size=16, weight="bold", anchor="w")
        self.track_label.grid(row=0, column=0, sticky="ew")
        self.track_label.bind("<Configure>", self._track_wrap)
        self.time_label = label(info, "00:00", size=21, color=MINT, font=(MONO, 21, "bold"))
        self.time_label.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.subline = label(info, "LOAD AN AUDIO FILE TO BEGIN", size=8, color=MUTED, font=(MONO, 8), anchor="w")
        self.subline.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self.total_label = label(info, "/ 00:00", size=9, color=MUTED, font=(MONO, 9))
        self.total_label.grid(row=1, column=1, sticky="e")
        performance = tk.Frame(deck, bg=PANEL)
        performance.pack(fill="x", padx=18, pady=(6, 0))
        self.platter = tk.Canvas(performance, width=140, height=140, bg=PANEL_DEEP,
                                 highlightthickness=0)
        self.platter.pack(side="left", padx=(0, 12))
        facts = tk.Frame(performance, bg=PANEL)
        facts.pack(side="left", fill="both", expand=True)
        label(facts, "MOTOR / TRANSPORT", size=8, color=DIM, font=(MONO, 8)).pack(anchor="w")
        self.rpm_label = label(facts, "--.- RPM", size=21, color=MINT,
                               font=(MONO, 21, "bold"), anchor="w")
        self.rpm_label.pack(fill="x", pady=(4, 0))
        self.rate_label = label(facts, "PLAY RATE  1.00x", size=10, color=TEXT,
                                font=(MONO, 10), anchor="w")
        self.rate_label.pack(fill="x", pady=(4, 0))
        self.cue_label = label(facts, "CUE  00:00", size=9, color=GOLD,
                               font=(MONO, 9), anchor="w")
        self.cue_label.pack(fill="x", pady=(4, 0))
        meter_box = tk.Frame(performance, bg=PANEL)
        meter_box.pack(side="right", padx=(12, 0))
        label(meter_box, "MASTER", size=8, color=DIM, font=(MONO, 8)).pack(anchor="center")
        self.meter = tk.Canvas(meter_box, width=92, height=115, bg=PANEL_DEEP, highlightthickness=0)
        self.meter.pack()
        self.meter_status = label(meter_box, "L  /  R", size=8, color=MUTED, font=(MONO, 8))
        self.meter_status.pack()

        wave_head = tk.Frame(deck, bg=PANEL); wave_head.pack(fill="x", padx=18, pady=(12, 0))
        label(wave_head, "TRACK OVERVIEW", size=8, color=MUTED, font=(MONO, 8)).pack(side="left")
        self.remaining_label = label(wave_head, "REMAINING  --:--", size=8, color=MUTED, font=(MONO, 8))
        self.remaining_label.pack(side="right")
        self.canvas = tk.Canvas(deck, height=110, bg=PANEL_DEEP, highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True, padx=18, pady=(10, 4))
        self.canvas.bind("<Button-1>", self.seek)
        footer = tk.Frame(deck, bg=PANEL); footer.pack(fill="x", padx=18, pady=(6, 14))
        button(footer, "LOAD TRACK", self.load).pack(side="left")
        self.play_button = button(footer, "PLAY  >", self.play, accent=True)
        self.play_button.pack(side="left", padx=(7, 0))
        button(footer, "−5s", lambda: self.seek_relative(-5), padx=9).pack(side="left", padx=(7, 0))
        button(footer, "+5s", lambda: self.seek_relative(5), padx=9).pack(side="left", padx=(5, 0))
        button(footer, "SET CUE", self.set_cue, padx=9).pack(side="left", padx=(7, 0))
        button(footer, "GO CUE", self.go_cue, padx=9).pack(side="left", padx=(5, 0))

        strip_header = tk.Frame(left, bg=BG); strip_header.pack(fill="x", pady=(16, 7))
        label(strip_header, "MIXER CONTROLS", size=10, weight="bold").pack(side="left")
        label(strip_header, "05  /  ANALOG INPUTS", size=8, color=DIM, font=(MONO, 8)).pack(side="right")
        strips = tk.Frame(left, bg=BG); strips.pack(fill="both", expand=False)
        titles = ["VOLUME", "SPEED", "LOW EQ", "MID EQ", "HIGH EQ"]
        channels = ["M1 / A1", "M1 / A2", "M1 / A3", "M2 / A0", "M2 / A1"]
        self.faders = []
        for i, (name, channel) in enumerate(zip(titles, channels)):
            strips.columnconfigure(i, weight=1, uniform="channel")
            fader = Fader(strips, name, channel, self.values[i], self.manual_change, i)
            fader.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == 4 else 4))
            self.faders.append(fader)

        library = tk.Frame(left, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        library.pack(fill="x", pady=(16, 0))
        library_header = tk.Frame(library, bg=PANEL); library_header.pack(fill="x", padx=14, pady=(10, 3))
        label(library_header, "RECENT TRACKS", size=9, weight="bold").pack(side="left")
        label(library_header, "DOUBLE-CLICK TO LOAD", size=8, color=DIM, font=(MONO, 8)).pack(side="right")
        self.library_list = tk.Listbox(library, height=3, bg=PANEL_DEEP, fg=TEXT,
                                       selectbackground="#31544e", selectforeground=TEXT,
                                       relief="flat", borderwidth=0, font=(FONT, 9), activestyle="none")
        self.library_list.pack(fill="x", padx=14, pady=(0, 12))
        self.library_list.bind("<Double-Button-1>", self.load_recent)

        device = tk.Frame(right, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        device.pack(fill="x")
        top = tk.Frame(device, bg=PANEL); top.pack(fill="x", padx=14, pady=(14, 6))
        label(top, "DEVICE LINK", size=10, weight="bold").pack(side="left")
        label(top, "USB / CDC", size=8, color=MUTED, font=(MONO, 8)).pack(side="right")
        label(device, "SERIAL PORT", size=8, color=DIM, font=(MONO, 8)).pack(anchor="w", padx=14, pady=(5, 4))
        row = tk.Frame(device, bg=PANEL); row.pack(fill="x", padx=14)
        self.port = ttk.Combobox(row, width=10, values=self.ports(), style="Console.TCombobox")
        self.port.pack(side="left", fill="x", expand=True)
        button(row, "↻", self.refresh_ports, width=2, padx=5, pady=5).pack(side="left", padx=(6, 0))
        self.connect_button = button(device, "CONNECT DEVICE", self.connect)
        self.connect_button.pack(fill="x", padx=14, pady=(8, 7))
        self.device_status = label(device, textvariable=self.status, size=8, color=MUTED,
                                   font=(MONO, 8), anchor="w")
        self.device_status.pack(fill="x", padx=14, pady=(0, 6))
        self._check(device, "Use hardware sliders", self.hardware).pack(fill="x", padx=10, pady=(0, 10))

        audio = tk.Frame(right, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        audio.pack(fill="x", pady=(12, 0))
        label(audio, "AUDIO OUTPUT", size=10, weight="bold").pack(anchor="w", padx=14, pady=(12, 5))
        audio_row = tk.Frame(audio, bg=PANEL); audio_row.pack(fill="x", padx=14, pady=(0, 12))
        self.output = ttk.Combobox(audio_row, state="readonly", style="Console.TCombobox", width=12)
        self.output.pack(side="left", fill="x", expand=True)
        self.output.bind("<<ComboboxSelected>>", self.select_output)
        button(audio_row, "↻", self.refresh_outputs, width=2, padx=5, pady=5).pack(side="left", padx=(6, 0))
        self.refresh_outputs()

        motor = tk.Frame(right, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        motor.pack(fill="both", expand=True, pady=(12, 0))
        top = tk.Frame(motor, bg=PANEL); top.pack(fill="x", padx=14, pady=(14, 6))
        label(top, "MOTOR / FEEDBACK", size=10, weight="bold").pack(side="left")
        label(top, "CAN", size=8, color=MUTED, font=(MONO, 8)).pack(side="right")
        self.motor_status = label(motor, textvariable=self.motor_text, size=9, color=MUTED,
                                  anchor="w", justify="left", wraplength=238)
        self.motor_status.pack(fill="x", padx=14, pady=(0, 5))
        self._check(motor, "Scratch with motor", self.jog_enabled, self.reset_angle).pack(fill="x", padx=10)
        label(motor, "SPEED FADER ADJUSTS SCRATCH RATE", size=8, color=DIM,
              font=(MONO, 8)).pack(anchor="w", padx=14, pady=(0, 10))

    def _viewport_resize(self, event):
        self._viewport_bounds()

    def _viewport_bounds(self, _event=None):
        # Keep the two-column console usable, with horizontal scroll if necessary.
        width = max(self.viewport.winfo_width(), 1000, self.shell.winfo_reqwidth())
        height = max(self.viewport.winfo_height(), self.shell.winfo_reqheight())
        old_width = float(self.viewport.itemcget(self.shell_id, "width") or 0)
        old_height = float(self.viewport.itemcget(self.shell_id, "height") or 0)
        if width != old_width or height != old_height:
            self.viewport.itemconfigure(self.shell_id, width=width, height=height)
        self.viewport.configure(scrollregion=self.viewport.bbox("all"))

    def _scroll_wheel(self, event):
        # Shift + wheel scrolls horizontally when DPI makes the console wider.
        amount = -1 if event.delta > 0 else 1
        if event.state & 0x0001:
            self.viewport.xview_scroll(amount, "units")
        else:
            self.viewport.yview_scroll(amount, "units")

    def _track_wrap(self, event):
        self.track_label.configure(wraplength=max(120, event.width))

    @staticmethod
    def ports():
        return [p.device for p in list_ports.comports()]

    def refresh_ports(self):
        self.port["values"] = self.ports()

    def refresh_outputs(self):
        # PortAudio indices disambiguate devices with the same name / host API.
        devices = sd.query_devices()
        apis = sd.query_hostapis()
        self.output_ids = [None]
        labels = ["System default"]
        for index, info in enumerate(devices):
            if info["max_output_channels"] >= 2:
                self.output_ids.append(index)
                labels.append(f"{index}: {info['name']} ({apis[info['hostapi']]['name']})")
        self.output["values"] = labels
        selected = self.engine.output_device
        if selected in self.output_ids:
            self.output.current(self.output_ids.index(selected))
        else:
            self.output.set(f"Unavailable device {selected} — refresh or choose another")

    def select_output(self, _event=None):
        choice = self.output.current()
        if choice < 0 or choice >= len(self.output_ids):
            return
        try:
            self.engine.set_output_device(self.output_ids[choice])
        except Exception as exc:
            selected = self.engine.output_device
            if selected in self.output_ids:
                self.output.current(self.output_ids.index(selected))
            messagebox.showerror("Audio output", f"Could not open output: {exc}")

    def disconnect(self):
        link, self.link = self.link, None
        if link:
            link.close()
        self.motor_online = False
        self.last_telemetry = 0.0
        self.engine.set_scratch_velocity(0)
        self.motor_text.set("Feedback offline · serial disconnected")
        self.status.set("USB DISCONNECTED")
        self.connect_button.config(text="CONNECT DEVICE")

    def connect(self):
        if self.link and not self.link.stop_event.is_set():
            self.disconnect()
            return
        if self.link:
            self.disconnect()
        try:
            self.link = SerialLink(self.port.get().strip())
            self.status.set("USB CONNECTED / " + self.port.get())
            self.connect_button.config(text="DISCONNECT")
        except Exception as exc:
            self.status.set("USB DISCONNECTED")
            self.connect_button.config(text="CONNECT DEVICE")
            messagebox.showerror("Serial connection", str(exc))

    def load(self, path=None):
        path = path or filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.flac *.ogg"), ("All files", "*.*")])
        if not path:
            return
        try:
            data, rate = self.engine.load(path)
            self.engine.start_stream()
            self.track.set(os.path.basename(path))
            self.cue_fraction = 0.0
            if path in self.recent_tracks:
                self.recent_tracks.remove(path)
            self.recent_tracks.insert(0, path)
            self.recent_tracks = self.recent_tracks[:20]
            self.library_list.delete(0, tk.END)
            for track_path in self.recent_tracks:
                self.library_list.insert(tk.END, os.path.basename(track_path))
            self.subline.config(text=f"{rate:,} HZ  /  {data.shape[1]} CH  /  {os.path.splitext(path)[1][1:].upper()}")
            mono = np.max(np.abs(data), axis=1)
            self.wave = np.array([np.max(chunk) for chunk in np.array_split(mono, min(len(mono), 700))])
        except Exception as exc:
            messagebox.showerror("Audio", str(exc))

    def load_recent(self, _event=None):
        selection = self.library_list.curselection()
        if selection:
            self.load(self.recent_tracks[selection[0]])

    def play(self):
        self.engine.toggle()

    def seek_relative(self, seconds):
        position, length, rate, _ = self.engine.snapshot()
        if length:
            self.engine.seek_fraction((position + seconds * rate) / max(1, length - 1))

    def set_cue(self):
        position, length, _, _ = self.engine.snapshot()
        if length:
            self.cue_fraction = position / max(1, length - 1)

    def go_cue(self):
        self.engine.seek_fraction(self.cue_fraction)

    def manual_change(self, _=None):
        self.engine.set_controls([v.get() for v in self.values])

    def reset_angle(self):
        self.engine.set_scratch_enabled(self.jog_enabled.get())

    def seek(self, event):
        self.engine.seek_fraction(event.x / max(self.canvas.winfo_width(), 1))

    def handle_message(self, message):
        self.last_telemetry = time.monotonic()
        if self.hardware.get():
            for i, channel in enumerate(SLIDER_INDICES):
                value = normalize(message["adc_uv"][channel], *self.calibration[i], inverted=self.slider_inverted[i])
                if value is not None:
                    self.values[i].set(value)
            self.manual_change()
        motor = message["motor"]
        self.motor_online = bool(motor.get("online"))
        if self.motor_online:
            self.motor_rpm = float(motor.get("rpm10", 0)) / 10.0
            self.motor_angle = float(motor.get("angle_mrad", 0)) / 1000.0
        self.motor_text.set(f"{'ONLINE' if self.motor_online else 'OFFLINE'}  /  "
                            f"{'LOCAL ARM ON' if motor.get('armed') else 'LOCAL ARM OFF'}\n"
                            f"Feedback: {motor.get('rpm10', 0) / 10:.1f} rpm\nCAN error: {motor.get('error', 0)}")
        # Motor feedback drives the audio only when scratch mode is selected.
        if self.jog_enabled.get():
            self.engine.set_scratch_velocity(motor.get("rpm10", 0) if self.motor_online else 0)

    def update_loop(self):
        if self.link:
            if self.link.stop_event.is_set():
                self.connect_button.config(text="CONNECT DEVICE")
                self.status.set("USB DISCONNECTED")
                self.motor_online = False
                self.motor_text.set("Feedback offline · serial disconnected")
            else:
                try:
                    while True:
                        self.handle_message(self.link.messages.get_nowait())
                except queue.Empty:
                    pass
                except (TypeError, ValueError, KeyError):
                    self.status.set("INVALID TELEMETRY")
            if self.last_telemetry and time.monotonic() - self.last_telemetry > 1.0:
                self.motor_online = False
                self.motor_text.set("Feedback offline · telemetry stale")
        connected = self.link is not None and not self.link.stop_event.is_set()
        self.header_status.config(fg=MINT if connected else MUTED)
        self.device_status.config(fg=MINT if connected else MUTED)
        self.motor_status.config(fg=MINT if self.motor_online else MUTED)
        self.draw()
        self.after(30, self.update_loop)

    def draw(self):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 1), max(c.winfo_height(), 1)
        for i in range(1, 8):
            x = i * w / 8
            c.create_line(x, 0, x, h, fill="#1a2a36")
        c.create_line(0, h / 2, w, h / 2, fill="#304049")
        pos, total, rate, playing = self.engine.snapshot()
        if self.wave is not None:
            progress = pos / max(total, 1)
            for i, amplitude in enumerate(self.wave):
                x = i * w / max(len(self.wave) - 1, 1)
                height = min(1.0, float(amplitude)) * (h / 2 - 10)
                color = GOLD if x / w <= progress else "#766342"
                c.create_line(x, h / 2 - height, x, h / 2 + height, fill=color)
            cue_x = self.cue_fraction * w
            c.create_line(cue_x, 0, cue_x, h, fill="#4ce7ba", dash=(3, 3))
        else:
            c.create_text(w / 2, h / 2 - 7, text="NO WAVEFORM", fill="#49616a", font=(MONO, 10, "bold"))
            c.create_text(w / 2, h / 2 + 13, text="LOAD A TRACK TO GET STARTED", fill="#40535e", font=(MONO, 8))
        if total:
            c.create_line(pos / total * w, 0, pos / total * w, h, fill=MINT, width=2)
        def fmt(seconds):
            return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"
        self.time_label.config(text=fmt(pos / rate))
        self.total_label.config(text="/ " + fmt(total / rate))
        self.remaining_label.config(text="REMAINING  " + fmt(max(0, total - pos) / rate))
        self.cue_label.config(text="CUE  " + fmt(self.cue_fraction * max(0, total - 1) / rate))
        self.rpm_label.config(text=f"{self.motor_rpm:+.1f} RPM" if self.motor_online else "--.- RPM")
        peaks, clipped, underflows, play_rate = self.engine.visual_snapshot()
        self.rate_label.config(text=f"PLAY RATE  {play_rate:+.2f}x")
        self._draw_platter()
        self._draw_meter(peaks, clipped, underflows)
        self.play_badge.config(text="PLAYING" if playing else "PAUSED" if total else "STANDBY",
                               fg=MINT if playing else MUTED)
        self.play_button.config(text="PAUSE  ||" if playing else "PLAY  >")

    def _draw_platter(self):
        c = self.platter
        c.delete("all")
        cx = cy = 70
        for radius, color in ((63, "#263742"), (57, "#151e29"), (48, "#33434a"),
                              (39, "#151e29"), (24, "#223a3a")):
            c.create_oval(cx-radius, cy-radius, cx+radius, cy+radius, fill=color, outline="#41504e")
        angle = self.motor_angle if self.motor_online else 0.0
        x, y = cx + 47 * math.sin(angle), cy - 47 * math.cos(angle)
        c.create_line(cx, cy, x, y, fill=GOLD if self.motor_online else DIM, width=3)
        c.create_oval(cx-5, cy-5, cx+5, cy+5, fill=MINT, outline="")
        c.create_text(cx, 130, text="CAN ANGLE" if self.motor_online else "OFFLINE",
                      fill=MUTED, font=(MONO, 7))

    def _draw_meter(self, peaks, clipped, underflows):
        c = self.meter
        c.delete("all")
        for channel, peak in enumerate(peaks):
            db = 20.0 * math.log10(max(float(peak), 1e-5))
            segments = max(0, min(16, round((db + 48.0) / 48.0 * 16)))
            for i in range(16):
                x = 18 + channel * 30
                y = 96 - i * 5
                on = i < segments
                color = (RED if i >= 15 else GOLD if i >= 12 else MINT) if on else "#26363c"
                c.create_rectangle(x, y, x + 18, y + 3, fill=color, outline="")
        c.create_text(27, 108, text="L", fill=MUTED, font=(MONO, 7))
        c.create_text(57, 108, text="R", fill=MUTED, font=(MONO, 7))
        self.meter_status.config(text=f"{'CLIP' if clipped else 'OUTPUT'}  /  XRUN {underflows}",
                                 fg=RED if clipped or underflows else MUTED)

    def shutdown(self):
        if self.link:
            self.link.close()
        self.engine.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
