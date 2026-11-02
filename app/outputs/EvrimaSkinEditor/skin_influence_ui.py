"""Small on-demand color influence window using the existing serial renderer."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk
from skin_document import SLOTS, raw_number
from skin_influence import probe_documents, difference_overlay
from skin_workflow_ui import output_dir


class SkinInfluence:
    def __init__(self, editor):
        self.editor = editor; self.source = copy.deepcopy(editor.doc)
        self.camera_settings = (editor.yaw, editor.pitch, editor.zoom)
        self.lighting_label = editor.renderer.lighting_label
        self.closed = False; self.future = None; self.timer = None; self.generation = 0
        self.queue = []; self.images = {}; self.photos = {}; self.errors = {}; self.ready = False
        self.was_playing = editor.idle_playing.get(); editor.idle_playing.set(False); editor.toggle_idle()
        self.window = tk.Toplevel(editor.root); self.window.title('Skin Studio — Section influence')
        self.window.geometry('1120x760'); self.window.minsize(1100, 700)
        self.window.transient(editor.root); self.window.grab_set(); self.window.protocol('WM_DELETE_WINDOW', self.close)
        header = ttk.Frame(self.window, padding=12); header.pack(fill='x')
        ttk.Label(header, text='Section influence', font=('Segoe UI',19,'bold')).pack(anchor='w')
        d = self.source
        self.context = f'{d["species"]} / Pattern {d["pattern"]+1} / {"Female" if d["female"] else "Male"} / Growth {d["growth"]:.0%} / {"Prime" if d.get("prime") else "Standard"} / Variation {d["variation"]:g}'
        origin = editor.assets.profiles[d['species']]['body']['patterns'][d['pattern']].get('origin','game-table')
        if origin != 'game-table': self.context += ' / ' + ('Asset-only texture: no verified game index' if origin == 'asset-preview' else 'Stored material: no recovered pattern table')
        ttk.Label(header, text=self.context, wraplength=1060).pack(anchor='w')
        ttk.Label(header, text='Find out where a color section shows up. Your working design stays unchanged.', wraplength=1060).pack(anchor='w', pady=(4,8))
        controls = ttk.Frame(header); controls.pack(fill='x')
        self.labels = {f'{label} ({slot})': slot for slot,(label,*_) in SLOTS.items()}
        self.slot = tk.StringVar(value=next(k for k,v in self.labels.items() if v=='b'))
        self.low = tk.StringVar(value='0'); self.high = tk.StringVar(value='1')
        self.quality = tk.StringVar(value='512'); self.threshold = tk.StringVar(value='8')
        ttk.Label(controls, text='Section').pack(side='left')
        ttk.Combobox(controls, textvariable=self.slot, values=list(self.labels), state='readonly', width=22).pack(side='left', padx=5)
        for title,var in [('Low RGB',self.low),('High RGB',self.high)]:
            ttk.Label(controls,text=title).pack(side='left',padx=(5,3));entry=ttk.Entry(controls,textvariable=var,width=12);entry.pack(side='left')
            entry.bind('<Return>',lambda e:self.run())
        ttk.Label(controls,text='Detail').pack(side='left',padx=(8,3))
        ttk.Combobox(controls,textvariable=self.quality,values=['256','512','1024'],state='readonly',width=6).pack(side='left')
        ttk.Label(controls,text='Threshold').pack(side='left',padx=(8,3))
        ttk.Combobox(controls,textvariable=self.threshold,values=['2','8','16'],state='readonly',width=4).pack(side='left')
        buttons=ttk.Frame(header);buttons.pack(fill='x',pady=(10,0))
        ttk.Button(buttons,text='Test this section',command=self.run).pack(side='left')
        ttk.Button(buttons,text='Stop',command=self.stop).pack(side='left',padx=8)
        ttk.Label(buttons,text='Right view').pack(side='left',padx=(12,4))
        self.view=tk.StringVar(value='Highlight changes')
        box=ttk.Combobox(buttons,textvariable=self.view,values=['Highlight changes','Low probe','High probe'],state='readonly',width=20)
        box.pack(side='left');box.bind('<<ComboboxSelected>>',lambda e:self.show())
        self.export_button=ttk.Button(buttons,text='Save comparison PNG…',command=self.export,state='disabled');self.export_button.pack(side='right')
        pair=ttk.Frame(self.window,padding=(12,0));pair.pack(fill='x')
        self.pictures={};self.captions={}
        for column,side in enumerate(('Current skin','Probe view')):
            frame=ttk.Frame(pair);frame.grid(row=0,column=column,sticky='nsew',padx=(0,12) if column==0 else 0);pair.columnconfigure(column,weight=1)
            self.captions[side]=ttk.Label(frame,text=side,font=('Segoe UI',11,'bold'));self.captions[side].pack(anchor='w')
            self.pictures[side]=ttk.Label(frame);self.pictures[side].pack(pady=6)
        self.result=tk.StringVar(value='Preparing probes…')
        ttk.Label(self.window,textvariable=self.result,wraplength=1060,padding=12).pack(fill='x')
        ttk.Label(self.window,text='Orange highlights changes in the picture. The percentage measures the whole picture, not body coverage. Some effects may be hidden by the pattern or other colors.',wraplength=1060,padding=(12,0)).pack(fill='x')
        footer=ttk.Frame(self.window,padding=12);footer.pack(side='bottom',fill='x')
        ttk.Button(footer,text='Close',command=self.close).pack(side='right')
        self.status=tk.StringVar();ttk.Label(footer,textvariable=self.status,wraplength=960).pack(side='left')
        for var in (self.slot,self.low,self.high,self.quality,self.threshold):var.trace_add('write',self.invalidate)
        self.run()

    def invalidate(self,*_):
        if self.closed:return
        self.generation+=1;self.queue.clear();self.ready=False;self.images.clear();self.photos.clear();self.errors.clear()
        if self.future is not None:self.future.cancel()
        for side in self.pictures:self.pictures[side].configure(image='')
        self.export_button.configure(state='disabled');self.result.set('Settings changed. Run probes to update the comparison.')
        self.status.set('Working design unchanged.')

    def run(self):
        if self.closed:return
        self.invalidate()
        try:
            slot=self.labels[self.slot.get()];low=raw_number(self.low.get());high=raw_number(self.high.get())
            size=int(self.quality.get());threshold=int(self.threshold.get())
            if size not in (256,512,1024) or threshold not in (2,8,16):raise ValueError('Choose a listed bake size and threshold.')
            self.docs=probe_documents(self.source,slot,low,high)
        except (ValueError,KeyError) as error:self.result.set(str(error));return
        self.settings=dict(slot=slot,low=low,high=high,size=size,threshold=threshold)
        self.queue=list(self.docs.items())
        self.probe_caption=f'{self.slot.get()}: RGB {low:g} and {high:g}; alpha unchanged'
        self.result.set(self.probe_caption + ('. Eye probes temporarily override original-eye colors.' if slot=='e' else '. Other sections and eyes retain their current settings.'))
        if self.future is None:self.next_job()

    def next_job(self):
        if self.closed:return
        if not self.queue:
            if self.images or self.errors:self.finish()
            return
        label,doc=self.queue.pop(0);self.job=(self.generation,label)
        assets=self.editor.assets;size=self.settings['size']
        def bake():
            material=assets.material(doc,size);shape=assets.shape(doc)
            return assets.mesh,material,shape
        self.status.set('Rendering '+label+'…')
        self.future=self.editor.pool.submit(bake);self.timer=self.window.after(40,self.poll)

    def poll(self):
        self.timer=None
        if self.closed:return
        if not self.future.done():self.timer=self.window.after(40,self.poll);return
        future,self.future=self.future,None
        generation,label=self.job
        if generation!=self.generation:self.next_job();return
        try:
            from morph_inspector import preview_camera
            mesh,material,shape=future.result();yaw,pitch,zoom=self.camera_settings
            camera=preview_camera(shape['camera_standard'],shape['camera_prime'],yaw,pitch,520,325,zoom)
            im=self.editor.renderer.draw(mesh,[],camera,520,325,models=[(material,shape['points'])])
            if self.editor.renderer._surface_error:raise ValueError(str(self.editor.renderer._surface_error))
            self.images[label]=im
        except Exception as error:self.errors[label]=str(error)
        self.next_job()

    def finish(self):
        self.ready=all(k in self.images for k in ('Current skin','Low probe','High probe')) and not self.errors
        if not self.ready:
            self.result.set('Comparison unavailable. '+ '; '.join(k+': '+v for k,v in self.errors.items()))
            self.status.set('Choose different probe values and run again. Working skin and raw values are unchanged.');return
        self.images['Highlight changes'],self.metrics=difference_overlay(self.images['Current skin'],self.images['Low probe'],self.images['High probe'],self.settings['threshold'])
        m=self.metrics
        self.result.set(self.probe_caption+f'. {m["changed_pixels"]:,} / {m["image_pixels"]:,} image pixels changed ({m["image_percent"]:.2f}%). Threshold > {m["threshold"]}/255 per channel.'+
            (' Eye probes temporarily override original-eye colors.' if self.settings['slot']=='e' else '')+
            (' No visible response at these values and this view.' if not m['changed_pixels'] else ''))
        self.export_button.configure(state='normal');self.show()
        self.status.set('Ready. Close and rotate in Studio to inspect another angle; then reopen this window.')

    def show(self):
        if not self.ready:return
        for side,key in (('Current skin','Current skin'),('Probe view',self.view.get())):
            if key not in self.images:return
            self.photos[side]=ImageTk.PhotoImage(self.images[key]);self.pictures[side].configure(image=self.photos[side]);self.captions[side].configure(text=key)

    def stop(self):
        self.invalidate();self.result.set('Probes stopped. Run probes to start again.');self.status.set('Working design unchanged.')

    def export(self):
        if not self.ready:return
        path=filedialog.asksaveasfilename(parent=self.window,title='Save section influence comparison',initialdir=output_dir(self.editor),initialfile='Section influence.png',defaultextension='.png',filetypes=[('PNG image','*.png')])
        if not path:return
        try:
            image=Image.new('RGB',(1080,510),'#101921');draw=ImageDraw.Draw(image)
            try:font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',16)
            except OSError:font=ImageFont.load_default(size=16)
            def line(y,text,color='white'):
                while draw.textlength(text,font=font)>1050:text=text[:-2]+'…'
                draw.text((15,y),text,font=font,fill=color)
            line(10,self.context);line(35,self.probe_caption,'#9fe5e0')
            for label,x in (('Current skin',15),(self.view.get(),545)):
                draw.text((x,62),label,font=font,fill='white');image.paste(self.images[label].convert('RGB'),(x,90))
            m=self.metrics
            line(426,f'{m["image_percent"]:.2f}% of IMAGE pixels changed / >{m["threshold"]}/255 / {self.settings["size"]}px bake / fixed camera and pose')
            line(451,'Orange highlight = response to either probe, not a recovered mask. No response does not prove unused.')
            line(476,'Light: ' + self.lighting_label + ' / Studio preview; not live-game validation.' + (' Eye probes override original colors.' if self.settings['slot']=='e' else ''))
            image.save(path);self.status.set('Saved '+Path(path).name)
        except OSError as error:messagebox.showerror('Cannot save comparison',str(error),parent=self.window)

    def close(self):
        if self.closed:return
        self.closed=True;self.queue.clear();self.images.clear();self.photos.clear()
        if self.timer is not None:self.window.after_cancel(self.timer)
        if self.future is not None:self.future.cancel()
        self.window.grab_release();self.window.destroy();self.editor.skin_influence=None
        if not self.editor.closed:
            self.editor.idle_playing.set(self.was_playing);self.editor.toggle_idle();self.editor.schedule_draw()
