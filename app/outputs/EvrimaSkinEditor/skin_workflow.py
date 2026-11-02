"""Small metadata-only workflow helpers; no new runtime or asset dependencies."""
import copy
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid
from skin_document import SLOTS, validate, finite, export_filename
from skin_experiments import checked_locks, active_channels, finish, SWEEP_MODES, STYLES, parse_sweep
from skin_library import tags_from_text

CHANNELS = ('Unlocked RGB', 'X / R', 'Y / G', 'Z / B')
RECIPE_VARS = ('section','channel','sweep_mode','companion','companion_channel','style','scope','count','seed','minimum','maximum','amount','quality','refine_section','refine_channel','refine_percent','refine_zero','refine_count')
PROFILES = ('Raw JSON (finite numbers)', 'Importer range ±1e23', 'Conventional colors 0–1', 'Custom range')
MAX_BYTES = 2 * 1024 * 1024

def write_json(path, data):
    payload=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    if len(payload.encode('utf-8'))>MAX_BYTES:raise ValueError('Settings exceed 2 MB. Save a smaller collection.')
    path=Path(path);temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.'+path.name+'.',suffix='.tmp',delete=False) as f:
            temporary=Path(f.name);f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)

def read_json(path):
    from skin_document import raw_number
    path=Path(path)
    if path.stat().st_size>MAX_BYTES:raise ValueError('Settings exceed 2 MB.')
    return json.loads(path.read_text(encoding='utf-8-sig'),parse_float=raw_number)

def validate_recipe(data):
    required={'variables','values','companion_values','sections','locks','tab'}
    if not isinstance(data,dict) or not required<=set(data) or set(data)-required-{'discovery'}:raise ValueError('Invalid experiment recipe.')
    from skin_discovery import settings,DEFAULTS
    data=copy.deepcopy(data);data['discovery']=settings(data.get('discovery',DEFAULTS))
    v=data['variables']
    if not isinstance(v,dict) or set(v)!=set(RECIPE_VARS) or any(not isinstance(x,str) or len(x)>100 for x in v.values()):raise ValueError('Invalid recipe controls.')
    for name,allowed in [('section',SLOTS),('refine_section',SLOTS),('channel',CHANNELS),('refine_channel',CHANNELS),('companion_channel',CHANNELS),('companion',(*SLOTS,'')),('sweep_mode',SWEEP_MODES),('style',STYLES),('scope',('One section','2–3 sections','All unlocked')),('quality',('256','512'))]:
        if v[name] not in allowed:raise ValueError('Invalid recipe '+name+'.')
    for name in ('values','companion_values'):
        if not isinstance(data[name],str) or len(data[name])>3000:raise ValueError('Invalid sweep list.')
        parse_sweep(data[name])
    if not isinstance(data['sections'],dict) or set(data['sections'])!=set(SLOTS) or any(type(x)is not bool for x in data['sections'].values()):raise ValueError('Invalid section selection.')
    checked_locks(data['locks'])
    if type(data['tab'])is not int or data['tab'] not in (0,1,2,3):raise ValueError('Invalid recipe tab.')
    if not 1<=int(v['count'])<=24 or not 3<=int(v['refine_count'])<=24:raise ValueError('Invalid result count.')
    int(v['seed'])
    if not -12<=int(v['minimum'])<=int(v['maximum'])<=30:raise ValueError('Invalid variation powers.')
    for key in ('amount','refine_percent'):
        if not 0<float(v[key])<=100:raise ValueError('Percent must be greater than zero and at most 100.')
    if not finite(float(v['refine_zero'])) or float(v['refine_zero'])<=0:raise ValueError('Zero-channel span must be positive and finite.')
    return copy.deepcopy(data)

def validate_presets(rows):
    if not isinstance(rows,list) or len(rows)>200:raise ValueError('Keep at most 200 presets per collection.')
    identities=set()
    for r in rows:
        if not isinstance(r,dict) or set(r)!={'id','name','tags','favorite','kind','data'}:raise ValueError('Invalid preset.')
        if not isinstance(r['id'],str) or not r['id'] or len(r['id'])>80 or r['id'] in identities:raise ValueError('Invalid preset identity.')
        identities.add(r['id'])
        if not isinstance(r['name'],str) or not r['name'].strip() or len(r['name'])>120:raise ValueError('Preset names need 1–120 characters.')
        if type(r['favorite'])is not bool or not isinstance(r['tags'],list) or not all(isinstance(t,str) for t in r['tags']) or tags_from_text(','.join(r['tags']))!=r['tags']:raise ValueError('Invalid tags or favorite.')
        if r['kind']=='recipe':validate_recipe(r['data'])
        elif r['kind']=='colors':
            if not isinstance(r['data'],dict) or set(r['data'])!={'colors','default_eyes'} or type(r['data']['default_eyes'])is not bool:raise ValueError('Invalid color preset.')
            validate_colors(r['data']['colors'])
        else:raise ValueError('Unknown preset kind.')
    return copy.deepcopy(rows)

def validate_colors(colors):
    if not isinstance(colors,dict) or set(colors)!=set(SLOTS):raise ValueError('All seven color sections are required.')
    for c in colors.values():
        parse_slot(c)
        if len(c)!=4:raise ValueError('Color presets require four channels per section.')
    return colors

def preset_collection(rows):return dict(format='skin-studio-presets',version=1,presets=validate_presets(rows))
def load_presets(data):
    if not isinstance(data,dict) or data.get('format')!='skin-studio-presets' or data.get('version')!=1:raise ValueError('Choose a Studio preset collection.')
    return validate_presets(data.get('presets'))

def add_preset(rows,name,tags,kind,data):
    return validate_presets([*rows,dict(id=uuid.uuid4().hex,name=name.strip(),tags=tags_from_text(tags),favorite=False,kind=kind,data=copy.deepcopy(data))])

def parse_slot(value):
    if isinstance(value,str):
        if len(value)>4096:raise ValueError('Color text is too long.')
        from skin_document import raw_number
        try:value=json.loads(value,parse_float=raw_number)
        except ValueError:
            from skin_document import raw_number
            value=[raw_number(x) for x in value.split(',')]
    if not isinstance(value,list) or len(value) not in (3,4) or not all(finite(v) for v in value):raise ValueError('Paste three or four finite numbers: R, G, B[, A].')
    return list(value)

def paste_slot(doc,section,text,include_alpha=False):
    result=copy.deepcopy(validate(doc));color=parse_slot(text)
    result['colors'][section][:3]=color[:3]
    if include_alpha and len(color)==4:result['colors'][section][3]=color[3]
    if section=='e':result['default_eyes']=False
    return validate(result)

def differences(a,b):
    validate(a);validate(b);lines=[]
    for key in ('name','species','pattern','female','growth','prime','variation','default_eyes','extra_overrides'):
        if a.get(key)!=b.get(key):lines.append(f'{key}: {a.get(key)!r} → {b.get(key)!r}')
    for s,(label,*_) in SLOTS.items():
        for i,c in enumerate('RGBA'):
            x,y=a['colors'][s][i],b['colors'][s][i]
            if x!=y:lines.append(f'{label} ({s}) {c}: {x!r} → {y!r}')
    return lines or ['No color or model-setting differences.']

def preflight(doc,profile=PROFILES[0],minimum='0',maximum='1'):
    validate(doc)
    if profile not in PROFILES:raise ValueError('Choose an export profile.')
    bounds=None
    if profile==PROFILES[1]:bounds=(-1e23,1e23)
    elif profile==PROFILES[2]:bounds=(0,1)
    elif profile==PROFILES[3]:
        bounds=(float(minimum),float(maximum))
        if not all(finite(v) for v in bounds) or bounds[0]>bounds[1]:raise ValueError('Custom minimum and maximum must be finite and ordered.')
    notes=[]
    for s,color in doc['colors'].items():
        for c,v in zip('RGBA',color):
            if bounds and not bounds[0]<=v<=bounds[1]:notes.append(f'{s}.{c} = {v!r} is outside {bounds[0]:g} to {bounds[1]:g}.')
    filename=export_filename(doc['name'])
    desired=doc['name'] if doc['name'].lower().endswith('.json') else doc['name']+'.json'
    if filename!=desired:notes.append('Filename will be sanitized to '+filename)
    if len(filename)>180:notes.append('Long filename: shorten the design name if the destination rejects it.')
    if doc.get('default_eyes'):notes.append('Original eyes are enabled; export uses the current species eye defaults.')
    return [f'Profile: {profile}',f'Filename: {filename}',*(notes or ['No range or filename issues found.']), 'Compact skin JSON carries colors, not dinosaur/model settings. Profiles are numeric checks, not a guarantee that a server accepts the file. Values are never changed.']

def refine_sweep(source,locks,section,channels,percent=10.,count=9,zero_span=.01):
    validate(source);checked_locks(locks)
    active=active_channels(locks,section,channels)
    if not active:raise ValueError('Unlock a selected channel before refining.')
    if type(count)is not int or not 3<=count<=24 or not finite(percent) or not 0<percent<=100 or not finite(zero_span) or zero_span<=0:raise ValueError('Use 3–24 results, 0–100% (excluding zero), and a positive finite zero-channel span.')
    rows=[]
    for i in range(count):
        position=2*i/(count-1)-1;colors=copy.deepcopy(source['colors'])
        for c in active:
            old=colors[section][c];new=old+position*(abs(old)*(percent/100) if old else zero_span)
            if not finite(new):raise ValueError('Refinement exceeds finite storage; reduce the percentage.')
            colors[section][c]=new
        label=section+' '+', '.join('XYZ'[c]+'='+repr(colors[section][c]) for c in active)
        doc=finish(source,colors,f'{source["name"]} Refined {i+1:02d}')
        doc['import_notes'].append('Refined result: '+label);rows.append((label,doc))
    return rows

def contact_sheet(rows,context):
    from PIL import Image,ImageDraw,ImageFont
    import textwrap
    if not rows or len(rows)>24:raise ValueError('Choose 1–24 results for the contact sheet.')
    try:
        face=str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/segoeui.ttf')
        font=ImageFont.truetype(face,15);small=ImageFont.truetype(face,12)
    except OSError:font=ImageFont.load_default(size=15);small=ImageFont.load_default(size=12)
    width,height=420,345;cols=min(3,len(rows));sheet=Image.new('RGB',(cols*width,90+math.ceil(len(rows)/cols)*height),'#eef2f5');draw=ImageDraw.Draw(sheet)
    draw.text((14,10),'Skin Studio — Experiment contact sheet',font=font,fill='#15212c')
    draw.text((14,35),'\n'.join(textwrap.wrap(context,cols*50)[:3]),font=small,fill='#263d50')
    for i,row in enumerate(rows):
        x=(i%cols)*width;y=90+(i//cols)*height
        if row.get('image') is not None:
            image=row['image'].convert('RGB');image.thumbnail((400,250));sheet.paste(image,(x+10+(400-image.width)//2,y))
        else:draw.text((x+12,y+80),'Preview unavailable',font=font,fill='#7b2525')
        label=('* ' if row.get('favorite') else '')+row['doc']['name']
        draw.text((x+10,y+252),'\n'.join(textwrap.wrap(label,48)[:2]),font=font,fill='#15212c')
        draw.text((x+10,y+293),'\n'.join(textwrap.wrap(row['label'],57)[:3]),font=small,fill='#263d50')
    return sheet

def validate_preferences(data):
    from skin_lighting import PRESETS,DIRECTIONS
    if not isinstance(data,dict) or data.get('format')!='skin-studio-workspace' or data.get('version')!=1:raise ValueError('Invalid workspace preferences.')
    if data.get('quality') not in ('256','512','1024') or data.get('light_preset') not in PRESETS or data.get('light_direction') not in DIRECTIONS:raise ValueError('Invalid quality or lighting preference.')
    if not finite(data.get('light_strength')) or not 0<=data['light_strength']<=2:raise ValueError('Invalid light strength.')
    if not isinstance(data.get('geometry'),str) or not re.fullmatch(r'\d{3,5}x\d{3,5}[+-]\d{1,6}[+-]\d{1,6}',data['geometry']):raise ValueError('Invalid window layout.')
    if not isinstance(data.get('export_folder'),str) or len(data['export_folder'])>1000:raise ValueError('Invalid export folder.')
    if type(data.get('remember'))is not bool:raise ValueError('Invalid workspace setting.')
    return copy.deepcopy(data)

def capture_preferences(editor):
    return validate_preferences(dict(format='skin-studio-workspace',version=1,remember=editor.remember_workspace,geometry=editor.root.geometry(),quality=editor.quality.get(),light_preset=editor.light_preset.get(),light_direction=editor.light_direction.get(),light_strength=float(editor.light_strength.get()),export_folder=editor.export_folder))

def load_workspace(editor):
    if not editor.preferences_path.exists():return
    try:
        data=validate_preferences(read_json(editor.preferences_path))
        if not data['remember']:return
        editor.remember_workspace=True;editor.export_folder=data['export_folder']
        editor.quality.set(data['quality']);editor.light_preset.set(data['light_preset']);editor.light_direction.set(data['light_direction']);editor.light_strength.set(str(data['light_strength']))
        # Clamp to the current screen so moving a portable install cannot hide it.
        w,h,x,y=map(int,re.fullmatch(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)',data['geometry']).groups())
        sw,sh=editor.root.winfo_screenwidth(),editor.root.winfo_screenheight()
        w,h=max(1150,min(w,sw)),max(820,min(h,sh))
        x,y=max(0,min(x,max(0,sw-w))),max(0,min(y,max(0,sh-h)))
        editor.root.geometry(f'{w}x{h}+{x}+{y}')
        editor.change_lighting()
    except (ValueError,OSError,TypeError,KeyError) as error:editor.status.set('Workspace preferences ignored: '+str(error))
