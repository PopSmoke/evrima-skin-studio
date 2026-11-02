"""Standalone local skin studio. UI depends on the document and asset adapters."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import ImageTk
from skin_document import SLOTS, as_hex, hex_color, new_document, import_json, export_skin, export_filename, save_json, validate, RAW_MODE, BYTE_HEX_MODE, format_color, parse_color, raw_number, importer_range_notes, normalize_json_whitespace
from skin_assets import SkinAssets, HERE
from skin_lighting import StudioRenderer as GLRenderer, PRESETS, DIRECTIONS
from morph_inspector import preview_camera
from skin_animations import AnimationLibrary
from skin_recovery import DraftRecovery
from skin_workflow_ui import output_dir
from skin_help import CREDIT, StudioHelp

MODES = ('Game hex (sRGB)', BYTE_HEX_MODE, RAW_MODE)


class SkinEditor:
    def __init__(self, root, visible=True):
        self.root = root
        if not visible:
            root.withdraw()
        root.title('Evrima Skin Studio')
        root.geometry('1320x880')
        root.minsize(1150, 820)
        self.assets = SkinAssets()
        self.doc = new_document('Carnotaurus', self.assets.defaults('Carnotaurus'))
        self.saved = copy.deepcopy(self.doc)
        self.path = None
        self.history = []
        self.redo_history = []
        self.experiment_lab = None
        self.skin_comparison = None
        self.pattern_audition = None
        self.help_window = None
        self.skin_library = None
        self.skin_influence = None
        self.library_rows = []
        self.library_saved = []
        self.library_path = None
        self.workflow_window = None
        self.preset_browser = None
        self.workflow_presets = []
        self.presets_saved = []
        self.presets_path = None
        self.preferences_path = HERE / 'workspace-preferences.json'
        self.remember_workspace = False
        self.export_folder = ''
        self.checkpoints = []
        self.closed = False
        self.recovery_status = tk.StringVar(value='Recovery is off. Choose a separate JSON file to keep a local draft.')
        self.recovery = DraftRecovery(root, self.recovery_status.set)
        self.renderer = GLRenderer(1800, 1200)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='skin-bake')
        self.future = None
        self.generation = 0
        self.render_mesh = self.material = self.image = self.photo = None
        self.render_shape = None
        self.idles = AnimationLibrary()
        self.idle_edition = self.idles.data.get('edition') == 'idle-only'
        if self.idle_edition:
            root.title('Evrima Skin Studio — Idle Edition')
        self.render_document = None
        self.rendered_lighting = None
        self.render_quality = None
        self.render_used = None
        self.render_animation_id = None
        self.animation_species = None
        self.animation_id = None
        self.animation_name = tk.StringVar()
        self.animation_filter = tk.StringVar()
        self.animation_count = tk.StringVar()
        self.animation_loop = tk.BooleanVar(value=True)
        self.animation_speed = tk.StringVar(value='1')
        self.animation_position = tk.DoubleVar(value=0.)
        self.animation_time = tk.StringVar(value='0.00 s')
        self.updating_timeline = False
        self.render_idle = None
        self.idle_species = None
        self.idle_seconds = 0.
        self.idle_reference = False
        self.idle_last = time.monotonic()
        self.idle_timer = None
        self.idle_playing = tk.BooleanVar(value=True)
        self.idle_label = tk.StringVar(value='Preparing animation…')
        self.idle_camera = None
        self.render_generation = -1
        self.pending = self.poll_id = None
        self.hex_pending = None
        self.syncing_colors = False
        self.yaw, self.pitch, self.zoom = -65., 12., 1.
        self.drag = None

        self.name = tk.StringVar(value=self.doc['name'])
        self.species = tk.StringVar(value=self.doc['species'])
        self.pattern = tk.StringVar()
        self.sex = tk.StringVar(value='Male')
        self.growth = tk.StringVar(value='100')
        self.variation = tk.StringVar(value='8')
        self.default_eyes = tk.BooleanVar(value=True)
        self.prime = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value=MODES[0])
        self.quality = tk.StringVar(value='512')
        self.light_preset = tk.StringVar(value='Studio')
        self.light_direction = tk.StringVar(value='Original')
        self.light_strength = tk.StringVar(value='1')
        self.light_label = tk.StringVar(value='Light: ' + self.renderer.lighting_label)
        self.compare = tk.BooleanVar(value=False)
        self.colors = {k: tk.StringVar() for k in SLOTS}
        self.raw_colors = {k: [tk.StringVar() for _ in range(4)] for k in SLOTS}
        self.show_alpha = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Preparing model…')
        self.preview_label = tk.StringVar(value='Your design')
        for alias, variable in self.colors.items():
            variable.trace_add('write', lambda *_, a=alias: self.color_text_changed(a))
            for channel in self.raw_colors[alias]:
                channel.trace_add('write', lambda *_, a=alias: self.raw_color_changed(a))

        toolbar = ttk.Frame(root, padding=(12, 10))
        toolbar.pack(fill='x')
        for text, command in [('New', self.reset), ('Open…', self.open_file), ('Save project…', self.save_project),
                              ('Export skin…', self.export_file), ('Save image…', self.save_preview), ('Palettes…', self.open_palettes), ('Undo', self.undo)]:
            ttk.Button(toolbar, text=text, command=command).pack(side='left', padx=(0, 6))
        self.redo_button = ttk.Button(toolbar, text='Redo', command=self.redo, state='disabled')
        self.redo_button.pack(side='left', padx=(0, 6))
        ttk.Button(toolbar, text='Help & About', command=self.open_help).pack(side='right')
        area = ttk.Frame(root, padding=(12, 0, 12, 8))
        area.pack(fill='both', expand=True)
        sidebar = ttk.Frame(area, width=380)
        sidebar.pack(side='left', fill='y', padx=(0, 14))
        sidebar.pack_propagate(False)
        scroll = tk.Canvas(sidebar, highlightthickness=0, width=360)
        scrollbar = ttk.Scrollbar(sidebar, orient='vertical', command=scroll.yview)
        scrollbar.pack(side='right', fill='y')
        scroll.pack(side='left', fill='both', expand=True)
        scroll.configure(yscrollcommand=scrollbar.set)
        left = ttk.Frame(scroll)
        sidebar_content = left
        pane = scroll.create_window((0, 0), window=left, anchor='nw')
        left.bind('<Configure>', lambda e: scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>', lambda e: scroll.itemconfigure(pane, width=e.width))
        def sidebar_wheel(event):
            if str(event.widget).startswith(str(sidebar_content)) or event.widget is scroll:
                scroll.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        root.bind('<MouseWheel>', sidebar_wheel, add='+')
        right = ttk.Frame(area)
        right.pack(side='left', fill='both', expand=True)
        ttk.Label(left, text='Skin Studio', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(left, text='Create. Compare. Make it yours.', wraplength=350).pack(anchor='w', pady=(0, 10))
        self.sidebar_tabs = ttk.Notebook(left); self.sidebar_tabs.pack(fill='both', expand=True)
        self.sidebar_pages = {}
        for title in ('Design', 'View', 'Tools'):
            frame = ttk.Frame(self.sidebar_tabs, padding=(8, 10))
            self.sidebar_tabs.add(frame, text=title); self.sidebar_pages[title] = frame
        left = self.sidebar_pages['Design']
        ttk.Label(left, text='Design name').pack(anchor='w')
        entry = ttk.Entry(left, textvariable=self.name)
        entry.pack(fill='x', pady=(2, 8))
        entry.bind('<FocusOut>', lambda e: self.apply_controls())
        entry.bind('<Return>', lambda e: self.apply_controls())

        self.species_box = self.combo(left, 'Dinosaur', self.species, sorted(self.assets.profiles), self.change_species)
        self.pattern_box = self.combo(left, 'Pattern', self.pattern, [], self.apply_controls)
        self.material_notice = ttk.Label(left, wraplength=345)
        self.material_notice.pack(fill='x', pady=(0, 4))
        ttk.Button(left, text='Audition patterns…', command=self.open_patterns).pack(fill='x', pady=(0, 6))
        self.combo(left, 'Sex', self.sex, ['Male', 'Female'], self.apply_controls)
        row = ttk.Frame(left)
        row.pack(fill='x', pady=5)
        for label, variable in [('Growth %', self.growth), ('Variation', self.variation)]:
            box = ttk.Frame(row)
            box.pack(side='left', fill='x', expand=True)
            ttk.Label(box, text=label).pack(anchor='w')
            inp = ttk.Entry(box, textvariable=variable, width=12)
            inp.pack(anchor='w', pady=2)
            inp.bind('<Return>', lambda e: self.apply_controls())
            inp.bind('<FocusOut>', lambda e: self.apply_controls())
        self.prime_box = ttk.Checkbutton(left, text='Prime model preview', variable=self.prime, command=self.apply_controls)
        self.prime_box.pack(anchor='w', pady=(4, 2))
        self.shape_note = ttk.Label(left, wraplength=345)
        self.combo(left, 'Color input', self.mode, MODES, self.refresh_colors)

        color_host = ttk.Frame(left)
        color_host.pack(fill='x')
        self.hex_frame = ttk.Frame(color_host)
        self.raw_frame = ttk.Frame(color_host)
        self.swatches = {}
        self.raw_swatches = {}
        self.raw_entries = {}
        self.eye_widgets = []
        for alias, (label, _, _) in SLOTS.items():
            row = ttk.Frame(self.hex_frame)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label, width=12).pack(side='left')
            swatch = tk.Button(row, width=3, relief='flat', command=lambda a=alias: self.pick(a))
            swatch.pack(side='left', padx=(0, 5))
            self.swatches[alias] = swatch
            field = ttk.Entry(row, textvariable=self.colors[alias], width=10)
            field.pack(side='left', padx=(0, 4))
            field.bind('<Return>', lambda e, a=alias: self.edit_hex(a))
            field.bind('<FocusOut>', lambda e, a=alias: self.edit_hex(a))
            raw = ttk.Button(row, text='RGBA…', width=7, command=lambda a=alias: self.edit_raw(a))
            raw.pack(side='left')
            if alias == 'e':
                self.eye_widgets = [swatch, field, raw]
        grid = ttk.Frame(self.raw_frame)
        grid.pack(fill='x')
        self.raw_grid = grid
        for column, title in enumerate(('X', 'Y', 'Z', 'A'), 2):
            heading = ttk.Label(grid, text=title, anchor='center')
            heading.grid(row=0, column=column, sticky='ew', pady=(0, 4))
        for index, (alias, (label, _, _)) in enumerate(SLOTS.items(), 1):
            swatch = tk.Button(grid, width=1, relief='flat', command=lambda a=alias: self.pick(a))
            swatch.grid(row=index, column=0, padx=(0, 4), pady=3)
            self.raw_swatches[alias] = swatch
            ttk.Label(grid, text=f'{label} ({alias})', wraplength=105).grid(row=index, column=1, sticky='w', padx=(0, 4))
            entries = []
            for channel, variable in enumerate(self.raw_colors[alias]):
                field = ttk.Entry(grid, textvariable=variable, width=6, justify='right', font=('Consolas', 9))
                field.grid(row=index, column=channel + 2, sticky='ew', padx=2, pady=3)
                field.bind('<Return>', lambda e, a=alias: self.edit_hex(a))
                field.bind('<FocusOut>', lambda e, a=alias: self.edit_hex(a))
                entries.append(field)
            self.raw_entries[alias] = entries
            if alias == 'e':
                self.eye_widgets.extend([swatch, *entries])
        ttk.Checkbutton(self.raw_frame, text='Show alpha (A)', variable=self.show_alpha, command=self.toggle_alpha).pack(anchor='w', pady=(5, 0))
        self.toggle_alpha()
        ttk.Checkbutton(left, text='Use default eyes', variable=self.default_eyes, command=self.apply_controls).pack(anchor='w', pady=8)
        ttk.Button(left, text='Color tips & known interactions', command=lambda: self.open_help('Color interactions')).pack(fill='x', pady=(2, 6))
        ttk.Button(left, text='Apply settings', command=self.apply_controls).pack(fill='x', pady=5)
        left = self.sidebar_pages['View']
        self.combo(left, 'Preview detail', self.quality, ['256', '512', '1024'], self.request_preview)
        lighting = ttk.LabelFrame(left, text='Preview lighting', padding=8)
        lighting.pack(fill='x', pady=8)
        self.combo(lighting, 'Preset', self.light_preset, list(PRESETS), self.change_lighting)
        self.combo(lighting, 'Direction', self.light_direction, list(DIRECTIONS), self.change_lighting)
        self.combo(lighting, 'Light strength', self.light_strength, ['0', '0.25', '0.5', '1', '1.5', '2'], self.change_lighting)
        ttk.Button(lighting, text='Reset lighting', command=self.reset_lighting).pack(fill='x', pady=4)
        ttk.Checkbutton(left, text='Show original colors', variable=self.compare, command=self.request_preview).pack(anchor='w', pady=5)
        ttk.Button(left, text='Preview details…', command=lambda: self.open_help('Preview details')).pack(fill='x', pady=5)
        left = self.sidebar_pages['Tools']
        ttk.Button(left, text='Experiment Lab…', command=self.open_experiments).pack(fill='x', pady=5)
        ttk.Button(left, text='Compare skins / checkpoints…', command=self.open_comparison).pack(fill='x', pady=5)
        ttk.Button(left, text='My skin library…', command=self.open_library).pack(fill='x', pady=5)
        ttk.Button(left, text='Design tools / workspace…', command=self.open_design_tools).pack(fill='x', pady=5)
        ttk.Button(left, text='See where colors act…', command=self.open_influence).pack(fill='x', pady=5)
        ttk.Button(left, text='What do these tools do?', command=lambda: self.open_help('Tools explained')).pack(fill='x', pady=5)
        recovery = ttk.LabelFrame(left, text='Recovery copy', padding=8)
        recovery.pack(fill='x', pady=8)
        ttk.Button(recovery, text='Enable / choose recovery copy…', command=self.enable_recovery).pack(fill='x')
        row = ttk.Frame(recovery); row.pack(fill='x', pady=5)
        ttk.Button(row, text='Save copy now', command=self.save_recovery).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Stop recovery', command=self.stop_recovery).pack(side='left', fill='x', expand=True, padx=(5,0))
        ttk.Label(recovery, textvariable=self.recovery_status, wraplength=325).pack(anchor='w')

        top = ttk.Frame(right)
        top.pack(fill='x')
        ttk.Label(top, textvariable=self.preview_label, font=('Segoe UI', 10, 'bold')).pack(side='left')
        ttk.Button(top, text='Reset camera', command=self.reset_camera).pack(side='right')
        ttk.Label(right, textvariable=self.light_label).pack(anchor='w', pady=(3,0))
        animation_bar = ttk.Frame(right)
        animation_bar.pack(fill='x', pady=(6, 0))
        ttk.Label(animation_bar, text='Animation').pack(side='left', padx=(0, 6))
        self.animation_box = ttk.Combobox(animation_bar, textvariable=self.animation_name, state='readonly', height=20)
        self.animation_box.pack(side='left', fill='x', expand=True)
        self.animation_box.bind('<<ComboboxSelected>>', lambda e: self.change_animation())
        ttk.Label(animation_bar, text='Find').pack(side='left', padx=6)
        ttk.Entry(animation_bar, textvariable=self.animation_filter, width=16).pack(side='left')
        self.animation_filter.trace_add('write', lambda *_: self.filter_animations())
        controls = ttk.Frame(right)
        controls.pack(fill='x', pady=(5, 0))
        ttk.Checkbutton(controls, text='Play', variable=self.idle_playing, command=self.toggle_idle).pack(side='left')
        ttk.Checkbutton(controls, text='Loop', variable=self.animation_loop).pack(side='left', padx=5)
        ttk.Button(controls, text='Restart', command=self.restart_animation).pack(side='left')
        ttk.Button(controls, text='Reference pose', command=self.reference_pose).pack(side='left', padx=6)
        ttk.Label(controls, text='Speed').pack(side='left')
        ttk.Combobox(controls, textvariable=self.animation_speed, values=('0.25', '0.5', '1', '2'), width=4, state='readonly').pack(side='left', padx=5)
        ttk.Label(controls, textvariable=self.idle_label).pack(side='left', padx=5)
        timeline = ttk.Frame(right)
        timeline.pack(fill='x')
        ttk.Scale(timeline, from_=0., to=1., variable=self.animation_position, command=self.scrub_animation).pack(side='left', fill='x', expand=True)
        ttk.Label(timeline, textvariable=self.animation_time, width=19).pack(side='left', padx=5)
        self.canvas = tk.Canvas(right, background='#101921', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, pady=8)
        ttk.Label(right, text='Drag to turn • Scroll to zoom • Colors update as you edit').pack(anchor='w')
        self.canvas.bind('<Configure>', lambda e: self.schedule_draw())
        self.canvas.bind('<ButtonPress-1>', lambda e: setattr(self, 'drag', (e.x, e.y, self.yaw, self.pitch)))
        self.canvas.bind('<B1-Motion>', self.rotate)
        self.canvas.bind('<ButtonRelease-1>', lambda e: setattr(self, 'drag', None))
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.details = tk.Text(right, height=5, wrap='word', relief='flat', background='#eef2f5', font=('Segoe UI', 10), padx=10, pady=8)
        # Keep diagnostic text available to Help without crowding the canvas.
        ttk.Label(root, textvariable=self.status, padding=(12, 6), wraplength=1250).pack(fill='x')
        footer = ttk.Frame(root, padding=(12, 0, 12, 8)); footer.pack(fill='x')
        ttk.Label(footer, text='Preview appearance may vary in game.').pack(side='left')
        ttk.Button(footer, text=CREDIT, command=lambda: self.open_help('About')).pack(side='right')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Control-z>', lambda event: self.history_shortcut(event, False))
        root.bind('<Control-y>', lambda event: self.history_shortcut(event, True))
        root.bind('<Control-Shift-Z>', lambda event: self.history_shortcut(event, True))
        self.sync_controls()
        if visible:
            from skin_workflow import load_workspace
            load_workspace(self)
        self.request_preview()
        self.idle_timer = self.root.after(50, self.tick_idle)

    def open_help(self, page='Getting started'):
        if self.help_window is None:
            self.help_window = StudioHelp(self, page)
        else:
            self.help_window.show(page)
        return self.help_window

    def open_design_tools(self):
        for active in (self.workflow_window,self.experiment_lab,self.skin_comparison,self.pattern_audition,self.skin_library,self.skin_influence):
            if active is not None:
                active.window.lift()
                return active if active is self.workflow_window else None
        self.cancel_live_colors()
        if not self.apply_controls():return None
        from skin_workflow_ui import DesignTools
        self.workflow_window=DesignTools(self)
        return self.workflow_window

    def open_experiments(self):
        if self.workflow_window is not None:
            self.workflow_window.window.lift();return None
        if self.skin_influence is not None:
            self.skin_influence.window.lift()
            return None
        if self.skin_library is not None:
            self.skin_library.window.lift()
            return None
        if self.pattern_audition is not None:
            self.pattern_audition.window.lift()
            return None
        if self.skin_comparison is not None:
            self.skin_comparison.window.lift()
            return None
        if self.experiment_lab is not None:
            self.experiment_lab.window.lift()
            return self.experiment_lab
        self.cancel_live_colors()
        if not self.apply_controls():
            return None
        from skin_experiment_ui import ExperimentLab
        self.experiment_lab = ExperimentLab(self)
        return self.experiment_lab

    def open_comparison(self):
        if self.workflow_window is not None:
            self.workflow_window.window.lift();return None
        if self.skin_influence is not None:
            self.skin_influence.window.lift()
            return None
        if self.skin_library is not None:
            self.skin_library.window.lift()
            return None
        if self.pattern_audition is not None:
            self.pattern_audition.window.lift()
            return None
        if self.experiment_lab is not None:
            self.experiment_lab.window.lift()
            return None
        if self.skin_comparison is not None:
            self.skin_comparison.window.lift()
            return self.skin_comparison
        self.cancel_live_colors()
        if not self.apply_controls():
            return None
        from skin_compare_ui import SkinComparison
        self.skin_comparison = SkinComparison(self)
        return self.skin_comparison

    def open_patterns(self):
        if self.workflow_window is not None:
            self.workflow_window.window.lift();return None
        for active in (self.experiment_lab, self.skin_comparison, self.skin_library, self.skin_influence):
            if active is not None:
                active.window.lift()
                return None
        if self.pattern_audition is not None:
            self.pattern_audition.window.lift()
            return self.pattern_audition
        self.cancel_live_colors()
        if not self.apply_controls():
            return None
        from skin_pattern_audition import PatternAudition
        self.pattern_audition = PatternAudition(self)
        return self.pattern_audition

    def open_library(self):
        if self.workflow_window is not None:
            self.workflow_window.window.lift();return None
        for active in (self.experiment_lab, self.skin_comparison, self.pattern_audition, self.skin_influence):
            if active is not None:
                active.window.lift()
                return None
        if self.skin_library is not None:
            self.skin_library.window.lift()
            return self.skin_library
        self.cancel_live_colors()
        if not self.apply_controls():
            return None
        from skin_library_ui import SkinLibrary
        self.skin_library = SkinLibrary(self)
        return self.skin_library

    def open_influence(self):
        if self.workflow_window is not None:
            self.workflow_window.window.lift();return None
        for active in (self.experiment_lab, self.skin_comparison, self.pattern_audition, self.skin_library):
            if active is not None:
                active.window.lift()
                return None
        if self.skin_influence is not None:
            self.skin_influence.window.lift()
            return self.skin_influence
        self.cancel_live_colors()
        if not self.apply_controls():
            return None
        from skin_influence_ui import SkinInfluence
        self.skin_influence = SkinInfluence(self)
        return self.skin_influence

    def open_palettes(self):
        try:
            from skin_palettes import open_browser
            return open_browser(self)
        except (ValueError, OSError, KeyError) as error:
            messagebox.showerror('Palette library', str(error), parent=self.root)

    def combo(self, parent, title, variable, values, callback):
        ttk.Label(parent, text=title).pack(anchor='w')
        box = ttk.Combobox(parent, textvariable=variable, values=values, state='readonly')
        box.pack(fill='x', pady=(2, 7))
        box.bind('<<ComboboxSelected>>', lambda e: callback())
        return box

    def patterns(self):
        patterns = self.assets.profiles[self.doc['species']]['body']['patterns']
        self.pattern_indices = [i for i, p in enumerate(patterns) if p.get('available', True)]
        return [('Asset: ' + patterns[i]['name']) if patterns[i].get('origin') == 'asset-preview'
                else f'{i + 1}: {patterns[i]["name"]}' for i in self.pattern_indices]

    def sync_controls(self):
        self.name.set(self.doc['name'])
        self.species.set(self.doc['species'])
        self.sync_animations()
        names = self.patterns()
        self.pattern_box.configure(values=names)
        self.pattern.set(names[self.pattern_indices.index(self.doc['pattern'])])
        self.sex.set('Female' if self.doc['female'] else 'Male')
        self.growth.set(f'{self.doc["growth"] * 100:g}')
        self.variation.set(f'{self.doc["variation"]:g}')
        self.default_eyes.set(self.doc['default_eyes'])
        self.prime.set(self.doc.get('prime', False))
        full = self.assets.shapes.full_support(self.doc['species'])
        elder = self.assets.shapes.elder_support(self.doc['species'])
        self.prime_box.configure(text='Prime' if full else 'Prime (limited preview)' if elder else 'Prime preview unavailable', state='normal' if full or elder else 'disabled')
        profile = self.assets.profiles[self.doc['species']]
        self.material_notice.configure(text='This dinosaur uses painted body textures. Body colors are saved, but do not recolor its preview.' if profile.get('body_kernel') == 'legacy-painted' else '')
        note = self.assets.shapes.support_note(self.doc['species'])
        if full or elder:
            note += ' Prime differences begin above 75% growth.'
        if profile.get('material_support') == 'experimental':
            note += '\nExperimental material preview: original textures; species-specific shader differences are not fully verified.'
        if profile['eye']['kernel'] == 'source-texture':
            note += '\nLegacy eyes: source texture only. Eye tint preview is unavailable; imported colors remain saved.'
        if len(names) < len(profile['body']['patterns']):
            note += f'\n{len(names)} of {len(profile["body"]["patterns"])} patterns have recovered textures.'
        selected_pattern = profile['body']['patterns'][self.doc['pattern']]
        if selected_pattern.get('origin') == 'asset-preview':
            note += '\nAsset texture preview only: no verified game pattern index. Save as a studio project to retain this selection.'
        elif selected_pattern.get('origin') == 'stored-material':
            note += '\nThis model has no recovered game pattern table; showing its stored material.'
        self.shape_note.configure(text=note)
        self.refresh_colors()

    def sync_animations(self):
        species = self.doc['species']
        if self.animation_species != species:
            self.animation_species = species
            self.animation_rows = self.idles.choices(species)
            row = self.animation_rows[0]
            self.animation_id = row['id']
            self.animation_name.set(row['label'])
            self.animation_loop.set(row['default_loop'])
            self.animation_filter.set('')
        self.filter_animations()

    def filter_animations(self):
        rows = getattr(self, 'animation_rows', [])
        query = self.animation_filter.get().strip().lower()
        visible = [r for r in rows if query in r['label'].lower()]
        self.animation_box.configure(values=[r['label'] for r in visible])
        excluded = len(self.idles.data['models'].get(self.animation_species, {}).get('excluded', []))
        self.animation_count.set('One idle per dinosaur • compact portable edition' if self.idle_edition else f'{len(visible)} of {len(rows)} clips • {excluded} layers or incompatible clips excluded')

    def change_animation(self):
        row = next((r for r in self.animation_rows if r['label'] == self.animation_name.get()), None)
        if row is None or row['id'] == self.animation_id:
            return
        self.animation_id = row['id']
        self.animation_loop.set(row['default_loop'])
        self.idle_playing.set(True)
        self.idle_reference = False
        self.request_preview()
        self.idle_label.set('Loading animation…')
        self.status.set('Loading selected animation…')

    def update_timeline(self):
        duration = self.render_idle.duration if self.render_idle is not None else 1.
        self.updating_timeline = True
        try:
            self.animation_position.set(self.idle_seconds / duration)
            self.animation_time.set(f'{self.idle_seconds:.2f} / {duration:.2f} s')
        finally:
            self.updating_timeline = False

    def scrub_animation(self, value):
        if self.updating_timeline or self.render_idle is None or self.render_generation != self.generation:
            return
        self.idle_playing.set(False)
        self.idle_reference = False
        self.idle_seconds = float(value) * self.render_idle.duration
        self.idle_label.set('Paused')
        self.update_timeline()
        self.schedule_draw()

    def restart_animation(self):
        if self.render_idle is None or self.render_generation != self.generation:
            return
        self.idle_seconds = 0.
        self.idle_playing.set(True)
        self.toggle_idle()
        self.update_timeline()

    def refresh_colors(self):
        self.cancel_live_colors()
        self.syncing_colors = True
        defaults = self.assets.defaults(self.doc['species'])
        try:
            for alias in SLOTS:
                color = defaults[alias] if alias == 'e' and self.doc['default_eyes'] else self.doc['colors'][alias]
                self.colors[alias].set(format_color(color, self.mode.get()))
                self.swatches[alias].configure(bg=as_hex(color))
                self.raw_swatches[alias].configure(bg=as_hex(color))
                for variable, value in zip(self.raw_colors[alias], color):
                    # Keep valid spelling/cursor position while the user types,
                    # e.g. 1e22, rather than rewriting it to 1e+22 after a bake.
                    try:
                        unchanged = raw_number(variable.get()) == value
                    except ValueError:
                        unchanged = False
                    if not unchanged:
                        variable.set(repr(value))
        finally:
            self.syncing_colors = False
        for widget in self.eye_widgets:
            widget.configure(state='disabled' if self.doc['default_eyes'] or self.assets.profiles[self.doc['species']]['eye']['kernel'] == 'source-texture' else 'normal')
        if self.mode.get() == RAW_MODE:
            self.hex_frame.pack_forget()
            self.raw_frame.pack(fill='x')
        else:
            self.raw_frame.pack_forget()
            self.hex_frame.pack(fill='x')

    def toggle_alpha(self):
        for column in (2, 3, 4, 5):
            visible = column != 5 or self.show_alpha.get()
            self.raw_grid.columnconfigure(column, weight=1 if visible else 0, uniform='channels' if visible else '')
            # grid_slaves omits removed widgets, so keep the full list once.
        if not hasattr(self, 'alpha_widgets'):
            self.alpha_widgets = self.raw_grid.grid_slaves(column=5)
        for widget in self.alpha_widgets:
            widget.grid() if self.show_alpha.get() else widget.grid_remove()

    def raw_color_changed(self, alias):
        if not self.syncing_colors:
            self.colors[alias].set(', '.join(v.get() for v in self.raw_colors[alias]))

    def color_text_changed(self, alias):
        if self.syncing_colors:
            return
        if self.mode.get() == RAW_MODE:
            pieces = self.colors[alias].get().split(',')
            if len(pieces) in (3, 4):
                self.syncing_colors = True
                try:
                    for variable, piece in zip(self.raw_colors[alias], pieces):
                        if variable.get() != piece.strip():
                            variable.set(piece.strip())
                finally:
                    self.syncing_colors = False
        self.queue_live_colors()

    def commit(self, doc, show_design=False):
        self.assets.validate_document(doc)
        was_comparing = self.compare.get()
        if doc != self.doc or show_design:
            self.compare.set(False)
        if doc != self.doc:
            # Never conceal an edit behind the original-material comparison.
            self.history.append(copy.deepcopy(self.doc))
            self.history = self.history[-30:]
            self.redo_history.clear()
            self.redo_button.configure(state='disabled')
            self.doc = copy.deepcopy(doc)
            self.recovery.queue(self.doc)
            self.sync_controls()
            self.request_preview()
        elif show_design and was_comparing:
            self.request_preview()

    def cancel_live_colors(self):
        if self.hex_pending is not None:
            self.root.after_cancel(self.hex_pending)
            self.hex_pending = None

    def queue_live_colors(self, *_):
        if self.closed or self.syncing_colors:
            return
        self.cancel_live_colors()
        self.hex_pending = self.root.after(350, self.apply_live_colors)

    def apply_live_colors(self):
        self.hex_pending = None
        # Leave incomplete typing intact. Apply the fields together, never one
        # field followed by a control refresh that discards another pending edit.
        for alias, variable in self.colors.items():
            if alias == 'e' and self.doc['default_eyes']:
                continue
            try:
                parse_color(variable.get(), self.mode.get(), self.doc['colors'][alias])
            except ValueError as error:
                self.status.set(str(error) + ' The last valid skin is still displayed.')
                return
        self.apply_controls()

    def apply_controls(self):
        try:
            doc = copy.deepcopy(self.doc)
            doc.update(name=self.name.get(), pattern=self.pattern_indices[self.pattern_box.current()], female=self.sex.get() == 'Female',
                default_eyes=self.default_eyes.get(), prime=self.prime.get())
            # Unedited rounded displays must not quantize saved model settings.
            if self.growth.get() != f'{self.doc["growth"] * 100:g}':
                doc['growth'] = float(self.growth.get()) / 100
            if self.variation.get() != f'{self.doc["variation"]:g}':
                doc['variation'] = float(self.variation.get())
            for alias in SLOTS:
                if alias == 'e' and (self.doc['default_eyes'] or doc['default_eyes']):
                    continue
                entered = self.colors[alias].get()
                if entered != format_color(self.doc['colors'][alias], self.mode.get()):
                    c = parse_color(entered, self.mode.get(), doc['colors'][alias])
                    doc['colors'][alias] = c
            self.commit(doc)
            return True
        except (ValueError, KeyError) as error:
            self.status.set(str(error))
            return False

    def edit_hex(self, alias):
        if alias == 'e' and self.doc['default_eyes']:
            return
        # Merely leaving a rounded hex field must not quantize imported raw values.
        if self.colors[alias].get() == format_color(self.doc['colors'][alias], self.mode.get()):
            return
        self.cancel_live_colors()
        self.apply_controls()

    def pick(self, alias):
        chosen = colorchooser.askcolor(as_hex(self.doc['colors'][alias]), title=SLOTS[alias][0], parent=self.root)[1]
        if chosen:
            doc = copy.deepcopy(self.doc)
            c = hex_color(chosen)  # OS color picker always displays sRGB.
            c[3] = doc['colors'][alias][3]
            doc['colors'][alias] = c
            self.commit(doc, show_design=True)

    def edit_raw(self, alias):
        popup = tk.Toplevel(self.root)
        popup.title(SLOTS[alias][0] + ' — raw material color')
        popup.transient(self.root)
        popup.grab_set()
        fields = []
        for name, value in zip('RGBA', self.doc['colors'][alias]):
            row = ttk.Frame(popup, padding=8)
            row.pack(fill='x')
            ttk.Label(row, text=name, width=3).pack(side='left')
            field = ttk.Entry(row, width=26)
            field.insert(0, repr(value))
            field.pack(side='left')
            fields.append(field)
        ttk.Label(popup, text='Enter exact color values, including negatives and decimals. A is kept with your colors; it does not make the body transparent.', wraplength=360, padding=8).pack()
        def apply():
            try:
                doc = copy.deepcopy(self.doc)
                doc['colors'][alias] = [raw_number(x.get()) for x in fields]
                self.commit(doc, show_design=True)
                popup.destroy()
            except ValueError as error:
                messagebox.showerror('Invalid RGBA', str(error), parent=popup)
        ttk.Button(popup, text='Apply raw color', command=apply).pack(pady=10)

    def change_species(self):
        species = self.species.get()
        doc = copy.deepcopy(self.doc)
        doc.update(species=species, pattern=0)
        # Keep the design when trying it on another species; New/reset restores its defaults.
        self.commit(doc)

    def confirm_discard(self):
        return self.doc == self.saved or messagebox.askyesno('Unsaved design', 'Discard changes that have not been saved as an editor project?', parent=self.root)

    def reset(self):
        if self.confirm_discard():
            self.commit(new_document(self.doc['species'], self.assets.defaults(self.doc['species'])))
            self.path = None
            self.saved = copy.deepcopy(self.doc)

    def undo(self):
        if self.closed or self.root.grab_current() is not None:
            return
        self.cancel_live_colors()
        # Capture a complete edit still waiting for the live-update timer so it
        # can be redone. Incomplete input only reverts to the last valid design.
        if not self.apply_controls():
            self.sync_controls()
            self.status.set('Incomplete input cleared. The last valid design is restored.')
            return
        if self.history:
            self.redo_history.append(copy.deepcopy(self.doc))
            self.redo_history = self.redo_history[-30:]
            self.doc = self.history.pop()
            self.recovery.queue(self.doc)
            self.compare.set(False)
            self.redo_button.configure(state='normal')
            self.sync_controls()
            self.request_preview()

    def redo(self):
        if self.closed or self.root.grab_current() is not None:
            return
        self.cancel_live_colors()
        # A fresh edit creates a new history branch, including an edit that has
        # not reached the debounce timer yet. Invalid input stays editable.
        if not self.apply_controls():
            self.status.set('Finish or undo incomplete input before using Redo.')
            return
        if self.redo_history:
            self.history.append(copy.deepcopy(self.doc))
            self.history = self.history[-30:]
            self.doc = self.redo_history.pop()
            self.recovery.queue(self.doc)
            self.compare.set(False)
            self.redo_button.configure(state='normal' if self.redo_history else 'disabled')
            self.sync_controls()
            self.request_preview()

    def history_shortcut(self, event, forward):
        if self.closed or self.root.grab_current() is not None:
            return None
        # Text fields retain their own editing keys; modal tools never change
        # the main design through a shortcut behind their window.
        if event.widget.winfo_toplevel() is not self.root or event.widget.winfo_class() in ('Text', 'Entry', 'TEntry', 'TCombobox', 'Spinbox', 'TSpinbox'):
            return None
        self.redo() if forward else self.undo()
        return 'break'

    def open_file(self):
        path = filedialog.askopenfilename(parent=self.root, title='Open skin or editor project', filetypes=[('Skin JSON', '*.json')])
        if not path:
            return
        try:
            if Path(path).stat().st_size > 1024 * 1024:
                raise ValueError('Skin file exceeds 1 MB')
            doc = self.assets.import_document(Path(path).read_text(encoding='utf-8-sig'), self.doc)
            self.assets.validate_document(doc)
            if not self.confirm_discard():
                return
            self.commit(doc)
            self.path = path if json.loads(normalize_json_whitespace(Path(path).read_text(encoding='utf-8-sig'))).get('format') == 'evrima-skin-editor' else None
            if self.recovery.path is not None and Path(path).resolve() == self.recovery.path.resolve():
                self.path = None  # An active rolling draft is not a manual save checkpoint.
            if doc.get('source_glitch', {}) and doc['source_glitch'].get('mode') == 'legacy_glitch':
                self.mode.set(RAW_MODE)
                self.refresh_colors()
            self.saved = copy.deepcopy(self.doc) if self.path else None
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            messagebox.showerror('Cannot open skin', str(error), parent=self.root)

    def save_project(self):
        if not self.apply_controls():
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save editable skin project', initialdir=output_dir(self), defaultextension='.skin-project.json', initialfile=Path(self.path).name if self.path else 'my-skin.skin-project.json', filetypes=[('Skin project', '*.json')])
        if path:
            try:
                if self.recovery.path is not None and Path(path).resolve() == self.recovery.path.resolve():
                    raise ValueError('Choose a project filename separate from the active recovery copy, or stop recovery first.')
                save_json(path, self.doc)
                self.path = path
                self.saved = copy.deepcopy(self.doc)
                self.status.set('Project saved: ' + path)
            except (OSError, ValueError) as error:
                messagebox.showerror('Save failed', str(error), parent=self.root)

    def export_file(self):
        if not self.apply_controls():
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Export skin JSON', initialdir=output_dir(self), defaultextension='.json', initialfile=export_filename(self.doc['name']), filetypes=[('Skin JSON', '*.json')])
        if path:
            try:
                if self.recovery.path is not None and Path(path).resolve() == self.recovery.path.resolve():
                    raise ValueError('Choose an export filename separate from the active recovery copy, or stop recovery first.')
                exported = export_skin(self.doc, self.assets.defaults(self.doc['species']))
                save_json(path, exported)
                notes = importer_range_notes({k: list(v.values()) for k, v in exported['raw'].items()})
                self.status.set('Skin JSON exported: ' + Path(path).name + '. Raw values preserved without clamping. ' + (' '.join(notes) if notes else 'Compact JSON does not carry species, pattern, sex, variation or prime status.'))
            except (OSError, ValueError) as error:
                messagebox.showerror('Export failed', str(error), parent=self.root)

    def save_preview(self):
        if self.image is None or self.render_generation != self.generation or self.rendered_lighting != self.renderer.lighting_label:
            self.status.set('Wait for the current design to finish previewing before saving an image.')
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Save studio preview', initialdir=output_dir(self), defaultextension='.png', initialfile='skin-preview.png', filetypes=[('PNG image', '*.png')])
        if path:
            try:
                from PIL.PngImagePlugin import PngInfo
                info = PngInfo()
                info.add_text('Studio lighting', self.rendered_lighting)
                info.add_text('Preview', 'Decoded materials; authored studio lighting, not live-game validation.')
                self.image.save(path, pnginfo=info)
                self.status.set('Saved current studio view: ' + path)
            except OSError as error:
                messagebox.showerror('Image save failed', str(error), parent=self.root)

    def enable_recovery(self):
        if self.closed or self.root.grab_current() is not None or not self.apply_controls():
            return
        path = filedialog.asksaveasfilename(parent=self.root, title='Choose a separate recovery copy (updated automatically this session)',
            initialfile=export_filename(self.doc['name'] + ' recovery'), defaultextension='.json', filetypes=[('Editable skin JSON', '*.json')])
        if not path: return
        try:
            if self.path is not None and Path(path).resolve() == Path(self.path).resolve():
                raise ValueError('Choose a separate recovery filename so your saved project is not overwritten by automatic updates.')
            self.recovery.enable(path, self.doc)
        except (ValueError, OSError) as error:
            messagebox.showerror('Cannot enable recovery', str(error), parent=self.root)

    def save_recovery(self):
        if self.closed or self.root.grab_current() is not None: return
        if self.recovery.path is None:
            self.enable_recovery(); return
        if self.apply_controls():
            self.recovery.queue(self.doc); self.recovery.flush()

    def stop_recovery(self):
        if self.closed or self.root.grab_current() is not None or self.recovery.path is None: return
        # Stopping retains the most recent valid design; a failed write leaves
        # recovery active so the user can retry instead of silently losing it.
        if self.recovery.flush(): self.recovery.stop()

    def request_preview(self):
        if self.closed:
            return
        if self.pattern_audition is not None:
            self.pattern_audition.editor_changed()
        self.generation += 1
        self.preview_label.set(('Original colors' if self.compare.get() else 'Your design') + ' • updating…')
        self.status.set('Updating skin… You can keep editing.')
        if self.future is None:
            self.start_bake()

    def start_bake(self):
        doc = copy.deepcopy(self.doc)
        if self.compare.get():
            doc['colors'] = self.assets.defaults(doc['species'])
            doc['default_eyes'] = True
            doc['extra_overrides'] = {}
        size = int(self.quality.get())
        self.job_generation = self.generation
        self.job_document, self.job_quality = doc, size
        selection = self.animation_id
        # Switching animations must not rebake the same skin or discard draft inputs.
        reuse = (self.render_mesh, self.material, self.render_shape, self.render_used) if doc == self.render_document and size == self.render_quality else None
        self.job_reuses_material = reuse is not None
        def bake():
            if reuse is None:
                material = self.assets.material(doc, size)
                shape = self.assets.shape(doc)
                mesh, used = self.assets.mesh, copy.deepcopy(self.assets.used)
            else:
                mesh, material, shape, used = reuse
            clip = None
            camera_bounds = None
            idle_error = None
            try:
                clip = self.idles.load(doc['species'], mesh, self.assets.profiles[doc['species']]['mesh']['sha256'], selection)
                camera_bounds = clip.camera_bounds(shape)
            except (ValueError, OSError, KeyError) as error:
                clip = None
                idle_error = str(error)
            return mesh, material, used, shape, clip, camera_bounds, idle_error
        self.future = self.pool.submit(bake)
        self.poll_id = self.root.after(50, self.poll)

    def poll(self):
        self.poll_id = None
        if self.closed:
            return
        if not self.future.done():
            self.poll_id = self.root.after(50, self.poll)
            return
        future, self.future = self.future, None
        try:
            result = future.result()
            if self.job_generation == self.generation:
                previous = self.material
                changed_texels = None
                if previous is not None and result[1].skin_texture.shape == previous.skin_texture.shape:
                    import numpy as np
                    changed_texels = int(np.any(result[1].skin_texture != previous.skin_texture, axis=2).sum())
                self.render_mesh, self.material, used, self.render_shape, self.render_idle, self.idle_camera, idle_error = result
                self.render_document, self.render_quality = self.job_document, self.job_quality
                self.render_used = used
                if self.idle_species != self.doc['species'] or self.render_animation_id != self.animation_id:
                    self.idle_seconds = 0.
                    self.idle_species = self.doc['species']
                    self.render_animation_id = self.animation_id
                self.idle_last = time.monotonic()
                self.update_timeline()
                self.idle_label.set('Animation unavailable' if idle_error else 'Reference pose' if self.idle_reference else 'Playing' if self.idle_playing.get() else 'Paused')
                if not self.draw():
                    return
                self.render_generation = self.generation
                pattern_profile = self.assets.profiles[self.doc['species']]['body']['patterns'][self.doc['pattern']]
                experimental = self.assets.profiles[self.doc['species']].get('material_support') == 'experimental' or pattern_profile.get('origin') == 'asset-preview'
                self.preview_label.set('Original colors' if self.compare.get() else 'Your design • limited preview' if experimental else 'Your design')
                notes = [note.replace('Atavus', 'external') for note in self.doc.get('import_notes', [])]
                notes.extend(importer_range_notes(self.doc['colors']))
                shape = self.render_shape
                notes.append(f'{self.doc["species"]} • {self.pattern.get()} • {shape["state"]} • elder shape {shape["elder_weight"]:.0%} • {"original material comparison" if self.compare.get() else "your colors"}.')
                notes.append(shape['note'])
                if self.render_idle is not None:
                    notes.append('Recovered clip: ' + self.render_idle.row['source'].split('.')[-1] + '. Plays on the displayed model/proportions with root travel held in place; game blending, effects and sounds are not reproduced.')
                    if self.render_idle.reference_components:
                        notes.append(f'{self.render_idle.reference_components} unstored bone components use the source skeleton reference values.')
                if idle_error:
                    notes.append('Animation unavailable: ' + idle_error + '. Showing the reference pose.')
                if experimental:
                    notes.append(self.assets.profiles[self.doc['species']]['material_note'])
                if pattern_profile.get('origin') == 'asset-preview':
                    notes.append(pattern_profile['note'])
                if self.doc.get('prime') and self.doc['growth'] <= .75:
                    notes.append('At this growth, toggling Prime has no model effect under the recovered shared rule.')
                notes.append(f'Color inputs use recovered source textures (up to {max(max(r["size"]) for r in used.values())} px); interactive color bake {self.quality.get()} px, normal preview up to 2048 px.')
                if any(any(v < 0 or v > 1 for v in c[:3]) for c in self.doc['colors'].values()):
                    notes.append('Some raw RGB values are outside 0–1. Preserved in the file; display highlights can clip. This does not prove glow in game.')
                self.details.configure(state='normal')
                self.details.delete('1.0', 'end')
                self.details.insert('1.0', '\n'.join(notes))
                self.details.configure(state='disabled')
                feedback = ''
                if self.job_reuses_material:
                    feedback = 'Animation updated. '
                elif changed_texels == 0:
                    feedback = 'No visible body-color change for this setting. '
                elif changed_texels is not None:
                    feedback = 'Colors updated. '
                self.status.set(feedback + ('Animation unavailable; showing the still pose.' if idle_error else 'Ready.'))
        except Exception as error:
            if self.job_generation == self.generation:
                self.preview_label.set('PREVIEW UNAVAILABLE • raw values retained • previous image below')
                self.status.set('Preview failed: ' + str(error))
                self.details.configure(state='normal')
                self.details.delete('1.0', 'end')
                self.details.insert('1.0', 'This image is the last successful preview, not the current raw values. You can still save or export the current design.\n' + str(error))
                self.details.configure(state='disabled')
        if self.job_generation != self.generation:
            self.start_bake()

    def schedule_draw(self):
        if not self.closed and self.pattern_audition is not None:
            self.pattern_audition.editor_changed()
        if not self.closed and self.pending is None:
            self.pending = self.root.after(20, self.draw)

    def toggle_idle(self):
        if self.idle_playing.get():
            self.idle_reference = False
            if self.render_idle is not None and self.idle_seconds >= self.render_idle.duration:
                self.idle_seconds = 0.
        self.idle_last = time.monotonic()
        self.idle_label.set('Animation unavailable' if self.render_idle is None else 'Reference pose' if self.idle_reference else 'Playing' if self.idle_playing.get() else 'Paused')
        self.schedule_draw()

    def reference_pose(self):
        self.idle_playing.set(False)
        self.idle_reference = True
        self.idle_label.set('Reference pose')
        self.schedule_draw()

    def tick_idle(self):
        self.idle_timer = None
        if self.closed:
            return
        now = time.monotonic()
        elapsed = now - self.idle_last
        self.idle_last = now
        if (self.idle_playing.get() and self.render_idle is not None
                and self.render_generation == self.generation and self.future is None):
            self.idle_seconds += elapsed * float(self.animation_speed.get())
            if self.animation_loop.get():
                self.idle_seconds %= self.render_idle.duration
            elif self.idle_seconds >= self.render_idle.duration:
                self.idle_seconds = self.render_idle.duration
                self.idle_playing.set(False)
                self.idle_label.set('Finished')
            self.update_timeline()
            if not self.draw():
                self.idle_playing.set(False)
                self.idle_label.set('Paused after display error')
        # A bounded UI timer: no queued frame backlog, no texture rebakes.
        self.idle_timer = self.root.after(50, self.tick_idle)

    def draw(self):
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None
        if self.closed or self.material is None:
            return
        try:
            width = max(320, min(1700, self.canvas.winfo_width()))
            height = max(240, min(1100, self.canvas.winfo_height()))
            points = self.render_shape['points']
            if self.render_idle is not None and not self.idle_reference:
                points = self.render_idle.vertices(self.idle_seconds, points, self.render_shape['scale'])
            # Fit both states at the same growth so auto-fit cannot hide prime size changes.
            bounds = self.idle_camera if self.idle_camera is not None else (self.render_shape['camera_standard'], self.render_shape['camera_prime'])
            camera = preview_camera(bounds[0], bounds[1], self.yaw, self.pitch, width, height, self.zoom)
            self.image = self.renderer.draw(self.render_mesh, [], camera, width, height, models=[(self.material, points)])
            self.rendered_lighting = self.renderer.lighting_label
            self.photo = ImageTk.PhotoImage(self.image)
            self.canvas.delete('all')
            self.canvas.create_image(self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2, image=self.photo)
            return True
        except Exception as error:
            self.status.set('Display failed: ' + str(error))
            return False

    def reset_camera(self):
        self.yaw, self.pitch, self.zoom = -65., 12., 1.
        self.schedule_draw()

    def change_lighting(self):
        if self.closed or self.root.grab_current() is not None:
            return False
        try:
            self.renderer.set_lighting(self.light_preset.get(), self.light_direction.get(), float(self.light_strength.get()))
        except ValueError as error:
            self.status.set(str(error)); return False
        self.light_label.set('Light: ' + self.renderer.lighting_label)
        self.schedule_draw()
        return True

    def reset_lighting(self):
        if self.closed or self.root.grab_current() is not None:
            return
        self.light_preset.set('Studio'); self.light_direction.set('Original'); self.light_strength.set('1')
        self.change_lighting()

    def rotate(self, event):
        if self.drag:
            x, y, yaw, pitch = self.drag
            self.yaw = yaw + (event.x - x) * .35
            self.pitch = max(-80, min(80, pitch + (event.y - y) * .25))
            self.schedule_draw()

    def wheel(self, event):
        self.zoom = max(.2, min(4., self.zoom * (.9 if event.delta > 0 else 1.1)))
        self.schedule_draw()

    def close(self, force=False):
        if self.closed:
            return
        if not force:
            if self.preset_browser is not None and not self.preset_browser.flush():
                return
            self.cancel_live_colors()
            self.apply_controls()  # Preserve complete pending input before exit/recovery.
            if self.skin_library is not None and not self.skin_library.flush():
                return
            if not self.confirm_discard():
                return
            if self.library_rows != self.library_saved:
                parent = self.skin_library.window if self.skin_library is not None else self.root
                choice = messagebox.askyesnocancel('Unsaved skin library', 'Save your skin library before closing Studio?', parent=parent)
                if choice is None:
                    return
                if choice:
                    from skin_library_ui import save_library
                    if not save_library(self, parent):
                        return
        if not force and not self.recovery.close():
            if not messagebox.askyesno('Recovery copy not saved', 'The latest recovery write failed. Close anyway? The last successful recovery file is retained.', parent=self.root):
                return
        if not force and self.workflow_presets != self.presets_saved:
            choice=messagebox.askyesnocancel('Unsaved presets','Save your recipes and color presets before closing Studio?',parent=self.root)
            if choice is None:return
            if choice:
                from skin_workflow_ui import save_presets
                if not save_presets(self,self.root):return
        if not force and self.remember_workspace:
            try:
                from skin_workflow import write_json,capture_preferences
                write_json(self.preferences_path,capture_preferences(self))
            except (ValueError,OSError) as error:
                if not messagebox.askyesno('Workspace settings not saved',str(error)+'\nClose anyway?',parent=self.root):return
        self.recovery.close(flush=False)
        self.closed = True
        if self.help_window is not None:
            self.help_window.close()
        if self.workflow_window is not None:
            self.workflow_window.close()
        if self.skin_influence is not None:
            self.skin_influence.close()
        if self.skin_library is not None:
            self.skin_library.close(force=True)
        if self.experiment_lab is not None:
            self.experiment_lab.close()
        if self.skin_comparison is not None:
            self.skin_comparison.close()
        if self.pattern_audition is not None:
            self.pattern_audition.close()
        self.cancel_live_colors()
        for pending in (self.pending, self.poll_id, self.idle_timer):
            if pending is not None:
                self.root.after_cancel(pending)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.renderer.close()
        self.root.destroy()


def main(startup_check=None):
    root = tk.Tk()
    try:
        editor = SkinEditor(root)
        if startup_check is not None:
            deadline = time.monotonic() + 60
            def check():
                if editor.image is not None and editor.render_generation == editor.generation and root.winfo_viewable():
                    Path(startup_check).write_text(json.dumps(dict(passed=True,window=root.title(),
                        visible=bool(root.winfo_viewable()),species=editor.doc['species'],
                        idle_clips=len(editor.animation_rows),frame=list(editor.image.size))),encoding='utf-8')
                    editor.close(force=True)
                elif time.monotonic() >= deadline:
                    Path(startup_check).write_text(json.dumps(dict(passed=False,error=editor.status.get())),encoding='utf-8')
                    editor.close(force=True)
                else: root.after(100, check)
            root.after(100, check)
        root.mainloop()
    except Exception:
        import traceback
        log = HERE / 'last-error.txt'
        log.write_text(traceback.format_exc(), encoding='utf-8')
        messagebox.showerror('Skin Studio could not start', 'Details were saved to ' + str(log), parent=root)
        root.destroy()
        raise


if __name__ == '__main__':
    main()
