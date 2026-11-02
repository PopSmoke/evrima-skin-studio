"""Reusable recipes and small design utilities, with explicit JSON storage."""
import copy
import json
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from skin_document import SLOTS,RAW_MODE
from skin_library import tags_from_text
from skin_workflow import *

def output_dir(editor):
    value=getattr(editor,'export_folder','')
    return value if value and Path(value).is_dir() else None

def save_presets(editor,parent):
    path=filedialog.asksaveasfilename(parent=parent,title='Save recipes and color presets',initialdir=output_dir(editor),initialfile=Path(editor.presets_path).name if editor.presets_path else 'My Studio presets.json',defaultextension='.json',filetypes=[('Preset collection','*.json')])
    if not path:return False
    try:
        write_json(path,preset_collection(editor.workflow_presets));editor.presets_path=path;editor.presets_saved=copy.deepcopy(editor.workflow_presets);return True
    except (ValueError,OSError) as error:messagebox.showerror('Could not save presets',str(error),parent=parent);return False

class PresetBrowser:
    def __init__(self,editor,parent,kind,capture,apply):
        self.editor=editor;self.parent=parent;self.kind=kind;self.capture_data=capture;self.apply_data=apply
        self.current_id=None;self.updating=False;self.closed=False
        editor.preset_browser=self
        self.window=tk.Toplevel(parent);self.window.title('Studio — Recipes and color presets');self.window.geometry('790x600');self.window.minsize(700,530)
        self.window.transient(parent);self.window.grab_set();self.window.protocol('WM_DELETE_WINDOW',self.close)
        outer=ttk.Frame(self.window,padding=12);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='Experiment recipes' if kind=='recipe' else 'Color combinations',font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(outer,text='Recipes store controls and locks, not the source skin. Color presets keep raw colors and the original-eye setting.',wraplength=740).pack(anchor='w',pady=5)
        row=ttk.Frame(outer);row.pack(fill='x');self.query=tk.StringVar();self.only_favorites=tk.BooleanVar()
        ttk.Label(row,text='Search names / tags').pack(side='left');ttk.Entry(row,textvariable=self.query).pack(side='left',fill='x',expand=True,padx=8)
        ttk.Checkbutton(row,text='Favorites',variable=self.only_favorites,command=self.refresh).pack(side='left')
        self.query.trace_add('write',self.refresh)
        self.tree=ttk.Treeview(outer,columns=('name','tags','favorite'),show='headings',height=9)
        for key,title in [('name','Preset'),('tags','Tags'),('favorite','Favorite')]:self.tree.heading(key,text=title)
        self.tree.column('favorite',width=65);self.tree.pack(fill='both',expand=True,pady=8);self.tree.bind('<<TreeviewSelect>>',self.select)
        self.name=tk.StringVar(value='My recipe' if kind=='recipe' else 'My colors');self.tags=tk.StringVar();self.favorite=tk.BooleanVar()
        for title,var in [('Preset name',self.name),('Tags (comma-separated)',self.tags)]:
            ttk.Label(outer,text=title).pack(anchor='w');ttk.Entry(outer,textvariable=var).pack(fill='x')
        ttk.Checkbutton(outer,text='Favorite',variable=self.favorite).pack(anchor='w')
        row=ttk.Frame(outer);row.pack(fill='x',pady=8)
        for title,action in [('Capture new',self.capture),('Keep details',self.keep),('Use selected',self.use),('Remove',self.remove)]:ttk.Button(row,text=title,command=action).pack(side='left',padx=3)
        row=ttk.Frame(outer);row.pack(fill='x')
        for title,action in [('Open collection…',self.open),('Save collection…',self.save),('Close',self.close)]:ttk.Button(row,text=title,command=action).pack(side='left',padx=3)
        self.status=tk.StringVar(value='Capture new saves in this session. Save collection to keep it after closing Studio.')
        ttk.Label(outer,textvariable=self.status,wraplength=740).pack(anchor='w',pady=7);self.refresh()

    def selected(self):
        return next((r for r in self.editor.workflow_presets if r['id']==self.current_id),None)
    def flush(self):
        r=self.selected()
        if r is None or self.updating:return True
        try:
            rows=copy.deepcopy(self.editor.workflow_presets);target=next(x for x in rows if x['id']==r['id'])
            target.update(name=self.name.get().strip(),tags=tags_from_text(self.tags.get()),favorite=self.favorite.get())
            self.editor.workflow_presets=validate_presets(rows)
            return True
        except ValueError as error:
            self.status.set(str(error)+' Correct the details before continuing.');return False
    def load_details(self):
        r=self.selected()
        self.name.set(r['name'] if r else '');self.tags.set(', '.join(r['tags']) if r else '');self.favorite.set(r['favorite'] if r else False)
    def refresh(self,*_):
        if self.closed or not self.flush():return False
        self.updating=True;self.tree.delete(*self.tree.get_children())
        for r in self.editor.workflow_presets:
            text=(r['name']+' '+','.join(r['tags'])).casefold()
            if r['kind']==self.kind and (not self.only_favorites.get() or r['favorite']) and all(t in text for t in self.query.get().casefold().split()):self.tree.insert('','end',iid=r['id'],values=(r['name'],', '.join(r['tags']),'Yes' if r['favorite'] else ''))
        if self.current_id and self.tree.exists(self.current_id):self.tree.selection_set(self.current_id)
        elif self.current_id is not None:self.current_id=None;self.load_details()
        self.updating=False
        return True
    def select(self,*_):
        if self.updating:return True
        ids=self.tree.selection();identity=ids[0] if ids else None
        if identity==self.current_id:return True
        if not self.flush():
            if self.current_id and self.tree.exists(self.current_id):self.tree.selection_set(self.current_id)
            return False
        self.current_id=identity;self.load_details();return True
    def capture(self):
        try:
            rows=add_preset(self.editor.workflow_presets,self.name.get(),self.tags.get(),self.kind,self.capture_data());rows[-1]['favorite']=self.favorite.get()
            self.editor.workflow_presets=rows;self.current_id=rows[-1]['id'];self.load_details()
            self.query.set('');self.only_favorites.set(False);self.refresh();self.status.set('Captured. Save collection to keep this preset after Studio closes.')
        except (ValueError,TypeError,KeyError) as error:self.status.set(str(error))
    def keep(self):
        if self.flush() and self.refresh():self.status.set('Details kept. Save collection to retain them after exit.')
    def use(self):
        if not self.select() or not self.flush():return
        r=self.selected()
        if not r:return
        try:self.apply_data(copy.deepcopy(r['data']));self.status.set('Applied '+r['name']+'.')
        except (ValueError,KeyError,TypeError) as error:self.status.set(str(error))
    def remove(self):
        if not self.select() or not self.flush():return
        r=self.selected()
        if r and messagebox.askyesno('Remove preset','Remove '+r['name']+' from this collection?',parent=self.window):
            self.editor.workflow_presets=[x for x in self.editor.workflow_presets if x['id']!=r['id']];self.current_id=None;self.load_details();self.refresh()
    def save(self):
        if not self.select() or not self.flush():return False
        if save_presets(self.editor,self.window):self.refresh();self.status.set('Collection saved.');return True
        return False
    def open(self):
        if not self.flush():return
        path=filedialog.askopenfilename(parent=self.window,title='Open recipe / color preset collection',filetypes=[('Preset JSON','*.json')])
        if not path:return
        try:
            rows=load_presets(read_json(path))
            if self.editor.workflow_presets!=self.editor.presets_saved:
                choice=messagebox.askyesnocancel('Unsaved presets','Save this collection before opening another?',parent=self.window)
                if choice is None or (choice and not save_presets(self.editor,self.window)):return
            self.editor.workflow_presets=rows;self.editor.presets_saved=copy.deepcopy(rows);self.editor.presets_path=path
            self.current_id=None;self.load_details();self.refresh();self.status.set('Collection loaded.')
        except (ValueError,TypeError,KeyError,OSError) as error:self.status.set(str(error))
    def close(self):
        if self.closed:return True
        if not self.flush():return False
        self.closed=True;self.editor.preset_browser=None
        self.window.grab_release();self.window.destroy()
        if self.parent.winfo_exists():self.parent.grab_set() if self.parent is not self.editor.root else None
        return True

class DesignTools:
    def __init__(self,editor):
        self.editor=editor;self.window=tk.Toplevel(editor.root);self.window.title('Skin Studio — Design tools');self.window.geometry('850x680');self.window.minsize(760,600)
        self.window.transient(editor.root);self.window.grab_set();self.window.protocol('WM_DELETE_WINDOW',self.close)
        self.was_playing=editor.idle_playing.get();editor.idle_playing.set(False);editor.toggle_idle()
        outer=ttk.Frame(self.window,padding=12);outer.pack(fill='both',expand=True)
        tabs=ttk.Notebook(outer);tabs.pack(fill='both',expand=True)
        self.tabs={}
        for label in ('Copy colors','Differences','Export check','Workspace'):
            frame=ttk.Frame(tabs,padding=14);tabs.add(frame,text=label);self.tabs[label]=frame
        self.status=tk.StringVar(value='Copy, compare and organize your designs. Color changes support Undo.')
        ttk.Label(outer,textvariable=self.status,wraplength=790).pack(anchor='w',pady=10)
        ttk.Button(outer,text='Close',command=self.close).pack(anchor='e')
        f=self.tabs['Copy colors'];self.from_slot=tk.StringVar(value='b');self.to_slot=tk.StringVar(value='f');self.include_alpha=tk.BooleanVar()
        self.combo(f,'Copy from section',self.from_slot,list(SLOTS));ttk.Button(f,text='Copy exact RGBA to clipboard',command=self.copy_color).pack(anchor='w',pady=5)
        self.color_text=tk.Text(f,height=4,wrap='word');self.color_text.pack(fill='x',pady=6)
        ttk.Button(f,text='Read clipboard into this box',command=self.read_clipboard).pack(anchor='w')
        self.combo(f,'Paste into section',self.to_slot,list(SLOTS));ttk.Checkbutton(f,text='Also replace alpha when four values are supplied',variable=self.include_alpha).pack(anchor='w')
        ttk.Button(f,text='Apply values with Undo',command=self.paste_color).pack(anchor='w',pady=8)
        ttk.Button(f,text='Organized color presets…',command=self.color_presets).pack(anchor='w',pady=10)
        ttk.Label(f,text='Accepts [R, G, B, A] or comma-separated values. Copy resolves original-eye defaults; pasting into eyes switches to custom eye colors.',wraplength=730).pack(anchor='w')
        f=self.tabs['Differences'];ttk.Label(f,text='Compare the current design (A) with another skin or Studio project (B).',wraplength=700).pack(anchor='w')
        ttk.Button(f,text='Choose comparison JSON…',command=self.compare_file).pack(anchor='w',pady=8)
        self.diff=tk.Text(f,wrap='word',height=22);self.diff.pack(fill='both',expand=True)
        ttk.Label(f,text='Compact skin files inherit current model settings where those settings are absent.',wraplength=700).pack(anchor='w')
        f=self.tabs['Export check'];self.profile=tk.StringVar(value=PROFILES[1]);self.minimum=tk.StringVar(value='-1e23');self.maximum=tk.StringVar(value='1e23')
        self.combo(f,'Numeric compatibility profile',self.profile,PROFILES)
        for title,var in [('Custom minimum',self.minimum),('Custom maximum',self.maximum)]:ttk.Label(f,text=title).pack(anchor='w');ttk.Entry(f,textvariable=var).pack(fill='x')
        ttk.Button(f,text='Check current design',command=self.check_export).pack(anchor='w',pady=8)
        self.check_text=tk.Text(f,wrap='word',height=16);self.check_text.pack(fill='both',expand=True)
        f=self.tabs['Workspace'];self.remember=tk.BooleanVar(value=editor.remember_workspace);self.folder=tk.StringVar(value=editor.export_folder)
        ttk.Checkbutton(f,text='Remember workspace on exit',variable=self.remember).pack(anchor='w',pady=8)
        ttk.Label(f,text='Remembers window size and position, preview quality, lighting, and your preferred export folder. Designs, history, recipes and library entries use their own save commands.',wraplength=720).pack(anchor='w',pady=8)
        ttk.Label(f,text='Preferred export folder').pack(anchor='w');ttk.Entry(f,textvariable=self.folder).pack(fill='x');ttk.Button(f,text='Choose folder…',command=self.choose_folder).pack(anchor='w',pady=6)
        ttk.Button(f,text='Save workspace settings',command=self.save_workspace).pack(anchor='w',pady=12)
        ttk.Label(f,text='Settings are stored beside Studio as workspace-preferences.json. Turning remember off and saving disables restoration.',wraplength=720).pack(anchor='w')
    def combo(self,parent,label,var,choices):
        ttk.Label(parent,text=label).pack(anchor='w',pady=(8,0));ttk.Combobox(parent,textvariable=var,values=choices,state='readonly').pack(fill='x')
    def copy_color(self):
        from skin_experiments import prepare_source
        doc=prepare_source(self.editor.doc,self.editor.assets.defaults(self.editor.doc['species']));text=json.dumps(doc['colors'][self.from_slot.get()],allow_nan=False)
        self.color_text.delete('1.0','end');self.color_text.insert('1.0',text);self.window.clipboard_clear();self.window.clipboard_append(text);self.status.set('Exact RGBA copied.')
    def read_clipboard(self):
        try:
            text=self.window.clipboard_get();parse_slot(text);self.color_text.delete('1.0','end');self.color_text.insert('1.0',text)
        except (ValueError,tk.TclError) as error:self.status.set('Cannot read color: '+str(error))
    def paste_color(self):
        try:
            doc=paste_slot(self.editor.doc,self.to_slot.get(),self.color_text.get('1.0','end').strip(),self.include_alpha.get());self.editor.mode.set(RAW_MODE);self.editor.commit(doc,show_design=True);self.status.set('Color applied. Undo is available after closing this window.')
        except ValueError as error:self.status.set(str(error))
    def color_presets(self):
        def capture():return dict(colors=copy.deepcopy(self.editor.doc['colors']),default_eyes=self.editor.doc['default_eyes'])
        def apply(data):
            doc=copy.deepcopy(self.editor.doc);doc.update(copy.deepcopy(data));self.editor.commit(doc,show_design=True)
        return PresetBrowser(self.editor,self.window,'colors',capture,apply)
    def compare_file(self):
        path=filedialog.askopenfilename(parent=self.window,title='Choose skin B',filetypes=[('Skin JSON','*.json')])
        if not path:return
        try:
            if Path(path).stat().st_size>1024*1024:raise ValueError('Skin exceeds 1 MB.')
            other=self.editor.assets.import_document(Path(path).read_text(encoding='utf-8-sig'),self.editor.doc)
            self.diff.delete('1.0','end');self.diff.insert('1.0','A: '+self.editor.doc['name']+'\nB: '+other['name']+'\n\n'+'\n'.join(differences(self.editor.doc,other)))
        except (ValueError,OSError,KeyError,TypeError) as error:self.status.set(str(error))
    def check_export(self):
        try:
            doc=copy.deepcopy(self.editor.doc)
            if doc['default_eyes']:doc['colors']['e']=list(self.editor.assets.defaults(doc['species'])['e'])
            lines=preflight(doc,self.profile.get(),self.minimum.get(),self.maximum.get());self.check_text.delete('1.0','end');self.check_text.insert('1.0','\n'.join(lines))
        except ValueError as error:self.status.set(str(error))
    def choose_folder(self):
        path=filedialog.askdirectory(parent=self.window,title='Preferred export folder',initialdir=output_dir(self.editor))
        if path:self.folder.set(path)
    def save_workspace(self):
        e=self.editor;old=(e.remember_workspace,e.export_folder)
        try:
            folder=self.folder.get().strip()
            if folder and not Path(folder).is_dir():raise ValueError('Choose an existing export folder.')
            e.remember_workspace=self.remember.get();e.export_folder=folder;write_json(e.preferences_path,capture_preferences(e));self.status.set('Workspace settings saved.')
        except (ValueError,OSError) as error:e.remember_workspace,e.export_folder=old;self.status.set(str(error))
    def close(self):
        self.window.grab_release();self.window.destroy();self.editor.workflow_window=None
        self.editor.idle_playing.set(self.was_playing)
        if not self.editor.closed:self.editor.toggle_idle();self.editor.schedule_draw()

def test_record(library):
    if not library.flush() or library.row() is None:return
    identity=library.row()['id'];window=tk.Toplevel(library.window);window.title('Record an in-game test');window.geometry('560x480');window.transient(library.window);window.grab_set()
    f=ttk.Frame(window,padding=14);f.pack(fill='both',expand=True)
    doc=library.row()['document'];ttk.Label(f,text=f'{doc["name"]} — {doc["species"]}, pattern {doc["pattern"]+1}',wraplength=520).pack(anchor='w')
    server=tk.StringVar();build=tk.StringVar();match=tk.StringVar(value='Not compared')
    for label,var in [('Server / rules',server),('Game build',build)]:ttk.Label(f,text=label).pack(anchor='w',pady=(8,0));ttk.Entry(f,textvariable=var).pack(fill='x')
    ttk.Label(f,text='Match to Studio preview').pack(anchor='w',pady=(8,0));ttk.Combobox(f,textvariable=match,values=('Not compared','Close match','Minor differences','Major differences'),state='readonly').pack(fill='x')
    ttk.Label(f,text='Lighting and observations').pack(anchor='w',pady=(8,0));notes=tk.Text(f,height=6,wrap='word');notes.pack(fill='both',expand=True)
    status=tk.StringVar();ttk.Label(f,textvariable=status,wraplength=520).pack(anchor='w')
    def close():window.grab_release();window.destroy();library.window.grab_set()
    def save():
        row=next(r for r in library.editor.library_rows if r['id']==identity)
        stamp=datetime.now().isoformat(timespec='minutes')
        entry=f'[{stamp}] {doc["species"]} / pattern {doc["pattern"]+1} / growth {doc["growth"]:.0%} / prime={doc["prime"]} / female={doc["female"]}\nServer: {server.get()} | Build: {build.get()} | Preview: {match.get()}\n{notes.get("1.0","end-1c")}\n'
        combined=(row['notes']+'\n'+entry).strip()
        if len(combined)>4000:status.set('Test notes exceed 4,000 characters. Shorten existing notes first.');return
        row['notes']=combined;row['status']='Needs adjustment' if match.get()=='Major differences' else 'Tested in game';library.load_details();library.refresh();close()
    ttk.Button(f,text='Add record to this saved design',command=save).pack(pady=8);window.protocol('WM_DELETE_WINDOW',close)
    return window
