"""On-demand Experiment Lab, using the editor's existing worker and renderer."""
import copy
from datetime import datetime
from pathlib import Path
import random
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from PIL import ImageTk
from skin_document import SLOTS, RAW_MODE, export_skin, export_filename, save_json, importer_range_notes
from skin_experiments import DEFAULT_SWEEP, MAX_RESULTS, STYLES, SWEEP_MODES, shader_sections, linked_sweep, paired_sweep, default_locks, prepare_source, parse_sweep, sweep, variations, compare_images
from morph_inspector import preview_camera
from skin_lab_workflow import LabWorkflow
from skin_workflow import refine_sweep
from skin_workflow_ui import output_dir
from skin_discovery import candidates,score_row
from skin_discovery_ui import DiscoveryUI


class ExperimentLab(LabWorkflow,DiscoveryUI):
    def __init__(self, editor):
        self.editor = editor
        self.lighting_label = editor.renderer.lighting_label
        self.source = prepare_source(editor.doc, editor.assets.defaults(editor.doc['species']))
        self.closed = False; self.future = None; self.timer = None; self.stopping = False
        self.queue = []; self.rows = []; self.baseline = None; self.photo = None
        self.was_playing = editor.idle_playing.get()
        editor.idle_playing.set(False); editor.toggle_idle()
        self.window = tk.Toplevel(editor.root)
        self.window.title('Skin Studio — Experiment Lab')
        self.window.geometry('1240x850'); self.window.minsize(1160, 800)
        self.window.transient(editor.root); self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        header = ttk.Frame(self.window, padding=12); header.pack(fill='x')
        ttk.Label(header, text='Experiment Lab', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        d = self.source
        self.source_label=ttk.Label(header,text=self.source_summary(),wraplength=1180)
        self.source_label.pack(anchor='w')
        ttk.Label(header, text='Light: ' + self.lighting_label + '. Works from this snapshot; Apply changes your design and supports Undo.').pack(anchor='w')
        area = ttk.Frame(self.window, padding=(12, 0)); area.pack(fill='both', expand=True)
        sidebar = ttk.Frame(area, width=370); sidebar.pack(side='left', fill='y', padx=(0, 12)); sidebar.pack_propagate(False)
        controls = ttk.Frame(sidebar); controls.pack(side='bottom', fill='x')
        scroll_area = ttk.Frame(sidebar); scroll_area.pack(fill='both', expand=True)
        canvas = tk.Canvas(scroll_area, width=350, highlightthickness=0); canvas.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(scroll_area, orient='vertical', command=canvas.yview); scroll.pack(side='right', fill='y'); canvas.configure(yscrollcommand=scroll.set)
        left = ttk.Frame(canvas); pane = canvas.create_window((0, 0), window=left, anchor='nw')
        left.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(pane, width=e.width))
        def scroll_controls(event):
            if str(event.widget).startswith(str(left)) or event.widget is canvas:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        self.window.bind('<MouseWheel>', scroll_controls, add='+')
        saved_locks = getattr(editor, 'experiment_locks', default_locks())
        self.locks = {s: [tk.BooleanVar(value=v) for v in saved_locks[s]] for s in SLOTS}
        lockbox = ttk.LabelFrame(left, text='Lock channels during experiments', padding=8); lockbox.pack(fill='x')
        for col, title in enumerate(('Section', 'All', 'X / R', 'Y / G', 'Z / B')):
            ttk.Label(lockbox, text=title).grid(row=0, column=col, padx=5)
        self.section_locks = {}
        for row, (s, (label, _, _)) in enumerate(SLOTS.items(), 1):
            ttk.Label(lockbox, text=f'{label} ({s})').grid(row=row, column=0, sticky='w')
            var = tk.BooleanVar(value=all(saved_locks[s])); self.section_locks[s] = var
            ttk.Checkbutton(lockbox, variable=var, command=lambda s=s: self.lock_section(s)).grid(row=row, column=1)
            for c in range(3):
                ttk.Checkbutton(lockbox, variable=self.locks[s][c], command=lambda s=s: self.sync_lock(s)).grid(row=row, column=c+2)
        ttk.Label(lockbox, text='Checked = keep unchanged. Alpha is always preserved.\nLocks apply to this lab and stay set until Studio closes.', wraplength=330).grid(row=8, column=0, columnspan=5, sticky='w', pady=6)
        lockbuttons = ttk.Frame(lockbox); lockbuttons.grid(row=9, column=0, columnspan=5)
        ttk.Button(lockbuttons, text='Lock all', command=lambda: self.set_locks(True)).pack(side='left', padx=4)
        ttk.Button(lockbuttons, text='Unlock body', command=lambda: self.set_locks(False, body=True)).pack(side='left', padx=4)
        self.tabs = ttk.Notebook(left); self.tabs.pack(fill='x', pady=10)
        sweep_tab = ttk.Frame(self.tabs, padding=10); self.tabs.add(sweep_tab, text='Value sweep')
        self.section = tk.StringVar(value='b'); self.channel = tk.StringVar(value='Unlocked RGB')
        self.sweep_mode = tk.StringVar(value=SWEEP_MODES[0])
        self.combo(sweep_tab, 'Sweep mode', self.sweep_mode, SWEEP_MODES)
        self.combo(sweep_tab, 'Section', self.section, list(SLOTS))
        self.combo(sweep_tab, 'Channels', self.channel, ['Unlocked RGB', 'X / R', 'Y / G', 'Z / B'])
        ttk.Label(sweep_tab, text='Values, separated by commas (up to 24)').pack(anchor='w')
        self.values = tk.Text(sweep_tab, height=4, width=35, wrap='word'); self.values.pack(fill='x'); self.values.insert('1.0', DEFAULT_SWEEP)
        self.group_note = tk.StringVar()
        self.group_label=ttk.Label(sweep_tab, textvariable=self.group_note, wraplength=305)
        self.group_label.pack(anchor='w',pady=6)
        self.custom_box=ttk.LabelFrame(sweep_tab,text='Sections to sweep together',padding=6)
        self.selected_sections={s:tk.BooleanVar(value=s in ('b','f')) for s in SLOTS}
        self.section_buttons={}
        for i,(s,(label,*_)) in enumerate(SLOTS.items()):
            button=ttk.Checkbutton(self.custom_box,text=f'{label} ({s})',variable=self.selected_sections[s])
            button.grid(row=i//2,column=i%2,sticky='w');self.section_buttons[s]=button
        self.pair_box=ttk.LabelFrame(sweep_tab,text='Companion section',padding=6)
        self.companion=tk.StringVar(value='f');self.companion_channel=tk.StringVar(value='Unlocked RGB')
        self.companion_box=self.combo(self.pair_box,'Second section',self.companion,['md','m','f','u','d'])
        self.combo(self.pair_box,'Second section channels',self.companion_channel,['Unlocked RGB','X / R','Y / G','Z / B'])
        ttk.Label(self.pair_box,text='Second values (every A × B combination)',wraplength=285).pack(anchor='w')
        self.companion_values=tk.Text(self.pair_box,height=3,width=30,wrap='word');self.companion_values.pack(fill='x')
        self.companion_values.insert('1.0','0.004, 0.35, 1, 8')
        ttk.Label(self.pair_box,text='Use one value in either list to hold that section fixed. Maximum 24 combinations.',wraplength=285).pack(anchor='w',pady=5)
        presets=ttk.LabelFrame(sweep_tab,text='Negative interaction starting points',padding=6);presets.pack(fill='x',pady=5)
        self.pair_preset=tk.StringVar(value='Body / flank')
        self.combo(presets,'Pair',self.pair_preset,['Body / flank','Body / underbelly','Markings / flank'])
        ttk.Button(presets,text='Set up negative pair',command=self.use_pair_preset).pack(fill='x')
        ttk.Label(presets,text='Holds the first slot at -9999999; sweeps the second. Does not change locks or your skin.',wraplength=285).pack(anchor='w',pady=4)
        self.sweep_mode.trace_add('write',self.update_sweep_controls)
        self.section.trace_add('write',self.update_sweep_controls)
        self.update_sweep_controls()
        var_tab = ttk.Frame(self.tabs, padding=10); self.tabs.add(var_tab, text='Variations')
        self.style = tk.StringVar(value=STYLES[1]); self.scope = tk.StringVar(value='2–3 sections')
        self.combo(var_tab, 'Style', self.style, STYLES)
        self.combo(var_tab, 'Change', self.scope, ['One section', '2–3 sections', 'All unlocked'])
        self.count = tk.StringVar(value='12'); self.seed = tk.StringVar(value='2026')
        self.minimum = tk.StringVar(value='6'); self.maximum = tk.StringVar(value='22'); self.amount = tk.StringVar(value='25')
        for label, var in [('Results (1–24)', self.count), ('Seed (repeatable)', self.seed), ('Minimum power of 10', self.minimum), ('Maximum power of 10', self.maximum), ('Subtle change (%)', self.amount)]:
            row = ttk.Frame(var_tab); row.pack(fill='x', pady=2)
            ttk.Label(row, text=label).pack(side='left'); ttk.Entry(row, textvariable=var, width=11).pack(side='right')
        ttk.Label(var_tab, text='Powers 6–22 mean magnitudes 1e6–1e22.\nSubtle mode uses Change %; the other styles use powers.', wraplength=325).pack(anchor='w', pady=4)
        ttk.Button(var_tab, text='New random seed', command=lambda: self.seed.set(str(random.SystemRandom().randrange(10**9)))).pack(anchor='w')
        self.quality = tk.StringVar(value='256')
        self.combo(controls, 'Preview detail (color bake)', self.quality, ['256', '512'])
        buttons = ttk.Frame(controls); buttons.pack(fill='x', pady=8)
        self.run_button = ttk.Button(buttons, text='Run experiments', command=self.run); self.run_button.pack(side='left')
        self.cancel_button = ttk.Button(buttons, text='Cancel', command=self.cancel, state='disabled'); self.cancel_button.pack(side='left', padx=6)
        self.clear_button = ttk.Button(buttons, text='Clear', command=self.clear); self.clear_button.pack(side='left')
        right = ttk.Frame(area); right.pack(side='left', fill='both', expand=True)
        listing = ttk.Frame(right); listing.pack(side='left', fill='y', padx=(0, 10))
        self.listing = tk.Listbox(listing, width=25, exportselection=False); self.listing.pack(side='left', fill='y')
        scrollbar = ttk.Scrollbar(listing, command=self.listing.yview); scrollbar.pack(side='left', fill='y'); self.listing.configure(yscrollcommand=scrollbar.set)
        self.listing.bind('<<ListboxSelect>>', self.show)
        panel = ttk.Frame(right); panel.pack(side='left', fill='both', expand=True)
        self.title = ttk.Label(panel, text='Run a sweep or generate variations', font=('Segoe UI', 13, 'bold'), wraplength=510); self.title.pack(anchor='w')
        self.picture = ttk.Label(panel); self.picture.pack(pady=8)
        self.details = tk.Text(panel, height=14, width=60, wrap='word', state='disabled'); self.details.pack(fill='both', expand=True)
        result_controls=ttk.Frame(panel)
        result_controls.pack(side='bottom',fill='x',before=self.details)
        self.name = tk.StringVar()
        self.name.trace_add('write', self.remember_name)
        ttk.Label(result_controls, text='Selected design name (used for export)').pack(anchor='w', pady=(6, 0))
        ttk.Entry(result_controls, textvariable=self.name).pack(fill='x')
        actions = ttk.Frame(result_controls); actions.pack(fill='x', pady=8)
        self.apply_button = ttk.Button(actions, text='Apply selected', command=self.apply, state='disabled'); self.apply_button.pack(side='left')
        self.export_button = ttk.Button(actions, text='Export selected JSON', command=self.export_selected, state='disabled'); self.export_button.pack(side='left', padx=5)
        self.export_all_button = ttk.Button(result_controls, text='Export all result JSONs…', command=self.export_all, state='disabled'); self.export_all_button.pack(anchor='w')
        footer = ttk.Frame(self.window, padding=12); footer.pack(side='bottom',fill='x',before=area)
        self.status = tk.StringVar(value='No extra assets or disk cache. Eyes start locked. Preview results are not live-game validation.')
        ttk.Label(footer, textvariable=self.status, wraplength=1160).pack(anchor='w')
        self.setup_workflow(controls,result_controls)
        self.setup_discovery()

    @staticmethod
    def combo(parent, label, variable, values):
        ttk.Label(parent, text=label).pack(anchor='w')
        box=ttk.Combobox(parent, textvariable=variable, values=values, state='readonly')
        box.pack(fill='x', pady=(0, 5))
        return box

    def update_sweep_controls(self,*_):
        group=shader_sections(self.section.get())
        self.group_note.set('Body sections can affect one another. Results vary with the dinosaur and pattern. Locked colors stay unchanged.' if self.section.get()!='e' else 'Eyes are tested separately. Unlock their colors to try variations.')
        for s,button in self.section_buttons.items():button.configure(state='normal' if s in group else 'disabled')
        companions=[s for s in group if s!=self.section.get()]
        self.companion_box.configure(values=companions)
        if self.companion.get() not in companions:self.companion.set(companions[0] if companions else '')
        self.custom_box.pack_forget();self.pair_box.pack_forget()
        # Keep pair/custom controls directly below the shared-shader explanation.
        if self.sweep_mode.get()==SWEEP_MODES[2]:self.custom_box.pack(fill='x',pady=5,after=self.group_label)
        if self.sweep_mode.get()==SWEEP_MODES[3]:self.pair_box.pack(fill='x',pady=5,after=self.group_label)

    def use_pair_preset(self):
        pairs={'Body / flank':('b','f'),'Body / underbelly':('b','u'),'Markings / flank':('m','f')}
        a,b=pairs[self.pair_preset.get()]
        self.section.set(a);self.sweep_mode.set(SWEEP_MODES[3]);self.companion.set(b)
        self.channel.set('Unlocked RGB');self.companion_channel.set('Unlocked RGB')
        self.values.delete('1.0','end');self.values.insert('1.0','-9999999')
        self.companion_values.delete('1.0','end');self.companion_values.insert('1.0','0.004, 0.35, 1, 8, 16')

    @staticmethod
    def sweep_channels(value):
        return [0,1,2] if value=='Unlocked RGB' else [['X / R','Y / G','Z / B'].index(value)]

    def lock_values(self):
        return {s: [v.get() for v in row] for s, row in self.locks.items()}

    def sync_lock(self, s):
        self.section_locks[s].set(all(v.get() for v in self.locks[s]))
        self.editor.experiment_locks = self.lock_values()

    def lock_section(self, s):
        for v in self.locks[s]: v.set(self.section_locks[s].get())
        self.sync_lock(s)

    def set_locks(self, locked, body=False):
        for s in SLOTS:
            if body and s == 'e': continue
            for v in self.locks[s]: v.set(locked)
            self.sync_lock(s)

    def clear(self):
        if self.future is not None: return
        self.discovery_batch={};self.discovery_meta={};self.discovery_locks={}
        self.rows.clear(); self.queue.clear(); self.baseline = self.photo = None
        self.listing.delete(0, 'end'); self.picture.configure(image=''); self.name.set('')
        self.title.configure(text='Run a sweep or generate variations')
        self.set_details(''); self.actions(False)
        self.status.set('Results cleared from memory. No preview files were stored.')

    def actions(self, selected):
        for button in (self.apply_button, self.export_button): button.configure(state='normal' if selected else 'disabled')
        self.export_all_button.configure(state='normal' if any(not r.get('baseline') for r in self.rows) else 'disabled')

    def run(self):
        if self.future is not None: return
        try:
            discovery_options={};discovery_meta={}
            if self.tabs.index(self.tabs.select()) == 0:
                channels=self.sweep_channels(self.channel.get());values=parse_sweep(self.values.get('1.0','end').strip())
                mode=self.sweep_mode.get();section=self.section.get()
                if mode==SWEEP_MODES[0]:jobs=sweep(self.source,self.lock_values(),section,channels,values)
                elif mode in (SWEEP_MODES[1],SWEEP_MODES[2]):
                    sections=list(shader_sections(section)) if mode==SWEEP_MODES[1] else [s for s in shader_sections(section) if self.selected_sections[s].get()]
                    jobs=linked_sweep(self.source,self.lock_values(),sections,channels,values)
                elif mode==SWEEP_MODES[3]:jobs=paired_sweep(self.source,self.lock_values(),section,channels,values,self.companion.get(),self.sweep_channels(self.companion_channel.get()),parse_sweep(self.companion_values.get('1.0','end').strip()))
                else:raise ValueError('Choose a listed sweep mode.')
                description='Value sweep / '+mode
            elif self.tabs.index(self.tabs.select()) == 1:
                jobs = variations(self.source, self.lock_values(), count=int(self.count.get()), seed=int(self.seed.get()), style=self.style.get(), minimum=int(self.minimum.get()), maximum=int(self.maximum.get()), amount=float(self.amount.get()), scope=self.scope.get())
                description='Variations / '+self.style.get()
            elif self.tabs.index(self.tabs.select()) == 2:
                jobs=refine_sweep(self.source,self.lock_values(),self.refine_section.get(),self.sweep_channels(self.refine_channel.get()),float(self.refine_percent.get()),int(self.refine_count.get()),float(self.refine_zero.get()))
                description='Refinement / '+self.refine_percent.get()+'%'
            else:
                discovery_options=self.discovery_options();jobs,discovery_meta=candidates(self.source,self.lock_values(),discovery_options)
                description='Discovery / '+discovery_options['method']
            size = int(self.quality.get())
            if size not in (256, 512): raise ValueError('Choose 256 or 512 preview detail.')
        except (ValueError, KeyError) as error:
            self.status.set(str(error)); return
        self.clear(); self.stopping = False; self.batch_size = size
        self.discovery_batch=discovery_options;self.discovery_meta=discovery_meta
        self.discovery_locks=self.lock_values() if discovery_options else {}
        self.batch_description=description
        self.queue = [('Baseline', copy.deepcopy(self.source))] + jobs
        self.total = len(jobs)
        self.run_button.configure(state='disabled'); self.clear_button.configure(state='disabled'); self.cancel_button.configure(state='normal')
        self.next_job()

    def next_job(self):
        if self.closed: return
        if self.stopping or not self.queue:
            self.queue.clear(); self.run_button.configure(state='normal'); self.clear_button.configure(state='normal'); self.cancel_button.configure(state='disabled')
            done = sum(not r.get('baseline') for r in self.rows)
            self.status.set(('Stopped. ' if self.stopping else 'Finished. ') + f'{done} results kept in memory. Select one to inspect, apply or export.')
            return
        label, doc = self.queue.pop(0)
        self.job = dict(label=label, doc=doc, baseline=label == 'Baseline')
        self.job.update(self.discovery_meta.get(label,{}))
        self.status.set(f'Preparing {label}… {max(0, len(self.rows)-1)}/{self.total} results. Locks and settings are captured when you press Run.')
        assets = self.editor.assets; size = self.batch_size
        def bake():
            material = assets.material(doc, size); shape = assets.shape(doc)
            return assets.mesh, material, shape
        # Reuse the existing one-worker pool: no parallel bakes, duplicated asset cache or runtime.
        self.future = self.editor.pool.submit(bake)
        self.timer = self.window.after(40, self.poll)

    def poll(self):
        self.timer = None
        if self.closed: return
        if not self.future.done():
            self.timer = self.window.after(40, self.poll); return
        future, self.future = self.future, None
        if self.stopping:
            self.next_job(); return
        row = self.job
        try:
            mesh, material, shape = future.result()
            camera = preview_camera(shape['camera_standard'], shape['camera_prime'], -65., 12., 520, 325)
            im = self.editor.renderer.draw(mesh, [], camera, 520, 325, models=[(material, shape['points'])])
            if self.editor.renderer._surface_error: raise ValueError(str(self.editor.renderer._surface_error))
            row['image'] = im
            if row['baseline']: self.baseline = im
            if self.baseline is not None:
                prior = [(r['label'], r['metrics']['digest']) for r in self.rows if 'metrics' in r]
                row['metrics'] = compare_images(im, self.baseline, prior)
                if self.discovery_batch:score_row(row,self.rows,self.baseline)
        except Exception as error:
            row['error'] = str(error)
        self.rows.append(row)
        suffix = ' — unavailable' if 'error' in row else ' — same pixels' if row.get('metrics', {}).get('same_as') else ''
        self.listing.insert('end', row['label'] + suffix)
        if len(self.rows) <= 2:
            self.listing.selection_clear(0, 'end'); self.listing.selection_set(len(self.rows)-1); self.show()
        self.actions(bool(self.listing.curselection()))
        self.next_job()

    def cancel(self):
        self.stopping = True; self.queue.clear()
        self.status.set('Stopping after the current bake. Completed results will remain available.')
        if self.future is not None: self.future.cancel()

    def selected(self):
        indices = self.listing.curselection()
        return self.rows[indices[0]] if indices else None

    def set_details(self, text):
        self.details.configure(state='normal'); self.details.delete('1.0', 'end'); self.details.insert('1.0', text); self.details.configure(state='disabled')

    def show(self, *_):
        row = self.selected()
        if row is None: return
        self.title.configure(text=row['label']); self.name.set(row['doc']['name'])
        self.favorite_button.configure(text='★ Favorited' if row.get('favorite') else '☆ Favorite')
        if 'image' in row:
            self.photo = ImageTk.PhotoImage(row['image']); self.picture.configure(image=self.photo)
        else:
            self.photo = None; self.picture.configure(image='')
        lines = ['Reference pose • fixed camera • ' + str(self.batch_size) + ' px color bake.']
        lines.append(self.batch_description)
        lines.append('Experiment: '+row['label'])
        if 'error' in row: lines += ['Preview unavailable: ' + row['error'], 'Raw values are retained and can still be exported.']
        elif 'metrics' in row:
            m = row['metrics']; lines.append(f'Changed vs baseline: {m["changed_percent"]:.1f}% of visible model pixels (>8/255 in any channel).')
            if m['same_as']: lines.append('Identical picture to: ' + m['same_as'] + '. Different inputs can clip to the same appearance.')
        else: lines.append('Baseline preview unavailable; no comparison percentage is reported.')
        lines += importer_range_notes(row['doc']['colors'])
        lines += self.discovery_lines(row)
        lines += ['Decoded preview only; not proof of in-game glow.', '', 'Exact raw RGBA:']
        lines += [s + ': ' + ', '.join(repr(v) for v in row['doc']['colors'][s]) for s in SLOTS]
        self.set_details('\n'.join(lines)); self.actions(True)

    def selected_doc(self):
        row = self.selected()
        if row is None: raise ValueError('Select a result first.')
        name = self.name.get().strip()
        if not name: raise ValueError('Give this result a design name.')
        row['doc']['name'] = name
        return copy.deepcopy(row['doc'])

    def remember_name(self, *_):
        row = self.selected()
        if row is not None and self.name.get().strip():
            row['doc']['name'] = self.name.get().strip()

    def apply(self):
        try:
            doc = self.selected_doc()
            self.editor.cancel_live_colors(); self.editor.mode.set(RAW_MODE)
            self.editor.commit(doc, show_design=True); self.editor.refresh_colors()
            self.close()
        except ValueError as error: self.status.set(str(error))

    def export_selected(self):
        try:
            doc = self.selected_doc()
            path = filedialog.asksaveasfilename(parent=self.window, title='Export experiment JSON', initialdir=output_dir(self.editor), initialfile=export_filename(doc['name']), defaultextension='.json', filetypes=[('Skin JSON', '*.json')])
            if path:
                save_json(path, export_skin(doc, self.editor.assets.defaults(doc['species'])))
                self.status.set('Exported ' + Path(path).name + '. Compact JSON carries colors; save a Studio project to retain model settings.')
        except (ValueError, OSError) as error: messagebox.showerror('Export failed', str(error), parent=self.window)

    def export_all(self, favorites_only=False):
        if self.selected() is not None:
            try: self.selected_doc()
            except ValueError as error: self.status.set(str(error)); return
        rows = [r for r in self.rows if not r.get('baseline') and (not favorites_only or r.get('favorite'))]
        if not rows:
            self.status.set('No matching results. Mark favorites first.');return
        parent = filedialog.askdirectory(parent=self.window, title='Choose where to create a new experiment folder', initialdir=output_dir(self.editor))
        if not parent: return
        folder = None
        try:
            stem = 'Skin experiments ' + datetime.now().strftime('%Y%m%d-%H%M%S')
            for index in range(1000):
                folder = Path(parent) / (stem + (f'-{index+1}' if index else ''))
                try: folder.mkdir(); break
                except FileExistsError: continue
            else: raise OSError('Could not create a fresh export folder.')
            used = set(); assignments=[]
            for row in rows:
                doc = copy.deepcopy(row['doc']); name = export_filename(doc['name']); index = 2
                while name.casefold() in used:
                    doc['name'] = row['doc']['name'] + f' {index}'; name = export_filename(doc['name']); index += 1
                used.add(name.casefold()); save_json(folder / name, export_skin(doc, self.editor.assets.defaults(doc['species'])))
                assignments.append(name+' — '+row['label'])
            d = self.source
            assignments='\n'.join(assignments)
            (folder / 'Import notes.txt').write_text(f'{len(rows)} experiments. Reference: {d["species"]}, pattern {d["pattern"]+1}, female={d["female"]}, growth={d["growth"]}, prime={d["prime"]}, variation={d["variation"]}.\nLight: {self.lighting_label}.\n{self.batch_description}\n{assignments}\nCompact JSON carries colors, not model settings. Previews are not live-game validation. Some extreme inputs may exceed external importer limits.\n', encoding='utf-8')
            self.status.set(f'Exported {len(rows)} JSONs into {folder}. No existing files were replaced.')
        except (ValueError, OSError) as error:
            messagebox.showerror('Export incomplete', str(error) + (f'\nFiles already written remain in {folder}.' if folder else ''), parent=self.window)

    def close(self):
        if self.closed: return
        self.closed = True; self.queue.clear()
        if self.timer is not None: self.window.after_cancel(self.timer)
        if self.future is not None: self.future.cancel()
        self.rows.clear(); self.baseline = self.photo = None
        self.editor.experiment_locks = self.lock_values()
        self.window.grab_release(); self.window.destroy()
        self.editor.experiment_lab = None
        if not self.editor.closed:
            self.editor.idle_playing.set(self.was_playing); self.editor.toggle_idle(); self.editor.schedule_draw()
