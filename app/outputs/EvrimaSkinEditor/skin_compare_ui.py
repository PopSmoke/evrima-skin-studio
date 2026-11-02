"""Two custom skins, one model/camera/pose; optional small checkpoint files."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk
from skin_document import SLOTS, RAW_MODE, save_json
from skin_experiments import compare_images
from skin_checkpoints import LIMIT, MAX_BYTES, add, encode, decode, on_model
from morph_inspector import preview_camera
from skin_workflow_ui import output_dir


class SkinComparison:
    def __init__(self, editor):
        self.editor = editor; self.model = copy.deepcopy(editor.doc)
        self.camera_settings = (editor.yaw, editor.pitch, editor.zoom)
        self.lighting_label = editor.renderer.lighting_label
        self.closed = False; self.future = None; self.timer = None; self.generation = 0
        self.queue = []; self.images = {}; self.photos = {}; self.errors = {}; self.imported = None
        self.rendered_docs = {}; self.current_docs = {}; self.ready = False
        self.was_playing = editor.idle_playing.get()
        editor.idle_playing.set(False); editor.toggle_idle()
        self.window = tk.Toplevel(editor.root); self.window.title('Skin Studio — Compare skins and checkpoints')
        self.window.geometry('1160x850'); self.window.minsize(1100, 760)
        self.window.transient(editor.root); self.window.grab_set(); self.window.protocol('WM_DELETE_WINDOW', self.close)
        header = ttk.Frame(self.window, padding=12); header.pack(fill='x')
        ttk.Label(header, text='Compare skins', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        d = self.model
        self.context = f'{d["species"]} / Pattern {d["pattern"]+1} / {"Female" if d["female"] else "Male"} / Growth {d["growth"]:.0%} / {"Prime" if d["prime"] else "Standard"} / Variation {d["variation"]:g}'
        ttk.Label(header, text=self.context, wraplength=1100).pack(anchor='w')
        ttk.Label(header, text='Both skins use matching camera and pose. Light: ' + self.lighting_label + '. Checkpoints retain their own settings for Restore.', wraplength=1100).pack(anchor='w')
        controls = ttk.Frame(header); controls.pack(fill='x', pady=8)
        self.quality = tk.StringVar(value='512')
        ttk.Label(controls, text='Preview detail').pack(side='left')
        quality = ttk.Combobox(controls, textvariable=self.quality, values=['256', '512', '1024'], state='readonly', width=6); quality.pack(side='left', padx=8)
        quality.bind('<<ComboboxSelected>>', self.request)
        ttk.Button(controls, text='Import skin into B…', command=self.import_b).pack(side='left')
        ttk.Button(controls, text='Swap A / B', command=self.swap).pack(side='left', padx=8)
        self.export_button = ttk.Button(controls, text='Save comparison PNG…', command=self.export_image, state='disabled'); self.export_button.pack(side='right')
        pair = ttk.Frame(self.window, padding=(12, 0)); pair.pack(fill='x')
        self.selectors = {}; self.selection = {}; self.pictures = {}; self.labels = {}
        for i, side in enumerate(('A', 'B')):
            frame = ttk.Frame(pair); frame.grid(row=0, column=i, sticky='nsew', padx=(0, 12) if i == 0 else (0, 0)); pair.columnconfigure(i, weight=1)
            ttk.Label(frame, text=side, font=('Segoe UI', 14, 'bold')).pack(anchor='w')
            self.selection[side] = tk.StringVar()
            self.selectors[side] = ttk.Combobox(frame, textvariable=self.selection[side], state='readonly'); self.selectors[side].pack(fill='x')
            self.selectors[side].bind('<<ComboboxSelected>>', self.request)
            self.pictures[side] = ttk.Label(frame); self.pictures[side].pack(pady=6)
            self.labels[side] = ttk.Label(frame, wraplength=520); self.labels[side].pack(anchor='w')
        self.details = tk.Text(self.window, height=5, wrap='word', state='disabled'); self.details.pack(fill='both', expand=True, padx=12, pady=8)
        checkpoints = ttk.LabelFrame(self.window, text=f'Checkpoints — up to {LIMIT} designs, no stored pictures', padding=10); checkpoints.pack(fill='x', padx=12)
        self.name = tk.StringVar(value=self.model['name'][:80])
        row = ttk.Frame(checkpoints); row.pack(fill='x')
        ttk.Label(row, text='Name').pack(side='left'); ttk.Entry(row, textvariable=self.name, width=30).pack(side='left', padx=6)
        ttk.Button(row, text='Keep B as checkpoint', command=self.keep_b).pack(side='left', padx=4)
        self.remove_button = ttk.Button(row, text='Remove selected B checkpoint', command=self.remove_b); self.remove_button.pack(side='left', padx=4)
        self.save_button = ttk.Button(row, text='Save set…', command=self.save_set); self.save_button.pack(side='right')
        ttk.Button(row, text='Load set…', command=self.load_set).pack(side='right', padx=6)
        ttk.Label(checkpoints, text='Checkpoints stay in this Studio session. Save a set to keep them after closing Studio; Load set merges by unique name.', wraplength=1090).pack(anchor='w', pady=(6, 0))
        footer = ttk.Frame(self.window, padding=12); footer.pack(fill='x')
        self.apply_button = ttk.Button(footer, text='Apply B colors to current model', command=self.apply_colors); self.apply_button.pack(side='left')
        ttk.Button(footer, text='Restore B with its model settings', command=self.restore_b).pack(side='left', padx=8)
        ttk.Button(footer, text='Close', command=self.close).pack(side='right')
        self.status = tk.StringVar(value='Loading comparison…')
        ttk.Label(self.window, textvariable=self.status, wraplength=1100, padding=(12, 0, 12, 10)).pack(fill='x')
        self.refresh_choices()
        if editor.checkpoints: self.selection['A'].set('Checkpoint: ' + editor.checkpoints[-1]['name'])
        self.request()

    def refresh_choices(self):
        self.choices = {'Current design': self.model}
        for row in self.editor.checkpoints: self.choices['Checkpoint: ' + row['name']] = row['document']
        if self.imported is not None: self.choices['Imported skin: ' + self.imported['name']] = self.imported
        for side in ('A', 'B'):
            self.selectors[side].configure(values=list(self.choices))
            if self.selection[side].get() not in self.choices: self.selection[side].set('Current design')

    def source(self, side):
        return copy.deepcopy(self.choices[self.selection[side].get()])

    def set_details(self, value):
        self.details.configure(state='normal'); self.details.delete('1.0', 'end'); self.details.insert('1.0', value); self.details.configure(state='disabled')

    def request(self, *_):
        if self.closed: return
        self.generation += 1; self.ready = False
        self.images.clear(); self.photos.clear(); self.errors.clear(); self.rendered_docs.clear()
        self.export_button.configure(state='disabled')
        for side in ('A', 'B'):
            self.pictures[side].configure(image=''); self.labels[side].configure(text='Updating…')
        self.set_details('Preparing matched previews…')
        self.current_docs = {s: on_model(self.source(s), self.model) for s in ('A', 'B')}
        self.queue = [(s, self.current_docs[s]) for s in ('A', 'B')]
        self.batch_size = int(self.quality.get())
        if self.batch_size not in (256, 512, 1024): raise ValueError('Unsupported comparison quality.')
        if self.future is None: self.next_job()
        else: self.future.cancel()

    def next_job(self):
        if self.closed: return
        if not self.queue:
            self.finish(); return
        side, doc = self.queue.pop(0); self.job = (self.generation, side, doc)
        assets = self.editor.assets; size = self.batch_size
        def bake():
            material = assets.material(doc, size); shape = assets.shape(doc)
            return assets.mesh, material, shape
        self.status.set('Preparing ' + side + '… You can change selections; outdated results are discarded.')
        self.future = self.editor.pool.submit(bake); self.timer = self.window.after(40, self.poll)

    def poll(self):
        self.timer = None
        if self.closed: return
        if not self.future.done():
            self.timer = self.window.after(40, self.poll); return
        future, self.future = self.future, None
        generation, side, doc = self.job
        if generation != self.generation:
            self.next_job(); return
        try:
            mesh, material, shape = future.result()
            yaw, pitch, zoom = self.camera_settings
            camera = preview_camera(shape['camera_standard'], shape['camera_prime'], yaw, pitch, 520, 325, zoom)
            image = self.editor.renderer.draw(mesh, [], camera, 520, 325, models=[(material, shape['points'])])
            if self.editor.renderer._surface_error: raise ValueError(str(self.editor.renderer._surface_error))
            self.images[side] = image; self.photos[side] = ImageTk.PhotoImage(image)
            self.pictures[side].configure(image=self.photos[side]); self.labels[side].configure(text=doc['name'])
            self.rendered_docs[side] = copy.deepcopy(doc)
        except Exception as error:
            self.errors[side] = str(error); self.labels[side].configure(text='Preview unavailable: ' + str(error))
        self.next_job()

    def finish(self):
        if self.closed: return
        self.ready = len(self.images) == 2 and not self.errors
        self.export_button.configure(state='normal' if self.ready else 'disabled')
        lines = []
        if self.ready:
            metrics = compare_images(self.images['B'], self.images['A'], [])
            self.metrics = metrics
            lines.append(f'B vs A: {metrics["changed_percent"]:.1f}% of visible model pixels change by more than 8/255 in any channel.')
            if self.images['A'].tobytes() == self.images['B'].tobytes():
                lines.append('The rendered pictures are identical. Different raw numbers may still clip to the same appearance.')
        else: lines += [s + ': ' + e for s, e in self.errors.items()]
        defaults = self.editor.assets.defaults(self.model['species'])
        for slot in SLOTS:
            a, b = [defaults[slot] if slot == 'e' and self.current_docs[s]['default_eyes'] else self.current_docs[s]['colors'][slot] for s in ('A', 'B')]
            if a != b:
                lines.append(slot + ': A (' + ', '.join(f'{v:g}' for v in a) + ') → B (' + ', '.join(f'{v:g}' for v in b) + ')')
        lines.append('Decoded preview with approximate studio lighting; not live-game validation or proof of emitted light.')
        self.set_details('\n'.join(lines))
        self.status.set('Comparison ready. Apply changes supports Undo.' if self.ready else 'Some previews failed. Raw checkpoint values are retained; comparison image export is disabled.')

    def swap(self):
        a, b = [self.selection[s].get() for s in ('A', 'B')]
        self.selection['A'].set(b); self.selection['B'].set(a); self.request()

    def keep_b(self):
        try:
            self.editor.checkpoints = add(self.editor.checkpoints, self.name.get(), self.source('B'))
            label = 'Checkpoint: ' + self.editor.checkpoints[-1]['name']
            self.refresh_choices(); self.selection['B'].set(label); self.request()
        except ValueError as error: self.status.set(str(error))

    def remove_b(self):
        label = self.selection['B'].get()
        row = next((r for r in self.editor.checkpoints if label == 'Checkpoint: ' + r['name']), None)
        if row is None:
            self.status.set('Choose a saved checkpoint in B to remove it.'); return
        self.editor.checkpoints = [r for r in self.editor.checkpoints if r['id'] != row['id']]
        self.refresh_choices(); self.request()

    def save_set(self):
        try:
            payload = encode(self.editor.checkpoints)
            path = filedialog.asksaveasfilename(parent=self.window, title='Save editable checkpoints', initialdir=output_dir(self.editor), defaultextension='.json', initialfile='Skin checkpoints.json', filetypes=[('Checkpoint set', '*.json')])
            if path: save_json(path, payload); self.status.set('Saved checkpoints with exact colors and model settings: ' + Path(path).name)
        except (ValueError, OSError) as error: messagebox.showerror('Could not save checkpoints', str(error), parent=self.window)

    def load_set(self):
        path = filedialog.askopenfilename(parent=self.window, title='Load checkpoint set', filetypes=[('Checkpoint set', '*.json')])
        if not path: return
        try:
            if Path(path).stat().st_size > MAX_BYTES: raise ValueError('Checkpoint set exceeds 2 MB.')
            incoming = decode(Path(path).read_text(encoding='utf-8-sig'))
            merged = copy.deepcopy(self.editor.checkpoints)
            for row in incoming:
                self.editor.assets.validate_document(row['document'])
                same = next((r for r in merged if r['name'].casefold() == row['name'].casefold()), None)
                if same is not None:
                    if same['document'] == row['document']: continue
                    raise ValueError('A different checkpoint already uses the name "' + row['name'] + '". No checkpoints were replaced.')
                # Reassign IDs during merge so imported IDs cannot collide with existing rows.
                merged = add(merged, row['name'], row['document'])
            self.editor.checkpoints = merged; self.refresh_choices(); self.request()
        except (ValueError, OSError, KeyError, TypeError) as error: messagebox.showerror('Could not load checkpoints', str(error), parent=self.window)

    def import_b(self):
        path = filedialog.askopenfilename(parent=self.window, title='Compare a skin or project in B', filetypes=[('Skin JSON', '*.json')])
        if not path: return
        try:
            if Path(path).stat().st_size > 1024 * 1024: raise ValueError('Skin file exceeds 1 MB.')
            self.imported = self.editor.assets.import_document(Path(path).read_text(encoding='utf-8-sig'), self.model)
            self.refresh_choices(); self.selection['B'].set('Imported skin: ' + self.imported['name']); self.name.set(self.imported['name'][:80]); self.request()
        except (ValueError, OSError, KeyError, TypeError) as error: messagebox.showerror('Could not import comparison', str(error), parent=self.window)

    def apply_document(self, doc):
        try:
            self.editor.assets.validate_document(doc)
            self.editor.cancel_live_colors(); self.editor.mode.set(RAW_MODE)
            self.editor.commit(doc, show_design=True); self.editor.refresh_colors(); self.close()
        except ValueError as error: self.status.set(str(error))

    def apply_colors(self):
        self.apply_document(on_model(self.source('B'), self.model))

    def restore_b(self):
        self.apply_document(self.source('B'))

    def export_image(self):
        if not self.ready:
            self.status.set('Wait for both current previews before exporting.'); return
        path = filedialog.asksaveasfilename(parent=self.window, title='Save matched comparison', initialdir=output_dir(self.editor), defaultextension='.png', initialfile='Skin comparison.png', filetypes=[('PNG image', '*.png')])
        if not path: return
        try:
            image = Image.new('RGB', (1080, 465), '#101921'); draw = ImageDraw.Draw(image)
            try: font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 16)
            except OSError: font = ImageFont.load_default(size=16)
            draw.text((15, 10), self.context, font=font, fill='white')
            for side, x in [('A', 15), ('B', 545)]:
                name = side + ' / ' + ' '.join(self.rendered_docs[side]['name'].split())
                while draw.textlength(name, font=font) > 510: name = name[:-2] + '…'
                draw.text((x, 45), name, font=font, fill='#9fe5e0'); image.paste(self.images[side].convert('RGB'), (x, 80))
            draw.text((15, 417), f'Matched camera, light and reference pose / {self.batch_size}px color bake / Changed pixels: {self.metrics["changed_percent"]:.1f}%', font=font, fill='white')
            draw.text((15, 442), 'Light: ' + self.lighting_label + ' / Studio preview; live-game appearance is unverified.', font=font, fill='#a8bbcf')
            image.save(path); self.status.set('Saved current A/B comparison: ' + Path(path).name)
        except OSError as error: messagebox.showerror('Image export failed', str(error), parent=self.window)

    def close(self):
        if self.closed: return
        self.closed = True; self.queue.clear(); self.images.clear(); self.photos.clear()
        if self.timer is not None: self.window.after_cancel(self.timer)
        if self.future is not None: self.future.cancel()
        self.window.grab_release(); self.window.destroy(); self.editor.skin_comparison = None
        if not self.editor.closed:
            self.editor.idle_playing.set(self.was_playing); self.editor.toggle_idle(); self.editor.schedule_draw()
