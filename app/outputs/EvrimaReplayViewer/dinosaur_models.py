"""Owned species geometry and native growth rules for replay and inspection."""
from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import zipfile
import numpy as np
from mesh_renderer import Mesh

HERE=Path(__file__).resolve().parent

def clamp(value):return max(0.,min(1.,value))

def curve_value(keys,time):
    if not math.isfinite(time):raise ValueError('Nonfinite growth')
    return float(np.interp(time,np.asarray(keys)[:,0],np.asarray(keys)[:,1]))

def morph_weights(profile,growth,prime=False):
    if not math.isfinite(growth) or not 0<=growth<=1:raise ValueError('Growth outside the recovered range')
    visual=curve_value(profile['visual_growth'],growth)
    progress=clamp(2*visual-.5)
    hatchling=growth<.25
    if profile['has_subadult']:
        juvenile=1. if hatchling else clamp(1.-2*progress)
        subadult=0. if hatchling else clamp(1.-abs(1.-2*progress))
    else:juvenile=clamp(1.-progress);subadult=0.
    weights={'juvenile':juvenile,'subadult':subadult}
    if 'hatchling' in profile['morph_names']:
        weights['hatchling']=clamp(1.-4*growth) if hatchling else 0.
        if hatchling:weights['juvenile']=clamp(4*growth)
    if profile['has_elder']:
        weights['elder']=max(0.,min(1. if prime and growth>.75 else .2,(growth-.75)*4))
    return {k:v for k,v in weights.items() if k in profile['morph_names']}

class DinosaurModels:
    def __init__(self,root=HERE):
        self.root=Path(root);path=self.root/'dinosaur-models.json'
        if path.stat().st_size>128*1024:raise ValueError('Dinosaur catalog exceeds limit')
        catalog=json.loads(path.read_text(encoding='utf-8'))
        if catalog.get('format')!='evrima-dinosaur-models-1':raise ValueError('Unsupported dinosaur catalog')
        self.profiles=catalog['profiles'];self.meshes={};self.morphs={};self.cache=OrderedDict()
        if not self.profiles or len(self.profiles)>64:raise ValueError('Invalid species count')
        for name,p in self.profiles.items():
            for key in ('mesh','morphs'):
                file=p[key]
                if not isinstance(file,str) or Path(file).name!=file or '/' in file or '\\' in file:raise ValueError('Invalid dinosaur asset path')
            for key in ('visual_growth','scale_standard','scale_prime'):
                points=np.asarray(p[key],dtype=float)
                if points.ndim!=2 or points.shape[1]!=2 or not 1<=len(points)<=256 or not np.isfinite(points).all() or np.any(np.diff(points[:,0])<=0):raise ValueError('Invalid dinosaur curve')
                if key.startswith('scale') and (np.any(points[:,1]<=0) or np.any(points[:,1]>10)):raise ValueError('Invalid size curve')
            for key in ('relative_location','relative_rotation'):
                v=np.asarray(p[key],dtype=float)
                if v.shape!=(3,) or not np.isfinite(v).all():raise ValueError('Invalid mesh transform')

    def mesh(self,species):
        if species not in self.profiles:return None
        if species not in self.meshes:
            p=self.profiles[species];path=self.root/p['mesh']
            if path.stat().st_size>64*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=p['mesh_sha256']:raise ValueError('Dinosaur mesh digest mismatch')
            mesh=Mesh(path);path=self.root/p['morphs']
            if path.stat().st_size>16*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=p['morphs_sha256']:raise ValueError('Dinosaur morph digest mismatch')
            with zipfile.ZipFile(path) as archive:
                if len(archive.infolist())>8 or sum(z.file_size for z in archive.infolist())>64*1024*1024:raise ValueError('Dinosaur morph data exceeds limit')
            with np.load(path,allow_pickle=False) as data:
                if set(data.files)!=set(p['morph_names']):raise ValueError('Dinosaur morph names differ')
                targets={k:data[k].astype(np.float64) for k in data.files}
            if any(a.shape!=mesh.positions.shape or not np.isfinite(a).all() for a in targets.values()):raise ValueError('Invalid dinosaur morph geometry')
            self.meshes[species]=mesh;self.morphs[species]=targets
        return self.meshes[species]

    def shape(self,species,growth,prime=None):
        mesh=self.mesh(species);p=self.profiles[species]
        if growth is None:
            return mesh.positions,1.,dict(growth=None,size_source='Growth not recorded; reference size',prime=None,morph_weights={})
        if not math.isfinite(growth) or not 0<=growth<=1:
            return mesh.positions,1.,dict(growth=growth,size_source='Growth outside supported range; reference size',prime=None,morph_weights={})
        if prime not in (None,False,True):raise ValueError('Invalid prime elder state')
        key=(species,float(growth),prime)
        if key in self.cache:
            value=self.cache.pop(key);self.cache[key]=value;return value
        weights=morph_weights(p,growth,prime is True)
        positions=mesh.positions.copy()
        for name,weight in weights.items():positions+=self.morphs[species][name]*weight
        size=curve_value(p['scale_prime' if prime is True and growth>.75 else 'scale_standard'],growth)
        alternate=curve_value(p['scale_prime'],growth)
        uncertain=prime is None and growth>.75 and (abs(size-alternate)>1e-7 or 'elder' in weights)
        info=dict(growth=growth,scale=size,prime=prime,morph_weights=weights,
            size_source='Standard elder preview; prime status unknown' if uncertain else 'Recovered growth curve',
            prime_scale=alternate if uncertain else None)
        value=(positions,size,info);self.cache[key]=value
        if len(self.cache)>64:self.cache.popitem(last=False)
        return value

    def place(self,species,positions,location,rotation,scale):
        p=self.profiles[species]
        def rotation_matrix(rot):
            pitch,yaw,roll=[math.radians(float(a)) for a in rot]
            sp,cp=math.sin(pitch),math.cos(pitch);sy,cy=math.sin(yaw),math.cos(yaw);sr,cr=math.sin(roll),math.cos(roll)
            return np.array([[cp*cy,sr*sp*cy-cr*sy,-cr*sp*cy-sr*sy],[cp*sy,sr*sp*sy+cr*cy,-cr*sp*sy+sr*cy],[sp,-sr*cp,cr*cp]])
        local=(np.asarray(positions)@rotation_matrix(p['relative_rotation']).T+np.asarray(p['relative_location']))*scale
        return local@rotation_matrix(rotation).T+np.asarray(location)
