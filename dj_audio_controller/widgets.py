"""Custom, lightweight canvases for the dual-deck dashboard."""
import math
import time
import numpy as np
import tkinter as tk

BG = '#0b101a'
PANEL = '#151d2a'
CARD = '#1b2634'
TRACK = '#111a25'
TEXT = '#eef4ef'
MUTED = '#8b9ca5'
DIM = '#536875'
MINT = '#66e5c1'
GOLD = '#ffcf58'
RED = '#ff777b'
BLUE = '#78bfff'

class FaderCanvas(tk.Canvas):
    """Only mouse/keyboard events write the variable, preserving hardware pickup."""
    def __init__(self, parent, variable, index, on_change, horizontal=False):
        super().__init__(parent, bg=CARD, highlightthickness=0, takefocus=True,
                         cursor='hand2', width=120 if horizontal else 88,
                         height=58 if horizontal else 100)
        self.variable, self.index, self.on_change, self.horizontal = variable, index, on_change, horizontal
        self.pending = False
        self.bind('<Configure>', self.request_draw)
        self.bind('<Button-1>', self.move)
        self.bind('<B1-Motion>', self.move)
        for key, delta in (('<Left>', -0.02), ('<Down>', -0.02), ('<Right>', 0.02), ('<Up>', 0.02)):
            self.bind(key, lambda e, d=delta: self.nudge(d))
        variable.trace_add('write', self.request_draw)

    def request_draw(self, *_):
        if not self.pending and self.winfo_exists():
            self.pending = True
            self.after(16, self.draw)

    def move(self, e):
        self.focus_set()
        w, h = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        value = (e.x-20) / max(1, w-40) if self.horizontal else (h-22-e.y) / max(1, h-42)
        self.variable.set(max(0.0, min(1.0, value)))
        self.on_change(self.index)

    def nudge(self, amount):
        self.variable.set(max(0.0, min(1.0, self.variable.get() + amount)))
        self.on_change(self.index)
        return 'break'

    def draw(self):
        self.pending = False
        if not self.winfo_exists(): return
        self.delete('all')
        w, h = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        v = max(0.0, min(1.0, float(self.variable.get())))
        color = GOLD if self.index in (0,2,3) else MINT
        if self.horizontal:
            a, b, y = 20, max(21,w-20), h*0.43; x = a+(b-a)*v
            self.create_line(a,y,b,y,fill='#31414e',width=7,capstyle='round')
            self.create_line(a,y,x,y,fill=color,width=4,capstyle='round')
            for i in range(9):
                xx=a+(b-a)*i/8; self.create_line(xx,y+12,xx,y+16,fill=DIM)
            self.create_rectangle(x-7,y-13,x+7,y+13,fill=TEXT,outline=GOLD,width=1)
            self.create_text(a,y+29,text='A',fill=MUTED,font=('Segoe UI',8),anchor='w')
            self.create_text(b,y+29,text='B',fill=MUTED,font=('Segoe UI',8),anchor='e')
        else:
            x=w/2; a=20; b=max(21,h-22); y=b-(b-a)*v
            self.create_line(x,a,x,b,fill='#31414e',width=7,capstyle='round')
            self.create_line(x,b,x,y,fill=color,width=4,capstyle='round')
            for i in range(11):
                yy=a+(b-a)*i/10
                self.create_line(x-26,yy,x-19,yy,fill=DIM)
                self.create_line(x+19,yy,x+26,yy,fill=DIM)
            self.create_rectangle(x-15,y-9,x+15,y+9,fill=TEXT,outline=color,width=1)
            self.create_line(x-9,y,x+9,y,fill='#647c82',width=2)

class Waveform(tk.Canvas):
    """Draw waveform only on load/resize; move just the playhead on each update."""
    def __init__(self, parent, color, seek):
        super().__init__(parent, bg=TRACK, height=60, highlightthickness=0, cursor='hand2')
        self.color, self.seek, self.wave = color, seek, None
        self.bind('<Configure>', lambda _: self.render())
        self.bind('<Button-1>', lambda e: self.seek(e.x/max(1,self.winfo_width())))

    def set_wave(self, wave): self.wave = wave; self.render()
    def render(self):
        self.delete('all')
        w,h=max(1,self.winfo_width()),max(1,self.winfo_height())
        for i in range(1,8):
            x=i*w/8; self.create_line(x,0,x,h,fill='#22303b')
        self.create_line(0,h/2,w,h/2,fill='#2d4149')
        if self.wave is None:
            self.create_text(w/2,h/2,text='LOAD TRACK',fill=DIM,font=('Segoe UI',10))
        else:
            for i,amp in enumerate(self.wave):
                x=i*w/max(1,len(self.wave)-1); bar=min(1.0,float(amp))*(h/2-7)
                self.create_line(x,h/2-bar,x,h/2+bar,fill=self.color)
        self.create_line(0,0,0,h,fill=TEXT,width=2,tags='head')

    def set_progress(self, fraction):
        w,h=max(1,self.winfo_width()),max(1,self.winfo_height())
        x=max(0.0,min(1.0,fraction))*w
        if not self.find_withtag('head'): self.render()
        self.coords('head',x,0,x,h)
        self.tag_raise('head')

class Record(tk.Canvas):
    """Virtual playhead artwork; this does not claim motor angle or touch input."""
    def __init__(self, parent, color):
        super().__init__(parent,bg=PANEL,width=82,height=82,highlightthickness=0)
        cx=cy=41
        for r,col in ((38,'#263747'),(35,'#101a24'),(29,'#263747'),(23,'#101a24'),(14,'#283841')):
            self.create_oval(cx-r,cy-r,cx+r,cy+r,fill=col,outline='#3a4d57')
        self.needle=self.create_line(cx,cy,cx,cy-29,fill=color,width=3)
        self.create_oval(cx-4,cy-4,cx+4,cy+4,fill=TEXT,outline='')
    def update_phase(self, phase):
        cx=cy=41
        self.coords(self.needle,cx,cy,cx+29*math.sin(phase),cy-29*math.cos(phase))

class LevelMeter(tk.Canvas):
    """Segmented dBFS peak meter with fast attack and a short visual decay."""
    def __init__(self, parent):
        super().__init__(parent, bg=TRACK, height=16, highlightthickness=0)
        self.level = 0.0
        self.segments = [self.create_rectangle(0,0,0,0,outline='') for _ in range(32)]
        self.last_update = time.monotonic()
        self.bind('<Configure>', lambda _: self.draw())

    def set_level(self, peak):
        now = time.monotonic()
        elapsed = max(0.0, min(now - self.last_update, 1.0))
        self.last_update = now
        # Map -48..0 dBFS to the visible range; silence stays at zero.
        value = max(0.0, min(1.0, (20 * math.log10(max(float(peak), 1e-8)) + 48) / 48))
        self.level = max(value, self.level - elapsed * 1.25)
        self.draw()

    def draw(self):
        width = max(1, self.winfo_width()); height = max(1, self.winfo_height())
        count = len(self.segments)
        for i, item in enumerate(self.segments):
            x0 = i * width / count; x1 = (i + 1) * width / count - 2
            color = MINT if i < 24 else GOLD if i < 29 else RED
            if (i + 1) / count > self.level: color = '#293943'
            self.coords(item, x0, 2, max(x0, x1), height - 2)
            self.itemconfigure(item, fill=color)

def waveform_points(samples, count=384):
    """Resample the latest real stereo output to a bounded drawing size."""
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim != 2 or data.shape[1] != 2 or len(data) < 2:
        return np.zeros((count, 2), dtype=np.float32)
    source_x = np.arange(len(data))
    x = np.linspace(0, len(data)-1, count)
    return np.clip(np.column_stack((np.interp(x, source_x, data[:, 0]),
                                    np.interp(x, source_x, data[:, 1]))), -1, 1)

class LiveWaveform(tk.Canvas):
    """Oscilloscope-style stereo waveform from the actual final output."""
    def __init__(self, parent, count=384):
        super().__init__(parent, bg=TRACK, height=70, highlightthickness=0)
        self.values = np.zeros((count, 2), dtype=np.float32)
        self.gridlines = [self.create_line(0,0,0,0,fill='#22303b') for _ in range(3)]
        self.lines = [self.create_line(0,0,1,0,fill=color,width=2) for color in (MINT,GOLD)]
        self.bind('<Configure>', lambda _: self.draw())

    def update_samples(self, samples, rate):
        self.values = waveform_points(samples, len(self.values))
        self.draw()

    def draw(self):
        w, h = max(1,self.winfo_width()), max(1,self.winfo_height())
        for item, fraction in zip(self.gridlines, (0.25,0.5,0.75)):
            self.coords(item,0,h*fraction,w,h*fraction)
        xs = np.linspace(0,w,len(self.values))
        for channel, line in enumerate(self.lines):
            center = h*(0.25 if channel == 0 else 0.75)
            ys = center-self.values[:,channel]*max(1,h*0.22)
            self.coords(line,*np.column_stack((xs,ys)).ravel().tolist())
