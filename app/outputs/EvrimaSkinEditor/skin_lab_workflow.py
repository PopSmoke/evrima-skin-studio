"""Experiment result curation, reusable settings and on-demand image sheets."""
import copy
import json
import tkinter as tk
from tkinter import ttk,filedialog
from skin_document import SLOTS
from skin_workflow import RECIPE_VARS,validate_recipe,contact_sheet,differences
from skin_workflow_ui import PresetBrowser,output_dir

class LabWorkflow:
    def setup_workflow(self,controls,panel):
        tab=ttk.Frame(self.tabs,padding=10);self.tabs.add(tab,text='Refine')
        self.refine_section=tk.StringVar(value='f');self.refine_channel=tk.StringVar(value='Unlocked RGB')
        self.refine_percent=tk.StringVar(value='10');self.refine_zero=tk.StringVar(value='0.01');self.refine_count=tk.StringVar(value='9')
        self.combo(tab,'Section to refine',self.refine_section,list(SLOTS))
        self.combo(tab,'Channels',self.refine_channel,['Unlocked RGB','X / R','Y / G','Z / B'])
        for label,var in [('Range around each value (%)',self.refine_percent),('Range around zero channels (±)',self.refine_zero),('Results (3–24)',self.refine_count)]:
            ttk.Label(tab,text=label).pack(anchor='w');ttk.Entry(tab,textvariable=var).pack(fill='x',pady=(0,6))
        ttk.Label(tab,text='Select a result, then choose “Refine this result” below the preview. Other sections and locked channels remain fixed. Negative values vary by their magnitude; zero uses the explicit range.',wraplength=305).pack(anchor='w',pady=8)
        ttk.Button(controls,text='Recipes / saved sweep settings…',command=self.open_recipes).pack(fill='x',pady=3)
        row=ttk.Frame(panel);row.pack(fill='x',pady=5)
        self.favorite_button=ttk.Button(row,text='☆ Favorite',command=self.toggle_favorite);self.favorite_button.pack(side='left')
        ttk.Button(row,text='Refine this result',command=self.refine_selected).pack(side='left',padx=5)
        menu_button=ttk.Menubutton(row,text='Result tools ▾');menu_button.pack(side='left')
        menu=tk.Menu(menu_button,tearoff=False);menu_button.configure(menu=menu)
        menu.add_command(label='Export favorite JSONs…',command=lambda:self.export_all(favorites_only=True))
        menu.add_command(label='Keep favorites in My skin library',command=self.keep_favorites)
        menu.add_command(label='Save contact sheet — all results…',command=lambda:self.save_sheet(False))
        menu.add_command(label='Save contact sheet — favorites…',command=lambda:self.save_sheet(True))
        menu.add_command(label='Inspect exact differences from baseline',command=self.inspect_difference)

    def capture_recipe(self):
        return validate_recipe(dict(variables={k:getattr(self,k).get() for k in RECIPE_VARS},values=self.values.get('1.0','end-1c'),companion_values=self.companion_values.get('1.0','end-1c'),sections={s:v.get() for s,v in self.selected_sections.items()},locks=self.lock_values(),tab=self.tabs.index(self.tabs.select()),discovery=self.discovery_options()))

    def apply_recipe(self,data):
        if self.future is not None:raise ValueError('Wait for or cancel the current batch before loading a recipe.')
        data=validate_recipe(data)
        for key,value in data['variables'].items():getattr(self,key).set(value)
        for key,value in data['discovery'].items():self.discovery[key].set(value)
        for key in ('values','companion_values'):
            widget=getattr(self,key);widget.delete('1.0','end');widget.insert('1.0',data[key])
        for s in SLOTS:
            self.selected_sections[s].set(data['sections'][s])
            for c in range(3):self.locks[s][c].set(data['locks'][s][c])
            self.sync_lock(s)
        self.tabs.select(data['tab']);self.update_sweep_controls();self.status.set('Recipe loaded onto this lab’s current source skin. Press Run to preview.')

    def open_recipes(self):
        if self.future is not None:self.status.set('Wait for or cancel the current batch before opening recipes.');return
        return PresetBrowser(self.editor,self.window,'recipe',self.capture_recipe,self.apply_recipe)

    def toggle_favorite(self):
        row=self.selected()
        if row is None or row.get('baseline'):self.status.set('Select a result to favorite.');return
        row['favorite']=not row.get('favorite',False)
        index=self.rows.index(row)
        suffix=' — unavailable' if 'error' in row else ' — same pixels' if row.get('metrics',{}).get('same_as') else ''
        self.listing.delete(index);self.listing.insert(index,('★ ' if row['favorite'] else '')+row['label']+suffix);self.listing.selection_set(index);self.show()
        self.status.set('Favorites stay with this batch. Keep them in My skin library or export them before clearing or rerunning.')

    def keep_favorites(self):
        from skin_library import add_documents
        rows=[r for r in self.rows if r.get('favorite') and not r.get('baseline')]
        if not rows:self.status.set('Mark at least one result as a favorite.');return
        try:
            library=add_documents(self.editor.library_rows,[r['doc'] for r in rows])
            for r in library[-len(rows):]:r['favorite']=True;r['tags']=['experiment']
            self.editor.library_rows=library;self.status.set(f'Kept {len(rows)} favorites in My skin library. Save that library to retain them after exit.')
        except ValueError as error:self.status.set(str(error))

    def refine_selected(self):
        if self.future is not None:self.status.set('Wait for or cancel the current batch before refining.');return
        if self.selected() is None:self.status.set('Select a result to refine.');return
        try:doc=self.selected_doc()
        except ValueError as error:self.status.set(str(error));return
        self.source=copy.deepcopy(doc);self.clear();self.tabs.select(2)
        self.source_label.configure(text=self.source_summary())
        self.status.set('Refinement source: '+doc['name']+'. Set the section and range, then Run. The main design is unchanged.')

    def source_summary(self):
        d=self.source
        return f'{d["name"]} • {d["species"]} • Pattern {d["pattern"]+1} • {"Female" if d["female"] else "Male"} • Growth {d["growth"]:.0%} • {"Prime" if d["prime"] else "Standard"} • Variation {d["variation"]:g}'

    def inspect_difference(self):
        row=self.selected()
        if row is None:return
        self.set_details('Exact changes from this batch’s baseline\n\n'+'\n'.join(differences(self.source,row['doc'])))

    def save_sheet(self,favorites=False):
        if self.future is not None:self.status.set('Wait for or cancel the batch before saving its contact sheet.');return
        rows=[r for r in self.rows if not r.get('baseline') and (not favorites or r.get('favorite'))]
        if not rows:self.status.set('No matching results. Mark favorites or run a batch first.');return
        path=filedialog.asksaveasfilename(parent=self.window,title='Save labeled contact sheet',initialdir=output_dir(self.editor),initialfile='Skin experiments.png',defaultextension='.png',filetypes=[('PNG image','*.png')])
        if not path:return
        try:
            from PIL.PngImagePlugin import PngInfo
            context=self.source_summary()+' | '+self.lighting_label+' | Decoded preview'
            image=contact_sheet(rows,context);metadata=PngInfo()
            metadata.add_text('Context',context);metadata.add_text('Assignments',json.dumps([dict(name=r['doc']['name'],assignment=r['label'],favorite=r.get('favorite',False),error=r.get('error')) for r in rows],ensure_ascii=False))
            image.save(path,pnginfo=metadata);self.status.set(f'Saved {len(rows)} labeled results. Full assignment labels are also stored in PNG metadata.')
        except (ValueError,OSError) as error:self.status.set('Contact sheet not saved: '+str(error))
