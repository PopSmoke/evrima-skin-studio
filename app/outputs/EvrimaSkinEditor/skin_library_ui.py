"""Personal collections: explicit JSON storage, no additional rendering or assets."""
import copy
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from skin_document import save_json, export_skin, export_filename
from skin_checkpoints import on_model
from skin_library import LIMIT, MAX_BYTES, STATUSES, add_documents, encode, decode, matching, tags_from_text
from skin_workflow_ui import output_dir


def save_library(editor, parent):
    path = filedialog.asksaveasfilename(parent=parent, title='Save skin library',
        initialfile=Path(editor.library_path).name if editor.library_path else 'My skins.skin-library.json',
        initialdir=str(Path(editor.library_path).parent) if editor.library_path else output_dir(editor),
        defaultextension='.json', filetypes=[('Skin library JSON', '*.json')])
    if not path: return False
    try:
        save_json(path, encode(editor.library_rows))
        editor.library_path = path; editor.library_saved = copy.deepcopy(editor.library_rows)
        return True
    except (ValueError, OSError) as error:
        messagebox.showerror('Library could not be saved', str(error), parent=parent)
        return False


class SkinLibrary:
    def __init__(self, editor):
        self.editor = editor; self.source = copy.deepcopy(editor.doc)
        self.selected = None; self.updating = False; self.closed = False
        self.was_playing = editor.idle_playing.get()
        editor.idle_playing.set(False); editor.toggle_idle()
        self.window = tk.Toplevel(editor.root); self.window.title('Skin Studio — My skin library')
        self.window.geometry('1080x720'); self.window.minsize(980, 660)
        self.window.transient(editor.root); self.window.grab_set()
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        header = ttk.Frame(self.window, padding=12); header.pack(fill='x')
        ttk.Label(header, text='My skin library', font=('Segoe UI', 19, 'bold')).pack(anchor='w')
        ttk.Label(header, text='Keep complete designs, favorites and test notes. Save library to keep them after closing Studio.').pack(anchor='w')
        row = ttk.Frame(header); row.pack(fill='x', pady=(10, 0))
        for label, command in [('Keep current design', self.capture), ('Import skins…', self.import_skins),
                               ('Open library…', self.open_library), ('Save library…', self.save)]:
            ttk.Button(row, text=label, command=command).pack(side='left', padx=(0, 8))
        filters = ttk.Frame(header); filters.pack(fill='x', pady=(12, 0))
        self.query = tk.StringVar(); self.favorites = tk.BooleanVar(); self.filter_status = tk.StringVar(value='All statuses')
        ttk.Label(filters, text='Search').pack(side='left')
        ttk.Entry(filters, textvariable=self.query, width=32).pack(side='left', padx=6)
        ttk.Checkbutton(filters, text='Favorites only', variable=self.favorites, command=self.refresh).pack(side='left', padx=8)
        box = ttk.Combobox(filters, textvariable=self.filter_status, values=['All statuses', *STATUSES], state='readonly', width=23)
        box.pack(side='left'); box.bind('<<ComboboxSelected>>', self.refresh)
        self.query.trace_add('write', self.refresh)
        body = ttk.Frame(self.window, padding=(12, 0)); body.pack(fill='both', expand=True)
        listing = ttk.Frame(body); listing.pack(side='left', fill='both', expand=True)
        self.tree = ttk.Treeview(listing, columns=('favorite', 'name', 'model', 'test'), show='headings', selectmode='browse')
        for key, title, width in [('favorite', 'Fav', 38), ('name', 'Design', 175), ('model', 'Dinosaur / pattern', 155), ('test', 'In-game test', 145)]:
            self.tree.heading(key, text=title); self.tree.column(key, width=width, minwidth=35)
        bar = ttk.Scrollbar(listing, orient='vertical', command=self.tree.yview)
        bar.pack(side='right', fill='y'); self.tree.pack(fill='both', expand=True)
        self.tree.configure(yscrollcommand=bar.set); self.tree.bind('<<TreeviewSelect>>', self.select)
        details = ttk.Frame(body, padding=(16, 0, 0, 0), width=320); details.pack(side='right', fill='y'); details.pack_propagate(False)
        self.context = tk.StringVar(value='Select a saved design.')
        ttk.Label(details, textvariable=self.context, wraplength=295).pack(anchor='w', pady=(0, 12))
        self.favorite = tk.BooleanVar(); self.tags = tk.StringVar(); self.test_status = tk.StringVar(value=STATUSES[0])
        ttk.Checkbutton(details, text='Favorite', variable=self.favorite).pack(anchor='w')
        ttk.Label(details, text='Tags, separated by commas').pack(anchor='w', pady=(10, 2))
        ttk.Entry(details, textvariable=self.tags).pack(fill='x')
        ttk.Label(details, text='Your in-game test status').pack(anchor='w', pady=(10, 2))
        ttk.Combobox(details, textvariable=self.test_status, values=STATUSES, state='readonly').pack(fill='x')
        ttk.Label(details, text='This is your own record, not automatic game validation.', wraplength=295).pack(anchor='w', pady=5)
        ttk.Label(details, text='Test notes — server/build, lighting, results').pack(anchor='w', pady=(10, 2))
        self.notes = tk.Text(details, height=7, wrap='word'); self.notes.pack(fill='both', expand=True)
        ttk.Button(details, text='Keep details', command=self.refresh).pack(fill='x', pady=8)
        ttk.Button(details, text='Record in-game test…', command=self.record_test).pack(fill='x', pady=4)
        ttk.Button(details, text='Remove selected…', command=self.remove).pack(fill='x')
        footer = ttk.Frame(self.window, padding=12); footer.pack(fill='x')
        self.actions = []
        for label, command in [('Apply colors to current dinosaur', lambda: self.apply(False)),
                               ('Restore full design', lambda: self.apply(True)), ('Export selected JSON…', self.export)]:
            b = ttk.Button(footer, text=label, command=command); b.pack(side='left', padx=(0, 8)); self.actions.append(b)
        ttk.Button(footer, text='Close', command=self.close).pack(side='right')
        self.status = tk.StringVar()
        ttk.Label(self.window, textvariable=self.status, padding=(12, 0, 12, 10), wraplength=1020).pack(fill='x')
        self.refresh()

    def record_test(self):
        from skin_workflow_ui import test_record
        return test_record(self)

    def row(self):
        return next((r for r in self.editor.library_rows if r['id'] == self.selected), None)

    def flush(self):
        row = self.row()
        if row is None: return True
        try:
            rows = copy.deepcopy(self.editor.library_rows)
            target = next(r for r in rows if r['id'] == self.selected)
            target.update(favorite=self.favorite.get(), tags=tags_from_text(self.tags.get()),
                          status=self.test_status.get(), notes=self.notes.get('1.0', 'end-1c'))
            self.editor.library_rows = encode(rows)['designs']
            return True
        except (ValueError, TypeError) as error:
            self.status.set(str(error) + ' Correct the details before continuing.')
            return False

    def refresh(self, *_):
        if self.closed or not self.flush(): return
        self.updating = True
        children = self.tree.get_children()
        if children: self.tree.delete(*children)
        rows = matching(self.editor.library_rows, self.query.get(), self.favorites.get(), self.filter_status.get())
        for row in rows:
            doc = row['document']
            self.tree.insert('', 'end', iid=row['id'], values=('Yes' if row['favorite'] else '',
                ' '.join(doc['name'].split()) or 'Untitled skin', f'{doc["species"]} / {doc["pattern"]+1}', row['status']))
        if self.selected in {r['id'] for r in rows}: self.tree.selection_set(self.selected)
        else: self.selected = None
        self.updating = False; self.load_details()
        dirty = self.editor.library_rows != self.editor.library_saved
        self.status.set(f'{len(rows)} shown / {len(self.editor.library_rows)} saved in this session (limit {LIMIT}). ' +
            ('Unsaved library changes — Save library before exiting.' if dirty else 'Library unchanged.') +
            (' File: ' + Path(self.editor.library_path).name if self.editor.library_path else ''))

    def select(self, *_):
        if self.updating: return
        selection = self.tree.selection()
        identity = selection[0] if selection else None
        if identity == self.selected: return
        if not self.flush():
            if self.selected and self.tree.exists(self.selected): self.tree.selection_set(self.selected)
            return
        self.selected = identity; self.load_details()

    def load_details(self):
        row = self.row()
        for button in self.actions: button.configure(state='normal' if row else 'disabled')
        self.favorite.set(row['favorite'] if row else False)
        self.tags.set(', '.join(row['tags']) if row else '')
        self.test_status.set(row['status'] if row else STATUSES[0])
        self.notes.delete('1.0', 'end'); self.notes.insert('1.0', row['notes'] if row else '')
        if not row: self.context.set('Select a saved design.'); return
        d = row['document']; profile = self.editor.assets.profiles[d['species']]
        pattern = profile['body']['patterns'][d['pattern']]
        origin = pattern.get('origin', 'game-table')
        pattern_text = f'Pattern {d["pattern"]+1}' if origin == 'game-table' else ('Asset-only texture — no verified game index' if origin == 'asset-preview' else 'Stored material — no recovered game pattern table')
        self.context.set(f'{d["name"]}\n{d["species"]} / {pattern_text}\n' +
            f'{"Female" if d["female"] else "Male"} / Growth {d["growth"]:.0%} / {"Prime" if d.get("prime") else "Standard"} / Variation {d["variation"]:g}')

    def capture(self):
        if not self.flush(): return
        try:
            self.editor.library_rows = add_documents(self.editor.library_rows, [self.source])
            self.selected = None
            self.query.set(''); self.favorites.set(False); self.filter_status.set('All statuses')
            self.selected = self.editor.library_rows[-1]['id']; self.load_details(); self.refresh()
        except ValueError as error: self.status.set(str(error))

    def import_skins(self):
        if not self.flush(): return
        paths = filedialog.askopenfilenames(parent=self.window, title='Import skins or editor projects', filetypes=[('Skin JSON', '*.json')])
        if not paths: return
        try:
            if len(paths) + len(self.editor.library_rows) > LIMIT: raise ValueError(f'Library limit is {LIMIT} designs.')
            docs = []
            for path in paths:
                if Path(path).stat().st_size > 1024*1024: raise ValueError(Path(path).name + ' exceeds 1 MB.')
                docs.append(self.editor.assets.import_document(Path(path).read_text(encoding='utf-8-sig'), self.source))
            rows = add_documents(self.editor.library_rows, docs)
            self.editor.library_rows = rows; self.refresh()
            self.status.set(f'Imported {len(docs)} designs. Compact skins use the current dinosaur/settings where unspecified. Save library to keep them.')
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            messagebox.showerror('Import failed — no files added', str(error), parent=self.window)

    def save(self):
        if not self.flush(): return False
        result = save_library(self.editor, self.window)
        if result: self.refresh()
        return result

    def open_library(self):
        if not self.flush(): return
        path = filedialog.askopenfilename(parent=self.window, title='Open skin library', filetypes=[('Skin library JSON', '*.json')])
        if not path: return
        try:
            if Path(path).stat().st_size > MAX_BYTES: raise ValueError('Library exceeds 8 MB.')
            rows = decode(Path(path).read_text(encoding='utf-8-sig'))
            for row in rows: self.editor.assets.validate_document(row['document'])
            if self.editor.library_rows != self.editor.library_saved:
                choice = messagebox.askyesnocancel('Unsaved library', 'Save the current library before opening another?', parent=self.window)
                if choice is None or (choice and not self.save()): return
            self.selected = None
            self.editor.library_rows = rows; self.editor.library_saved = copy.deepcopy(rows); self.editor.library_path = path
            self.query.set(''); self.favorites.set(False); self.filter_status.set('All statuses'); self.refresh()
        except (ValueError, OSError, KeyError, TypeError) as error:
            messagebox.showerror('Cannot open library', str(error), parent=self.window)

    def remove(self):
        if not self.flush() or self.row() is None: return
        if not messagebox.askyesno('Remove design', 'Remove this entry from the library? The original imported file is unchanged.', parent=self.window): return
        self.editor.library_rows = [r for r in self.editor.library_rows if r['id'] != self.selected]
        self.selected = None; self.refresh()

    def apply(self, full):
        if not self.flush() or self.row() is None: return
        try:
            doc = copy.deepcopy(self.row()['document']) if full else on_model(self.row()['document'], self.source)
            self.editor.commit(doc, show_design=True); self.close()
        except (ValueError, KeyError) as error: self.status.set(str(error))

    def export(self):
        if not self.flush() or self.row() is None: return
        doc = self.row()['document']
        path = filedialog.asksaveasfilename(parent=self.window, title='Export selected skin', initialdir=output_dir(self.editor), initialfile=export_filename(doc['name']), defaultextension='.json', filetypes=[('Skin JSON', '*.json')])
        if path:
            try:
                save_json(path, export_skin(doc, self.editor.assets.defaults(doc['species'])))
                self.status.set('Exported ' + Path(path).name + '. Compact JSON does not select dinosaur, pattern, growth or prime. Save library to retain those settings.')
            except (ValueError, OSError) as error: messagebox.showerror('Cannot export skin', str(error), parent=self.window)

    def close(self, force=False):
        if self.closed: return True
        if not force and not self.flush(): return False
        self.closed = True; self.window.grab_release(); self.window.destroy()
        self.editor.skin_library = None
        self.editor.idle_playing.set(self.was_playing)
        if not self.editor.closed: self.editor.toggle_idle(); self.editor.schedule_draw()
        return True
