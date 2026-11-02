"""Live pattern contact sheet using existing textures and one serial worker."""
import copy
import hashlib
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk
from skin_document import export_filename, save_json
from skin_workflow_ui import output_dir


def pattern_choices(profile, include_assets=False):
    rows = []
    for index, pattern in enumerate(profile['body']['patterns']):
        if not pattern.get('available', True): continue
        origin = pattern.get('origin', 'game-table')
        if origin == 'asset-preview' and not include_assets: continue
        label = ('Asset texture: ' + pattern['name']) if origin == 'asset-preview' else ('Stored material: ' + pattern['name']) if origin == 'stored-material' else f'Pattern {index+1}: {pattern["name"]}'
        rows.append(dict(index=index, label=label, origin=origin, note=pattern.get('note', '')))
    return rows


class PatternAudition:
    def __init__(self, editor):
        self.editor = editor; self.source = copy.deepcopy(editor.doc)
        self.profile = editor.assets.profiles[self.source['species']]
        self.camera_settings = (editor.yaw, editor.pitch, editor.zoom)
        self.lighting_label = editor.renderer.lighting_label
        self.closed = False; self.future = None; self.timer = None; self.generation = 0
        self.queue = []; self.rows = []; self.stopping = False; self.completed = 0
        self.refresh_timer = None; self.dirty = False; self.refreshing = False
        self.observed = None
        self.window = tk.Toplevel(editor.root); self.window.title('Skin Studio — Pattern audition')
        self.window.geometry('1120x850'); self.window.minsize(1040, 720)
        self.window.transient(editor.root); self.window.protocol('WM_DELETE_WINDOW', self.close)
        header = ttk.Frame(self.window, padding=12); header.pack(fill='x')
        ttk.Label(header, text='Pattern audition', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        d = self.source
        self.context = f'{d["species"]} / {"Female" if d["female"] else "Male"} / Growth {d["growth"]:.0%} / {"Prime" if d["prime"] else "Standard"} / Variation {d["variation"]:g}'
        self.context_label = tk.StringVar(value=d['name'] + ' • ' + self.context)
        ttk.Label(header, textvariable=self.context_label, wraplength=1060).pack(anchor='w')
        ttk.Label(header, text='Keep editing in Studio. These cards follow your changes. Choose a pattern, then Apply.', wraplength=1060).pack(anchor='w')
        options = ttk.Frame(header); options.pack(fill='x', pady=8)
        self.quality = tk.StringVar(value='512')
        ttk.Label(options, text='Preview detail').pack(side='left')
        ttk.Combobox(options, textvariable=self.quality, values=['256', '512', '1024'], state='readonly', width=6).pack(side='left', padx=8)
        current = self.profile['body']['patterns'][d['pattern']]
        self.include_assets = tk.BooleanVar(value=current.get('origin') == 'asset-preview')
        ttk.Checkbutton(options, text='Include extra previews (unverified in game)', variable=self.include_assets).pack(side='left', padx=8)
        ttk.Button(options, text='Refresh now', command=self.run).pack(side='left', padx=8)
        self.cancel_button = ttk.Button(options, text='Cancel', command=self.cancel); self.cancel_button.pack(side='left')
        self.sheet_button = ttk.Button(options, text='Save contact sheet…', command=self.export_sheet, state='disabled'); self.sheet_button.pack(side='right')
        area = ttk.Frame(self.window, padding=(12, 0)); area.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(area, highlightthickness=0)
        self.canvas.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(area, orient='vertical', command=self.canvas.yview); scroll.pack(side='right', fill='y')
        self.canvas.configure(yscrollcommand=scroll.set)
        self.grid = ttk.Frame(self.canvas); self.pane = self.canvas.create_window((0, 0), window=self.grid, anchor='nw')
        self.grid.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.pane, width=e.width))
        def wheel(event):
            if str(event.widget).startswith(str(self.grid)) or event.widget is self.canvas:
                self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        self.window.bind('<MouseWheel>', wheel, add='+')
        self.selection = tk.IntVar(value=d['pattern'])
        footer = ttk.Frame(self.window, padding=12); footer.pack(fill='x')
        self.info = tk.StringVar(value='Preparing patterns…')
        ttk.Label(footer, textvariable=self.info, wraplength=1060).pack(anchor='w', pady=(0, 8))
        buttons = ttk.Frame(footer); buttons.pack(fill='x')
        self.apply_button = ttk.Button(buttons, text='Apply selected pattern', command=self.apply, state='disabled'); self.apply_button.pack(side='left')
        self.project_button = ttk.Button(buttons, text='Save selected project…', command=self.save_project, state='disabled'); self.project_button.pack(side='left', padx=8)
        ttk.Button(buttons, text='Close', command=self.close).pack(side='right')
        self.status = tk.StringVar()
        ttk.Label(self.window, textvariable=self.status, wraplength=1060, padding=(12, 0, 12, 10)).pack(fill='x')
        self.quality.trace_add('write', lambda *_: self.editor_changed())
        self.include_assets.trace_add('write', lambda *_: self.editor_changed())
        self.run()

    def state(self):
        return (copy.deepcopy(self.editor.doc),
                (self.editor.yaw, self.editor.pitch, self.editor.zoom),
                self.editor.renderer.lighting_label, self.quality.get(), self.include_assets.get())

    def editor_changed(self):
        if self.closed or self.refreshing: return
        state = self.state()
        if state == self.observed: return
        self.observed = state
        self.generation += 1; self.dirty = True; self.queue.clear()
        if self.future is not None: self.future.cancel()
        if self.refresh_timer is not None: self.window.after_cancel(self.refresh_timer)
        self.sheet_button.configure(state='disabled')
        self.apply_button.configure(state='disabled'); self.project_button.configure(state='disabled')
        self.status.set('Design or view changed. Updating patterns after you pause; previous cards are out of date.')
        self.refresh_timer = self.window.after(600, self.run)

    def ready_for_action(self):
        # A click may arrive before the editor's live-input debounce. Never
        # replace those pending colors with the old audition snapshot.
        self.editor.cancel_live_colors()
        if not self.editor.apply_controls():
            self.status.set('Finish the incomplete design input in Skin Studio first.'); return False
        self.editor_changed()
        if self.dirty:
            self.status.set('Wait for the updated pattern previews before applying or saving.'); return False
        return True

    def run(self):
        if self.closed: return
        if self.refresh_timer is not None:
            self.window.after_cancel(self.refresh_timer); self.refresh_timer = None
        previous_species = self.source['species']
        self.source = copy.deepcopy(self.editor.doc)
        self.profile = self.editor.assets.profiles[self.source['species']]
        self.camera_settings = (self.editor.yaw, self.editor.pitch, self.editor.zoom)
        self.lighting_label = self.editor.renderer.lighting_label
        d = self.source
        if previous_species != d['species']:
            self.selection.set(d['pattern'])
            self.refreshing = True
            try: self.include_assets.set(self.profile['body']['patterns'][d['pattern']].get('origin') == 'asset-preview')
            finally: self.refreshing = False
        self.context = f'{d["species"]} / {"Female" if d["female"] else "Male"} / Growth {d["growth"]:.0%} / {"Prime" if d["prime"] else "Standard"} / Variation {d["variation"]:g}'
        self.context_label.set(d['name'] + ' • ' + self.context)
        self.observed = self.state()
        try:
            size = int(self.quality.get())
            if size not in (256, 512, 1024): raise ValueError('Choose 256, 512 or 1024 color-bake detail.')
            rows = pattern_choices(self.profile, self.include_assets.get())
            if len(rows) > 32: raise ValueError('This catalog exceeds the supported pattern count.')
        except ValueError as error: self.status.set(str(error)); return
        self.generation += 1; self.stopping = False; self.dirty = False; self.completed = 0; self.batch_size = size
        self.rows = rows; self.queue = list(rows)
        for widget in self.grid.winfo_children(): widget.destroy()
        self.sheet_button.configure(state='disabled')
        self.apply_button.configure(state='disabled'); self.project_button.configure(state='disabled')
        if self.selection.get() not in [r['index'] for r in rows]: self.selection.set(rows[0]['index'] if rows else -1)
        for i, row in enumerate(rows):
            self.grid.columnconfigure(i % 3, weight=1)
            card = ttk.LabelFrame(self.grid, padding=6); card.grid(row=i//3, column=i%3, padx=4, pady=6, sticky='nsew')
            label = ('Asset texture preview' if row['origin'] == 'asset-preview' else 'Stored material' if row['origin'] == 'stored-material' else f'Pattern {row["index"]+1}') + (' (current)' if row['index'] == self.source['pattern'] else '')
            ttk.Radiobutton(card, text=label, variable=self.selection, value=row['index'], command=self.select).pack(anchor='w')
            ttk.Label(card, text=row['label'], wraplength=310).pack(anchor='w')
            row['picture'] = ttk.Label(card, text='Waiting to render…', width=42, anchor='center'); row['picture'].pack(pady=4)
            row['picture'].bind('<Button-1>', lambda e, index=row['index']: self.choose(index))
            row['summary'] = ttk.Label(card, text=' ', wraplength=310); row['summary'].pack(anchor='w')
        self.select(); self.cancel_button.configure(state='normal')
        if self.future is None: self.next_job()
        else: self.future.cancel()

    def next_job(self):
        if self.closed: return
        if self.dirty: return  # A newer design is waiting for its debounce.
        if self.stopping or not self.queue:
            self.queue.clear(); self.cancel_button.configure(state='disabled')
            success = sum('image' in r for r in self.rows)
            self.sheet_button.configure(state='normal' if success else 'disabled')
            self.status.set(('Stopped. ' if self.stopping else 'Ready. ') + f'{success}/{len(self.rows)} previews available.')
            return
        row = self.queue.pop(0); doc = copy.deepcopy(self.source); doc['pattern'] = row['index']
        self.job = (self.generation, row)
        assets = self.editor.assets; size = self.batch_size
        def bake():
            material = assets.material(doc, size); shape = assets.shape(doc)
            return assets.mesh, material, shape
        self.status.set(f'Updating previews… {self.completed}/{len(self.rows)} ready.')
        self.future = self.editor.pool.submit(bake); self.timer = self.window.after(40, self.poll)

    def poll(self):
        self.timer = None
        if self.closed: return
        self.editor_changed()  # Reject stale results even before another UI callback.
        if not self.future.done(): self.timer = self.window.after(40, self.poll); return
        future, self.future = self.future, None
        generation, row = self.job
        if generation != self.generation or self.stopping: self.next_job(); return
        try:
            from morph_inspector import preview_camera
            mesh, material, shape = future.result()
            yaw, pitch, zoom = self.camera_settings
            camera = preview_camera(shape['camera_standard'], shape['camera_prime'], yaw, pitch, 640, 400, zoom)
            image = self.editor.renderer.draw(mesh, [], camera, 640, 400, models=[(material, shape['points'])])
            if self.editor.renderer._surface_error: raise ValueError(str(self.editor.renderer._surface_error))
            digest = hashlib.sha256(image.tobytes()).hexdigest()
            same = next((r for r in self.rows if r.get('digest') == digest), None)
            row.update(image=image, digest=digest, photo=ImageTk.PhotoImage(image.resize((320, 200), Image.Resampling.LANCZOS)))
            row['picture'].configure(image=row['photo'], text='', width=0)
            row['summary'].configure(text=('Same rendered pixels as ' + same['label']) if same else 'Asset only — no verified game index' if row['origin'] == 'asset-preview' else 'Stored material — no recovered pattern table' if row['origin'] == 'stored-material' else 'Ready')
        except Exception as error:
            row['error'] = str(error); row['picture'].configure(image='', text='Preview unavailable'); row['summary'].configure(text=str(error))
        self.completed += 1; self.select(); self.next_job()

    def cancel(self):
        if self.refresh_timer is not None:
            self.window.after_cancel(self.refresh_timer); self.refresh_timer = None
        self.stopping = True; self.queue.clear()
        if self.future is not None:
            self.future.cancel(); self.status.set('Stopping after the current bake. Finished previews are kept.')
        elif self.dirty:
            self.status.set('Paused with out-of-date previews. Edit the design or choose Refresh now to update.')
        else: self.next_job()

    def selected(self):
        return next((r for r in self.rows if r['index'] == self.selection.get()), None)

    def choose(self, index): self.selection.set(index); self.select()

    def select(self):
        row = self.selected(); ready = not self.dirty and row is not None and 'image' in row
        for button in (self.apply_button, self.project_button): button.configure(state='normal' if ready else 'disabled')
        if row is None:
            self.info.set('No available patterns match this filter. Enable asset-only previews if this dinosaur uses them.'); return
        text = row['label'] + '. '
        if 'error' in row: text += 'Preview failed: ' + row['error']
        elif not ready: text += 'Waiting for this preview.'
        else: text += 'Apply changes only the pattern and supports Undo. '
        if row['origin'] == 'asset-preview': text += 'This is an asset texture preview, not a verified game pattern. Save a Studio project to preserve the selection. '
        elif row['origin'] == 'stored-material': text += 'This dinosaur has no recovered game pattern table; this is its stored material. '
        if self.profile.get('material_support') == 'experimental': text += 'This dinosaur uses an experimental material adapter. '
        self.info.set(text)

    def selected_doc(self):
        self.editor_changed()
        if self.dirty: raise ValueError('Wait for the updated pattern previews before applying or saving.')
        row = self.selected()
        if row is None or 'image' not in row: raise ValueError('Select a pattern with a successful preview first.')
        doc = copy.deepcopy(self.source); doc['pattern'] = row['index']
        return doc

    def apply(self):
        if not self.ready_for_action(): return
        try:
            doc = self.selected_doc(); self.editor.cancel_live_colors()
            self.editor.commit(doc, show_design=True)
        except ValueError as error: self.status.set(str(error))

    def save_project(self):
        if not self.ready_for_action(): return
        try:
            doc = self.selected_doc(); row = self.selected()
            path = filedialog.asksaveasfilename(parent=self.window, title='Save skin with this pattern', initialdir=output_dir(self.editor), defaultextension='.json', initialfile=export_filename(doc['name'] + ' - ' + row['label'] + ' project'), filetypes=[('Editable Studio project', '*.json')])
            if path:
                save_json(path, doc); self.status.set('Saved editable project with colors, model and pattern settings. Compact skin JSON does not store pattern selection.')
        except (ValueError, OSError) as error: messagebox.showerror('Project export failed', str(error), parent=self.window)

    def export_sheet(self):
        if not self.ready_for_action(): return
        if self.future is not None or not any('image' in r for r in self.rows):
            self.status.set('Wait for rendering to finish or cancel before saving a contact sheet.'); return
        path = filedialog.asksaveasfilename(parent=self.window, title='Save pattern contact sheet', initialdir=output_dir(self.editor), defaultextension='.png', initialfile='Pattern audition.png', filetypes=[('PNG image', '*.png')])
        if not path: return
        try:
            columns = min(3, len(self.rows)); width = max(1000, columns*420)
            sheet = Image.new('RGB', (width, 120 + math.ceil(len(self.rows)/columns)*315), '#101921'); draw = ImageDraw.Draw(sheet)
            try: font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 16)
            except OSError: font = ImageFont.load_default(size=16)
            def line(text, x, y, limit, color='white'):
                text = ' '.join(text.split())
                while draw.textlength(text, font=font) > limit: text = text[:-2]+'…'
                draw.text((x, y), text, font=font, fill=color)
            success = sum('image' in r for r in self.rows)
            line(self.source['name'] + ' / ' + self.context, 12, 12, width-24)
            line(f'{success}/{len(self.rows)} successful previews / Same colors and camera / {self.batch_size}px color bake', 12, 40, width-24)
            line('Light: ' + self.lighting_label + ' / Studio preview, not live-game validation. Asset textures labeled.', 12, 68, width-24, '#a7c8d9')
            for i, row in enumerate(self.rows):
                x=(i%columns)*420; y=110+(i//columns)*315
                line(row['label'], x+8, y, 400, '#9fe5e0')
                if 'image' in row: sheet.paste(row['image'].convert('RGB').resize((416,260),Image.Resampling.LANCZOS),(x,y+27))
                else: line('Preview failed' if 'error' in row else 'Not rendered (cancelled)',x+12,y+125,395)
                if row['origin'] != 'game-table': line('No verified game pattern index',x+8,y+288,400,'#a7c8d9')
            sheet.save(path); self.status.set('Saved contact sheet: ' + str(path))
        except OSError as error: messagebox.showerror('Image export failed', str(error), parent=self.window)

    def close(self):
        if self.closed: return
        self.closed = True; self.queue.clear(); self.rows.clear()
        if self.timer is not None: self.window.after_cancel(self.timer)
        if self.refresh_timer is not None: self.window.after_cancel(self.refresh_timer)
        if self.future is not None: self.future.cancel()
        self.window.destroy(); self.editor.pattern_audition = None
        if not self.editor.closed:
            self.editor.schedule_draw()
