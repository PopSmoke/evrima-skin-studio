"""Targeted color probes and display-image measurements, not emission claims."""
import copy
import math
import random
from skin_document import validate,finite
from skin_experiments import BODY_SECTIONS,checked_locks,active_channels,finish

METHODS=('Isolated bright channels','Signed channel contrasts','Negative mask pairs','Precision neighbors')
FAMILIES={'Cyan':(.004,1.,1.),'Amber':(1.,.35,.004),'Violet':(.35,.004,1.),'Pink':(1.,.004,.35),'Green':(.004,1.,.08),'Blue':(.004,.08,1.),'Red':(1.,.004,.004),'Lime':(.35,1.,.004)}
RANKINGS=('Vivid color','Bright area','Least white','Interaction strength','Original order')
DEFAULTS=dict(method=METHODS[0],source='b',target='f',family='All families',count='8',seed='2026',level='-9999999',ranking=RANKINGS[0])

def settings(data):
    if not isinstance(data,dict) or set(data)!=set(DEFAULTS):raise ValueError('Invalid discovery settings.')
    if any(not isinstance(v,str) or len(v)>100 for v in data.values()):raise ValueError('Invalid discovery controls.')
    if data['method'] not in METHODS or data['source'] not in BODY_SECTIONS or data['target'] not in BODY_SECTIONS or data['family'] not in ('All families',*FAMILIES) or data['ranking'] not in RANKINGS:raise ValueError('Choose listed discovery settings.')
    limit=8 if data['method'] in METHODS[2:] else 24
    if not 1<=int(data['count'])<=limit:raise ValueError(f'Choose 1–{limit} candidates. Pair methods use three renders per candidate, plus the baseline.')
    int(data['seed']);level=float(data['level'])
    if not finite(level) or not -1e30<=level<0:raise ValueError('Source level must be negative, from -1e30 up to (but not including) zero.')
    return copy.deepcopy(data)

def candidates(source,locks,options):
    validate(source);checked_locks(locks);o=settings(options)
    method=o['method'];target=o['target'];origin=o['source'];count=int(o['count']);level=float(o['level']);rng=random.Random(int(o['seed']))
    channels=active_channels(locks,target,[0,1,2])
    if not channels:raise ValueError('Unlock at least one target channel for discovery.')
    paired=method in METHODS[2:]
    if paired and (origin==target or not active_channels(locks,origin,[0,1,2])):raise ValueError('Pair discovery needs two different body sections with unlocked channels.')
    families=list(FAMILIES) if o['family']=='All families' else [o['family']]
    rng.shuffle(families)
    jobs=[];metadata={}
    def make(i,role,changes):
        colors=copy.deepcopy(source['colors'])
        for s,rgb in changes.items():
            for c in active_channels(locks,s,[0,1,2]):colors[s][c]=rgb[c]
        assignment='; '.join(s+'='+repr(colors[s][:3]) for s in changes)
        label=f'{i+1:02d} {role}: '+assignment
        doc=finish(source,colors,f'{source["name"]} Discovery {i+1:02d} {role}')
        doc['import_notes'].append(method+' | '+assignment)
        jobs.append((label,doc));metadata[label]=dict(group=i,role=role,method=method,order=len(jobs))
    if method==METHODS[3]:
        import numpy as np
        center=np.float32(level);neighbors=[center]
        if center==0:raise ValueError('Choose a precision center that is nonzero in float32.')
        lower=upper=center
        for _ in range(4):
            lower=np.nextafter(lower,np.float32(-math.inf));upper=np.nextafter(upper,np.float32(math.inf));neighbors.extend([lower,upper])
        if not all(math.isfinite(float(x)) for x in neighbors):raise ValueError('Precision probes exceeded the float32 range.')
    for i in range(count):
        family=families[i%len(families)];base=FAMILIES[family]
        if method==METHODS[0]:
            # Raise only the leading channel; keep secondary channels bounded.
            rgb=list(base);peak=max(range(3),key=lambda c:base[c]);rgb[peak]=rng.choice((1.,8.,64.,4096.,1e8,1e22))
            make(i,'Candidate',{target:rgb})
        elif method==METHODS[1]:
            rgb=[v* rng.choice((1.,8.,64.)) for v in base];weak=min(range(3),key=lambda c:base[c]);rgb[weak]=-rng.choice((.004,.35,4.,64.,4096.))
            make(i,'Candidate',{target:rgb})
        else:
            if method==METHODS[3]:
                # One fixed target color isolates changes between float32 neighbors.
                fixed=FAMILIES[o['family']] if o['family']!='All families' else FAMILIES['Cyan']
                rgb=[.004 if v==.004 else v*8 for v in fixed];negative=float(neighbors[i])
            else:
                gain=(.35,1.,8.,16.)[i%4];rgb=[.004 if v==.004 else v*gain for v in base];negative=level
            src=[negative]*3
            make(i,'Source only',{origin:src});make(i,'Target only',{target:rgb});make(i,'Combined',{origin:src,target:rgb})
    return jobs,metadata

def model_mask(images):
    import numpy as np
    arrays=[np.asarray(image.convert('RGB'),dtype=np.float64)/255 for image in images]
    if any(a.shape!=arrays[0].shape for a in arrays):raise ValueError('Discovery comparisons require identical image dimensions.')
    baseline=arrays[0];bg=np.median([baseline[0,0],baseline[0,-1],baseline[-1,0],baseline[-1,-1]],axis=0)
    mask=np.zeros(baseline.shape[:2],dtype=bool)
    for a in arrays:mask|=np.max(abs(a-bg),axis=2)>6/255
    return arrays,mask

def measure(image,baseline):
    import numpy as np
    arrays,mask=model_mask([baseline,image]);a=arrays[1];pixels=a[mask];n=max(1,len(pixels))
    if not len(pixels):return dict(vivid_percent=0.,bright_percent=0.,white_percent=0.,observed_hex=None)
    peak=pixels.max(axis=1);low=pixels.min(axis=1);saturation=(peak-low)/np.maximum(peak,1e-10)
    vivid=(peak>=.75)&(saturation>=.5);white=(pixels>.92).all(axis=1)
    linear=np.where(pixels<=.04045,pixels/12.92,((pixels+.055)/1.055)**2.4)
    bright=linear@np.array([.2126,.7152,.0722])>.55
    color=pixels[vivid].mean(axis=0) if vivid.any() else None
    return dict(vivid_percent=float(vivid.sum()*100/n),bright_percent=float(bright.sum()*100/n),white_percent=float(white.sum()*100/n),observed_hex=None if color is None else '#'+''.join(f'{int(v*255+.5):02X}' for v in color))

def interaction(baseline,source_only,target_only,combined):
    import numpy as np
    arrays,mask=model_mask([baseline,source_only,target_only,combined]);b,s,t,c=arrays
    residual=np.max(abs((c-s)-(t-b)),axis=2)
    return float(((residual>8/255)&mask).sum()*100/max(1,mask.sum()))

def score_row(row,rows,baseline):
    if baseline is None or 'image' not in row:return
    row['discovery_score']=measure(row['image'],baseline)
    if row.get('role')=='Combined':
        controls={r.get('role'):r for r in rows if r.get('group')==row.get('group') and 'image' in r}
        if all(k in controls for k in ('Source only','Target only')):
            row['discovery_score']['interaction_percent']=interaction(baseline,controls['Source only']['image'],controls['Target only']['image'],row['image'])

def rank_key(row,ranking):
    if row.get('baseline'):return (0,0,0)
    score=row.get('discovery_score',{});role=row.get('role')
    category=1 if role in ('Candidate','Combined') and score else 2
    if ranking=='Original order':return (0,row.get('order',0),0)
    value={'Vivid color':score.get('vivid_percent',-1)-.5*score.get('white_percent',0),'Bright area':score.get('bright_percent',-1),'Least white':-score.get('white_percent',101),'Interaction strength':score.get('interaction_percent',-1)}[ranking]
    return (category,-value,row.get('order',0))
