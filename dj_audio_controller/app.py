"""Two-deck DJ console. Motor safety runs outside the GUI render loop."""
import os
import sys
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
import sounddevice as sd
from serial.tools import list_ports
from audio_engine import AudioEngine
from controls import MotorController, Pickup
from protocol import normalize
from serial_link import SerialLink
from settings import SLIDER_INDICES, SLIDER_INVERTED, SLIDER_CALIBRATION_UV
from widgets import BG, PANEL, CARD, TRACK, TEXT, MUTED, DIM, MINT, GOLD, RED, BLUE, FaderCanvas, Waveform, Record, LevelMeter, LiveWaveform

FONT = 'Segoe UI'
MONO = 'Consolas'

def audio_device_label(name):
    # Keep the real device index; translate common Windows labels for display.
    for native, english in (('耳机', 'Headphones'), ('扬声器', 'Speakers'),
                            ('主声音驱动程序', 'Primary Sound Driver'),
                            ('声音映射器', 'Audio Mapper'), ('输出', 'Output')):
        name = name.replace(native, english)
    return name

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('PULSE / XIAO DUAL DECK')
        self.geometry('1440x900'); self.minsize(900, 620); self.configure(bg=BG)
        self.engine = AudioEngine(); self.link = None
        self.motor = MotorController(self._send)
        self.selected = tk.IntVar(value=0); self.mode = tk.StringVar(value='VINYL'); self.previous_mode = 'VINYL'
        self.hardware = tk.BooleanVar(value=True); self.drive = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='USB DISCONNECTED'); self.motor_status = tk.StringVar(value='Waiting for motor feedback')
        self.drive_status = tk.StringVar(value='Motor drive disabled')
        self.faders = [tk.DoubleVar(value=v) for v in (0.7,0.7,0.5,0.5,0.5)]
        self.pickup_tempo, self.pickup_filter = Pickup(), Pickup()
        self.tracks = ['NO TRACK LOADED','NO TRACK LOADED']; self.motor_rpm = 0.0; self.motor_online = False
        self.last_hardware = [None] * 5; self.outputs = [None]
        self._styles(); self._build(); self.protocol('WM_DELETE_WINDOW', self.shutdown)
        self.after(40, self.update_loop)
        # Start maximized within the Windows work area; users can restore/resize.
        if sys.platform == 'win32': self.after_idle(self._fit_initial_window)

    def _fit_initial_window(self):
        try: self.state('zoomed')
        except tk.TclError: pass

    def _styles(self):
        style = ttk.Style(self); style.theme_use('clam')
        style.configure('Pulse.TCombobox',fieldbackground='#243242',background='#243242',foreground=TEXT,
                        arrowcolor=MINT,bordercolor='#314456',padding=6)
        style.map('Pulse.TCombobox',fieldbackground=[('readonly','#243242')],foreground=[('readonly',TEXT)])
        self.option_add('*TCombobox*Listbox.background','#243242'); self.option_add('*TCombobox*Listbox.foreground',TEXT)

    def label(self, parent, text='', **kw):
        kw.setdefault('bg', parent.cget('bg')); kw.setdefault('fg', TEXT); kw.setdefault('font', (FONT, 9))
        return tk.Label(parent, text=text, **kw)

    def button(self, parent, text, command, accent=False):
        bg = MINT if accent else '#27384a'; fg = '#0b1820' if accent else TEXT
        return tk.Button(parent,text=text,command=command,bg=bg,fg=fg,activebackground='#6aa991',
                         activeforeground='#10191b',relief='flat',bd=0,padx=11,pady=7,cursor='hand2',
                         font=(FONT,9,'bold'))

    def panel(self, parent):
        return tk.Frame(parent,bg=PANEL,highlightbackground='#293b4a',highlightthickness=1)

    def _build(self):
        vp=tk.Frame(self,bg=BG); vp.pack(fill='both',expand=True)
        self.viewport=tk.Canvas(vp,bg=BG,highlightthickness=0)
        vertical=tk.Scrollbar(vp,orient='vertical',command=self.viewport.yview)
        horizontal=tk.Scrollbar(vp,orient='horizontal',command=self.viewport.xview)
        vertical.pack(side='right',fill='y'); horizontal.pack(side='bottom',fill='x')
        self.viewport.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set); self.viewport.pack(fill='both',expand=True)
        self.container=tk.Frame(self.viewport,bg=BG); self.win=self.viewport.create_window((0,0),window=self.container,anchor='nw')
        # Coalesce geometry changes to avoid configure/redraw storms on maximize.
        self._layout_pending = False
        self.container.bind('<Configure>', self._schedule_layout)
        self.viewport.bind('<Configure>', self._schedule_layout)
        self.bind_all('<MouseWheel>',self._wheel)

        head=tk.Frame(self.container,bg=BG); head.pack(fill='x',padx=24,pady=(10,8))
        brand=tk.Frame(head,bg=BG); brand.pack(side='left')
        self.label(brand,'PULSE',fg=GOLD,font=('Segoe UI',21,'bold')).pack(side='left')
        self.label(brand,'  /  XIAO DJ',fg=TEXT,font=('Segoe UI',12,'bold')).pack(side='left',pady=(6,0))
        self.label(brand,'   DUAL DECK STUDIO',fg=DIM,font=(MONO,9)).pack(side='left',pady=(7,0))
        self.label(head,textvariable=self.status,fg=MINT,font=(FONT,10,'bold')).pack(side='right')

        decks=tk.Frame(self.container,bg=BG); decks.pack(fill='x',padx=24)
        self.deck_labels=[]; self.deck_times=[]; self.deck_bpm=[]; self.canvases=[]; self.play_buttons=[]; self.records=[]; self.deck_tags=[]; self.deck_meters=[]
        for i,color in enumerate((GOLD,MINT)):
            decks.columnconfigure(i,weight=1,uniform='deck')
            box=self.panel(decks); box.grid(row=0,column=i,sticky='nsew',padx=(0 if i==0 else 7,7 if i==0 else 0))
            top=tk.Frame(box,bg=PANEL); top.pack(fill='x',padx=16,pady=(8,3))
            self.label(top,'DECK  '+('A' if i==0 else 'B'),fg=color,font=(MONO,11,'bold')).pack(side='left')
            tag=self.label(top,'',fg=MINT,font=(FONT,8,'bold')); tag.pack(side='right'); self.deck_tags.append(tag)
            body=tk.Frame(box,bg=PANEL); body.pack(fill='x',padx=16)
            record=Record(body,color); record.pack(side='left',padx=(0,14)); self.records.append(record)
            info=tk.Frame(body,bg=PANEL); info.pack(side='left',fill='both',expand=True)
            lab=self.label(info,'NO TRACK LOADED',fg=TEXT,font=(FONT,13,'bold'),anchor='w',wraplength=330,justify='left')
            lab.pack(fill='x',pady=(3,2)); self.deck_labels.append(lab)
            tim=self.label(info,'00:00  /  00:00',fg=color,font=(MONO,16,'bold'),anchor='w'); tim.pack(fill='x'); self.deck_times.append(tim)
            self.label(info,'CHANNEL LEVEL',fg=MUTED,font=(FONT,8),anchor='w').pack(fill='x',pady=(4,0))
            meter=LevelMeter(info); meter.pack(fill='x',pady=(1,2)); self.deck_meters.append(meter)
            self.label(info,'CLICK WAVEFORM TO SEEK / ENTER BPM',fg=MUTED,font=(FONT,8),anchor='w').pack(fill='x',pady=(4,0))
            wave=Waveform(box,color,lambda fraction,n=i:self.engine.seek_fraction(n,fraction)); wave.pack(fill='x',padx=16,pady=(5,3)); self.canvases.append(wave)
            row=tk.Frame(box,bg=PANEL); row.pack(fill='x',padx=16,pady=(2,8))
            self.button(row,'LOAD',lambda n=i:self.load(n)).pack(side='left')
            play=self.button(row,'PLAY',lambda n=i:self.engine.toggle(n),accent=True); play.pack(side='left',padx=5); self.play_buttons.append(play)
            self.button(row,'SET CUE',lambda n=i:self.engine.set_cue(n)).pack(side='left')
            self.button(row,'GO CUE',lambda n=i:self.engine.go_cue(n)).pack(side='left',padx=5)
            self.label(row,'BPM',fg=MUTED,font=(MONO,9)).pack(side='left',padx=(7,3))
            entry=tk.Entry(row,width=5,bg='#243242',fg=TEXT,insertbackground=TEXT,relief='flat',font=(MONO,10))
            entry.pack(side='left'); entry.bind('<Return>',lambda e,n=i:self.set_bpm(n)); self.deck_bpm.append(entry)
            tk.Radiobutton(row,text='SELECT DECK',variable=self.selected,value=i,command=self.select_deck,bg=PANEL,fg=color,
                           selectcolor='#253c3a',activebackground=PANEL,activeforeground=TEXT,font=(FONT,8),
                           highlightthickness=0).pack(side='right')

        main=tk.Frame(self.container,bg=BG); main.pack(fill='both',expand=True,padx=24,pady=8)
        # Reserve the device column before allocating the flexible mixer width.
        right=tk.Frame(main,bg=BG,width=310); right.pack(side='right',fill='y'); right.pack_propagate(False)
        left=tk.Frame(main,bg=BG); left.pack(side='left',fill='both',expand=True,padx=(0,14))
        mixer=self.panel(left); mixer.pack(fill='both',expand=True)
        bar=tk.Frame(mixer,bg=PANEL); bar.pack(fill='x',padx=16,pady=(8,2))
        self.label(bar,'MIXER',fg=TEXT,font=(MONO,11,'bold')).pack(side='left')
        self.label(bar,'  /  5 CHANNELS',fg=MUTED,font=(FONT,9)).pack(side='left')
        self.pickup_label=self.label(bar,'',fg=MINT,font=(FONT,8)); self.pickup_label.pack(side='right')
        # Keep visualization and physical controls alongside one another, rather
        # than stacking tall panels beyond the bottom of a typical display.
        mix_columns=tk.Frame(mixer,bg=PANEL); mix_columns.pack(fill='both',expand=True,padx=12,pady=(2,10))
        mix_columns.rowconfigure(0,weight=1)
        mix_columns.columnconfigure(0,weight=1,minsize=235)
        mix_columns.columnconfigure(1,weight=2,minsize=440)
        master=tk.Frame(mix_columns,bg=CARD); master.grid(row=0,column=0,sticky='nsew',padx=(4,6))
        controls=tk.Frame(mix_columns,bg=PANEL); controls.grid(row=0,column=1,sticky='nsew')
        master_top=tk.Frame(master,bg=CARD); master_top.pack(fill='x',padx=10,pady=(7,2))
        self.label(master_top,'MASTER OUTPUT',fg=TEXT,font=(FONT,9,'bold')).pack(side='left')
        self.master_clip=self.label(master_top,'',fg=RED,font=(MONO,9,'bold')); self.master_clip.pack(side='right')
        self.master_meters=[]
        for name in ('L','R'):
            meter_row=tk.Frame(master,bg=CARD); meter_row.pack(fill='x',padx=10,pady=(0,4))
            self.label(meter_row,name,fg=MUTED,font=(MONO,8),width=2).pack(side='left')
            meter=LevelMeter(meter_row); meter.pack(side='left',fill='x',expand=True); self.master_meters.append(meter)
        scale=tk.Frame(master,bg=CARD); scale.pack(fill='x',padx=10,pady=(0,5))
        self.label(scale,'-48 dBFS',fg=DIM,font=(MONO,8)).pack(side='left')
        self.label(scale,'0 dBFS',fg=DIM,font=(MONO,8)).pack(side='right')
        waveform_header=tk.Frame(master,bg=CARD); waveform_header.pack(fill='x',padx=10,pady=(3,2))
        self.label(waveform_header,'LIVE WAVEFORM',fg=TEXT,font=(FONT,9,'bold')).pack(side='left')
        self.label(waveform_header,'MASTER OUTPUT',fg=MUTED,font=(MONO,8)).pack(side='right')
        self.live_waveform=LiveWaveform(master); self.live_waveform.pack(fill='both',expand=True,padx=10,pady=(0,2))
        channel_scale=tk.Frame(master,bg=CARD); channel_scale.pack(fill='x',padx=10,pady=(0,7))
        self.label(channel_scale,'L',fg=MINT,font=(MONO,8)).pack(side='left')
        self.label(channel_scale,'R',fg=GOLD,font=(MONO,8)).pack(side='right')
        row=tk.Frame(controls,bg=PANEL); row.pack(fill='both',expand=True,pady=(0,0)); row.rowconfigure(0,weight=1); self.fader_values=[None]*5
        for col,i in enumerate((0,1,3,4)):
            row.columnconfigure(col,weight=1,uniform='fader'); pane=tk.Frame(row,bg=CARD); pane.grid(row=0,column=col,sticky='nsew',padx=4,pady=4)
            names={0:'A VOLUME',1:'B VOLUME',3:'TEMPO',4:'FILTER'}
            channels={0:'M1  A1',1:'M1  A2',3:'M2  A0',4:'M2  A1'}
            self.label(pane,f'F{i+1}  /  {names[i]}',fg=TEXT,font=(FONT,9,'bold')).pack(pady=(9,1))
            self.label(pane,channels[i],fg=DIM,font=(MONO,8)).pack()
            widget=FaderCanvas(pane,self.faders[i],i,self.fader_changed); widget.pack(fill='both',expand=True,padx=5,pady=(3,0))
            val=self.label(pane,'',fg=GOLD if i in (0,3) else MINT,font=(MONO,10,'bold')); val.pack(pady=(0,9)); self.fader_values[i]=val
        cross=tk.Frame(controls,bg=CARD); cross.pack(fill='x',padx=4,pady=(4,0))
        ctop=tk.Frame(cross,bg=CARD); ctop.pack(fill='x',padx=12,pady=(8,0))
        self.label(ctop,'F3  /  CROSSFADER',fg=TEXT,font=(FONT,9,'bold')).pack(side='left')
        self.label(ctop,'M1  A3   ·   SHARP CUT',fg=MUTED,font=(MONO,8)).pack(side='right')
        cf=FaderCanvas(cross,self.faders[2],2,self.fader_changed,horizontal=True); cf.pack(fill='x',padx=18,pady=(0,6))
        self.fader_values[2]=self.label(cross,'',fg=GOLD,font=(MONO,9)); self.fader_values[2].pack(pady=(0,6))

        jog=self.panel(left); jog.pack(fill='x',before=mixer,pady=(0,7))
        top=tk.Frame(jog,bg=PANEL); top.pack(fill='x',padx=16,pady=(7,2))
        self.label(top,'JOG  /  MODE',fg=TEXT,font=(FONT,10,'bold')).pack(side='left')
        self.readout=self.label(top,'',fg=MINT,font=(MONO,9)); self.readout.pack(side='right')
        modes=tk.Frame(jog,bg=PANEL); modes.pack(fill='x',padx=12,pady=(2,4))
        for value,text in [('VINYL','VINYL / SCRATCH'),('JOG','PITCH BEND'),('FX','JOG FILTER'),('MOTORIZED','MOTORIZED')]:
            tk.Radiobutton(modes,text=text,variable=self.mode,value=value,command=self.mode_changed,bg=PANEL,fg=TEXT,
                           selectcolor='#26433d',activebackground=PANEL,activeforeground=TEXT,font=(FONT,9),
                           highlightthickness=0).pack(side='left',padx=(4,12))
        self.jog_info=self.label(jog,'',fg=MUTED,anchor='w',justify='left',wraplength=720,font=(FONT,8))
        self.jog_info.pack(fill='x',padx=16,pady=(1,7)); self._set_mode_hint()

        device=self.panel(right); device.pack(fill='x')
        self.label(device,'01  /  DEVICE LINK',fg=GOLD,font=(FONT,10,'bold')).pack(anchor='w',padx=14,pady=(14,7))
        self.label(device,'XIAO SERIAL PORT',fg=MUTED,font=(FONT,8)).pack(anchor='w',padx=14)
        self.port=ttk.Combobox(device,values=self.ports(),style='Pulse.TCombobox'); self.port.pack(fill='x',padx=14,pady=(4,0))
        self._select_xiao_port()
        row=tk.Frame(device,bg=PANEL); row.pack(fill='x',padx=14,pady=8)
        self.connect_button=self.button(row,'CONNECT',self.connect,accent=True); self.connect_button.pack(side='left')
        self.button(row,'REFRESH',self.refresh_ports).pack(side='left',padx=6)
        tk.Checkbutton(device,text='Use hardware faders',variable=self.hardware,bg=PANEL,fg=TEXT,selectcolor='#26433d',
                       activebackground=PANEL,activeforeground=TEXT,font=(FONT,9),highlightthickness=0).pack(anchor='w',padx=10)
        self.label(device,'AUDIO OUTPUT',fg=MUTED,font=(FONT,8)).pack(anchor='w',padx=14,pady=(8,0))
        audio_row=tk.Frame(device,bg=PANEL); audio_row.pack(fill='x',padx=14,pady=(4,14))
        self.output=ttk.Combobox(audio_row,state='readonly',style='Pulse.TCombobox'); self.output.pack(side='left',fill='x',expand=True)
        self.output.bind('<<ComboboxSelected>>',self.select_output)
        self.button(audio_row,'REFRESH',self.refresh_outputs).pack(side='left',padx=(6,0))

        motor=self.panel(right); motor.pack(fill='both',expand=True,pady=(12,0))
        self.label(motor,'02  /  CAN MOTOR',fg=GOLD,font=(FONT,10,'bold')).pack(anchor='w',padx=14,pady=(14,6))
        self.label(motor,textvariable=self.motor_status,fg=MINT,anchor='w',justify='left',wraplength=275,font=(FONT,9)).pack(fill='x',padx=14)
        self.drive_check=tk.Checkbutton(motor,text='Enable motorized drive',variable=self.drive,command=self.drive_changed,bg=PANEL,
                                        fg=TEXT,selectcolor='#26433d',activebackground=PANEL,activeforeground=TEXT,
                                        font=(FONT,10,'bold'),highlightthickness=0)
        self.drive_check.pack(anchor='w',padx=10,pady=(9,3))
        self.drive_label=self.label(motor,textvariable=self.drive_status,fg=MUTED,anchor='w',justify='left',wraplength=272,font=(FONT,9))
        self.drive_label.pack(fill='x',padx=14,pady=(0,8))
        self.label(motor,'Local ARMED does not confirm motor execution. STOP may fail if CAN is disconnected.',fg=DIM,
                   anchor='w',justify='left',wraplength=272,font=(FONT,8)).pack(fill='x',padx=14,pady=(0,14))
        self.refresh_outputs()

    def _schedule_layout(self, _event=None):
        if not self._layout_pending:
            self._layout_pending = True
            self.after(16, self._sync_layout)

    def _sync_layout(self):
        self._layout_pending = False
        if not self.winfo_exists(): return
        width = max(1180, self.viewport.winfo_width())
        # Natural height is preserved for scrolling in small windows; on large
        # screens let the dashboard stretch to fill the visible work area.
        height = max(self.container.winfo_reqheight(), self.viewport.winfo_height())
        current_width = int(float(self.viewport.itemcget(self.win, 'width') or 0))
        current_height = int(float(self.viewport.itemcget(self.win, 'height') or 0))
        if (width, height) != (current_width, current_height):
            self.viewport.itemconfigure(self.win, width=width, height=height)
        region = (0, 0, width, height)
        if self.viewport.cget('scrollregion') != ' '.join(map(str, region)):
            self.viewport.configure(scrollregion=region)

    def _wheel(self, event):
        axis=self.viewport.xview_scroll if event.state & 0x0001 else self.viewport.yview_scroll
        axis(-1 if event.delta>0 else 1,'units')
    @staticmethod
    def ports(): return [p.device for p in list_ports.comports()]
    def _select_xiao_port(self):
        for p in list_ports.comports():
            if p.vid == 0x2886 and p.pid == 0x00C5:
                self.port.set(p.device); return
    def refresh_ports(self):
        self.port['values']=self.ports()
        if not self.port.get(): self._select_xiao_port()
    def refresh_outputs(self):
        try:
            devs=sd.query_devices(); apis=sd.query_hostapis(); labels=['SYSTEM DEFAULT']; self.outputs=[None]
            for i,d in enumerate(devs):
                if d['max_output_channels']>=2:
                    self.outputs.append(i); labels.append(f"{i}: {audio_device_label(d['name'])} ({apis[d['hostapi']]['name']})")
            self.output['values']=labels
            self.output.current(self.outputs.index(self.engine.output_device) if self.engine.output_device in self.outputs else 0)
        except Exception as exc: self.status.set(f'Audio device error: {exc}')
    def select_output(self, _=None):
        i=self.output.current()
        if i<0: return
        try: self.engine.set_output_device(self.outputs[i])
        except Exception as exc: messagebox.showerror('AUDIO OUTPUT',str(exc)); self.refresh_outputs()
    def _send(self, command):
        if self.link is None or self.link.stop_event.is_set(): raise OSError('USB DISCONNECTED')
        self.link.send(command)
    def _on_telemetry(self, message):
        # This callback runs in the serial reader thread; never touch Tk here.
        self.motor.update_feedback(message['motor'])
    def connect(self):
        if self.link is not None: self.disconnect(); return
        try:
            self.motor.reset_feedback()
            self.link=SerialLink(self.port.get().strip(),on_telemetry=self._on_telemetry)
            self.motor.start(); self.last_hardware=[None]*5
            self.status.set('USB CONNECTED  /  '+self.port.get()); self.connect_button.config(text='DISCONNECT')
        except Exception as exc: self.status.set('CONNECTION FAILED'); messagebox.showerror('SERIAL CONNECTION',str(exc))
    def disconnect(self):
        self.motor.disable(); self.motor.stop()
        if self.link is not None: self.link.close()
        self.link=None; self.motor.reset_feedback(); self.drive.set(False); self.motor_online=False
        self.engine.motor_offline(); self.status.set('USB DISCONNECTED'); self.motor_status.set('Waiting for motor feedback')
        self.drive_status.set('Motor drive disabled'); self.connect_button.config(text='CONNECT')
    def load(self, deck):
        path=filedialog.askopenfilename(filetypes=[('Audio files','*.wav *.flac *.ogg'),('All files','*.*')])
        if not path: return
        try:
            data,_=self.engine.load(deck,path); self.engine.start_stream(); self.tracks[deck]=os.path.basename(path)
            mono=np.max(np.abs(data),axis=1)
            wave=np.array([np.max(c) for c in np.array_split(mono,min(len(mono),350))])
            self.canvases[deck].set_wave(wave)
        except Exception as exc: messagebox.showerror('AUDIO',str(exc))
    def set_bpm(self, deck):
        try: self.engine.set_bpm(deck,float(self.deck_bpm[deck].get() or 0))
        except ValueError as exc: messagebox.showerror('BPM',str(exc))
    def select_deck(self):
        deck=self.selected.get(); self.engine.set_selected(deck); d=self.engine.view()['decks'][deck]
        self.pickup_tempo.arm(self.faders[3].get(),d['tempo']); self.pickup_filter.arm(self.faders[4].get(),d['filter'])
    def fader_changed(self, index):
        values=[v.get() for v in self.faders]
        tempo=self.pickup_tempo.accept(values[3]) if index==3 else self.pickup_tempo.target is None
        fx=self.pickup_filter.accept(values[4]) if index==4 else self.pickup_filter.target is None
        self.engine.set_controls(values,apply_tempo=tempo,apply_filter=fx)
    def apply_hardware(self, message):
        if not self.hardware.get(): return
        changed=[]
        for i,ch in enumerate(SLIDER_INDICES):
            v=normalize(message['adc_uv'][ch],*SLIDER_CALIBRATION_UV[i],inverted=SLIDER_INVERTED[i])
            if v is not None:
                if abs(v-self.faders[i].get())>0.002: self.faders[i].set(v)
                if self.last_hardware[i] is None or abs(v-self.last_hardware[i]) >= 0.005:
                    changed.append(i); self.last_hardware[i]=v
        values=[v.get() for v in self.faders]
        tempo=self.pickup_tempo.accept(values[3]) if 3 in changed else False
        fx=self.pickup_filter.accept(values[4]) if 4 in changed else False
        self.engine.set_controls(values,apply_tempo=tempo,apply_filter=fx)
    def _set_mode_hint(self):
        texts={'VINYL':'Manual rotation follows the selected track. Playback resumes after ~220 ms idle.',
               'JOG':'Turn manually for pitch bend. Stops at the F4 playback rate.',
               'FX':'Turn manually to adjust filter. F5 can take over.',
               'MOTORIZED':'Motor runs at 4 rad/s. Turn or hold it to scratch; F4 controls normal playback. No touch sensor.'}
        self.jog_info.config(text=texts[self.mode.get()])
    def mode_changed(self):
        mode=self.mode.get()
        if mode!=self.previous_mode and self.motor.snapshot()['enabled']: self.motor.disable()
        self.drive.set(False); self.engine.set_motorized_enabled(False); self.engine.set_mode(mode); self.previous_mode=mode; self._set_mode_hint()
    def drive_changed(self):
        if not self.drive.get(): self.motor.disable(); self.engine.set_motorized_enabled(False); return
        if self.mode.get()!='MOTORIZED':
            # Enabling drive is an explicit request for the motorized mode.
            self.mode.set('MOTORIZED'); self.engine.set_mode('MOTORIZED'); self.previous_mode='MOTORIZED'; self._set_mode_hint()
        if self.link is None:
            self.drive.set(False); self.drive_status.set('Cannot enable: connect the XIAO serial port first.'); return
        if not self.motor.enable():
            self.drive.set(False); self.drive_status.set('Cannot enable: '+self.motor.snapshot()['fault'])
        else: self.drive_status.set('Starting: waiting for XIAO local ARMED status...')
    def handle_message(self,message):
        self.apply_hardware(message)
        m=message['motor']; self.motor_online=bool(m.get('online'))
        enabled = (self.mode.get() == 'MOTORIZED' and self.motor_online and bool(m.get('armed'))
                   and bool(self.motor.snapshot().get('enabled')))
        self.engine.set_motorized_enabled(enabled)
        if self.motor_online:
            self.motor_rpm=float(m.get('rpm10',0))/10
            before=self.engine.view()['decks'][self.selected.get()]['filter']
            self.engine.motor_sample(m.get('angle_mrad',0),message.get('t',0))
            after=self.engine.view()['decks'][self.selected.get()]['filter']
            if self.mode.get()=='FX' and before!=after: self.pickup_filter.arm(self.faders[4].get(),after)
        else: self.engine.motor_offline()
        platter = ''
        if enabled:
            deck = self.engine.view()['decks'][self.selected.get()]
            platter = ('   ·   SCRATCH' if deck['scratch'] else
                       '   ·   PLATTER READY' if self.engine.motorized_ready else '   ·   WAITING FOR SPEED')
        self.motor_status.set(f"{'FEEDBACK ONLINE' if self.motor_online else 'FEEDBACK OFFLINE'}  /  LOCAL {'ARMED' if m.get('armed') else 'DISARMED'}\n{self.motor_rpm:+.1f} rpm   ·   CAN ERROR {m.get('error',0)}{platter}")
    def update_loop(self):
        if self.link is not None:
            try:
                if self.link.stop_event.is_set():
                    self.disconnect(); self.status.set('USB DISCONNECTED'); self.drive_status.set('Connection lost; motor control stopped.')
                else:
                    # Bound work per frame so a fast telemetry stream cannot starve the UI.
                    for _ in range(8): self.handle_message(self.link.messages.get_nowait())
            except queue.Empty: pass
            except Exception as exc:
                self.disconnect(); self.status.set('DEVICE DATA ERROR'); self.drive_status.set(str(exc))
        state=self.motor.snapshot()
        self.drive.set(state['enabled'])
        if not state['enabled']: self.engine.set_motorized_enabled(False)
        if state['fault']:
            self.drive_status.set('Stopped: '+state['fault']); self.drive_label.config(fg=RED)
        elif state['enabled']:
            self.drive_status.set('Local armed / target 4 rad/s' if state['armed'] else 'Starting: waiting for XIAO local ARMED status...')
            self.drive_label.config(fg=MINT)
        elif self.link is not None and not self.drive_status.get().startswith('Cannot enable'):
            self.drive_status.set('Motor drive disabled'); self.drive_label.config(fg=MUTED)
        self.draw(); self.after(40,self.update_loop)
    def draw(self):
        view=self.engine.view()
        levels=self.engine.take_meter_peaks()
        for meter, level in zip(self.deck_meters + self.master_meters, levels): meter.set_level(level)
        self.master_clip.config(text='CLIP' if view['clip'] else '')
        samples, sample_rate = self.engine.waveform_snapshot()
        self.live_waveform.update_samples(samples, sample_rate)
        def fmt(x): return f'{int(x)//60:02d}:{int(x)%60:02d}'
        for i,d in enumerate(view['decks']):
            self.deck_labels[i].config(text=self.tracks[i]); self.play_buttons[i].config(text='PAUSE' if d['playing'] else 'PLAY')
            self.deck_tags[i].config(text='● SELECTED' if i==view['selected'] else 'STANDBY')
            self.deck_times[i].config(text=f"{fmt(d['position']/d['rate'])}  /  {fmt(d['length']/d['rate'])}")
            self.canvases[i].set_progress(d['position']/max(1,d['length']))
            self.records[i].update_phase(d['position']/d['rate']*2.5)
        values=[v.get() for v in self.faders]
        for i in (0,1): self.fader_values[i].config(text=f'{values[i]*100:4.0f}%')
        self.fader_values[2].config(text=f'POSITION  {100*values[2]:.0f}%')
        self.fader_values[3].config(text=f'{0.5+values[3]:.2f}×')
        self.fader_values[4].config(text=f'{values[4]*100:.0f}%')
        d=view['decks'][view['selected']]; bpm=f"{d['bpm']*(0.5+d['tempo']):.1f} BPM" if d['bpm'] else 'BPM --'
        self.readout.config(text=f"DECK {'AB'[view['selected']]}   {0.5+d['tempo']:.2f}×   {bpm}   XRUN {view['underflows']}"+('   CLIP' if view['clip'] else ''))
        self.pickup_label.config(text='F4 '+('PICKUP' if self.pickup_tempo.target is not None else 'ACTIVE')+'  /  F5 '+('PICKUP' if self.pickup_filter.target is not None else 'ACTIVE'))
    def shutdown(self):
        self.disconnect(); self.engine.close(); self.destroy()

if __name__=='__main__': App().mainloop()
