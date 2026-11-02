"""On-demand discovery controls for the existing Experiment Lab worker."""
import copy
import tkinter as tk
from tkinter import ttk,filedialog
from skin_experiments import BODY_SECTIONS
from skin_discovery import METHODS,FAMILIES,RANKINGS,DEFAULTS,rank_key,settings
from skin_workflow import write_json
from skin_workflow_ui import output_dir

class DiscoveryUI:
    def setup_discovery(self):
        tab=ttk.Frame(self.tabs,padding=10);self.tabs.add(tab,text='Discover')
        self.discovery={k:tk.StringVar(value=v) for k,v in DEFAULTS.items()}
        self.discovery_batch={};self.discovery_meta={};self.discovery_locks={}
        for label,key,choices in [('Method','method',METHODS),('Negative source (pair methods)','source',BODY_SECTIONS),('Color target','target',BODY_SECTIONS),('Color family','family',('All families',*FAMILIES))]:self.combo(tab,label,self.discovery[key],choices)
        for label,key in [('Candidates (pairs: 1–8; other methods: 1–24)','count'),('Repeatable seed','seed'),('Negative source level / precision center','level')]:
            ttk.Label(tab,text=label,wraplength=305).pack(anchor='w');ttk.Entry(tab,textvariable=self.discovery[key]).pack(fill='x',pady=(0,5))
        self.combo(tab,'Rank completed previews by',self.discovery['ranking'],RANKINGS)
        ttk.Button(tab,text='Rank completed results',command=self.rank_discovery).pack(fill='x',pady=4)
        ttk.Button(tab,text='Save findings JSON…',command=self.save_findings).pack(fill='x',pady=4)
        ttk.Label(tab,text='Try new combinations on this design. Locked colors and eyes stay unchanged. Paired tests show each change alone and together.',wraplength=305).pack(anchor='w',pady=6)
        ttk.Label(tab,text='Vivid favors strong color. Interaction finds combinations that change one another. Results describe these previews, not in-game glow.',wraplength=305).pack(anchor='w',pady=6)

    def discovery_options(self):return settings({k:v.get() for k,v in self.discovery.items()})

    def rank_discovery(self):
        if self.future is not None:self.status.set('Wait for or cancel the batch before ranking.');return
        if not self.discovery_batch or not self.rows:self.status.set('Run a Discover batch first.');return
        chosen=self.selected();ranking=self.discovery['ranking'].get()
        self.rows.sort(key=lambda r:rank_key(r,ranking));self.listing.delete(0,'end')
        for row in self.rows:
            suffix=' — unavailable' if 'error' in row else ' — same pixels' if row.get('metrics',{}).get('same_as') else ''
            self.listing.insert('end',('★ ' if row.get('favorite') else '')+row['label']+suffix)
        if chosen is not None:
            index=next(i for i,r in enumerate(self.rows) if r is chosen);self.listing.selection_set(index);self.show()
        self.status.set('Ranked by '+ranking+'. Baseline first, scored candidates next, controls last. Percentages describe this preview, not glow strength.')

    def discovery_lines(self,row):
        score=row.get('discovery_score')
        if score is None:return []
        lines=[f'Visible-image estimate: vivid {score["vivid_percent"]:.2f}% | bright {score["bright_percent"]:.2f}% | near-white {score["white_percent"]:.2f}%.']
        if score.get('observed_hex'):lines.append('Average vivid preview color: '+score['observed_hex']+' (display sample, not an import value).')
        if 'interaction_percent' in score:lines.append(f'Four-state interaction response: {score["interaction_percent"]:.1f}% of estimated model pixels (>8/255). Includes clipping/lighting effects; not proof of a separate shader.')
        if row.get('role')=='Combined' and 'interaction_percent' not in score:lines.append('Interaction unmeasured: one or more control previews are unavailable.')
        return lines

    def save_findings(self):
        if self.future is not None:self.status.set('Wait for or cancel the batch before saving findings.');return
        if not self.discovery_batch or not self.rows:self.status.set('Run a Discover batch first.');return
        path=filedialog.asksaveasfilename(parent=self.window,title='Save discovery findings',initialdir=output_dir(self.editor),initialfile='Color discovery findings.json',defaultextension='.json',filetypes=[('Findings JSON','*.json')])
        if not path:return
        try:
            data=dict(format='skin-studio-discovery-findings',version=1,source=copy.deepcopy(self.source),settings=self.discovery_batch,lighting=self.lighting_label,bake_size=self.batch_size,camera=dict(yaw=-65,pitch=12,width=520,height=325),completed_candidates=sum(r.get('role') in ('Candidate','Combined') for r in self.rows),stopped=self.stopping,limits='Decoded preview only. Approximate visible model mask. Metrics include lighting, sampling and clipping. No emitted light or live-game match established.',results=[dict(label=r['label'],role=r.get('role','Baseline'),group=r.get('group'),favorite=r.get('favorite',False),document=r['doc'],score=r.get('discovery_score'),comparison=r.get('metrics'),error=r.get('error')) for r in self.rows])
            data['locks']=copy.deepcopy(self.discovery_locks)
            data['thresholds']=dict(vivid_max_rgb_at_least=.75,vivid_saturation_at_least=.5,near_white_all_rgb_above=.92,bright_linear_luminance_above=.55,interaction_display_difference_above=8/255,background_distance_above=6/255)
            write_json(path,data);self.status.set('Saved exact colors, settings, scores and control references. Export individual skins with Export selected JSON.')
        except (OSError,ValueError) as error:self.status.set('Findings not saved: '+str(error))
