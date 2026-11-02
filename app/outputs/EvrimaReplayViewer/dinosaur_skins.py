"""Recovered clean body colors; original lighting and later effects remain previews."""
from collections import OrderedDict
import hashlib,json,math,re,struct
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
from skin_color_kernel import color

HERE=Path(__file__).resolve().parent

def linear_to_srgb(value):
    x=np.clip(value,0,1)
    return np.where(x<=.0031308,x*12.92,1.055*np.power(x,1/2.4)-.055)

def preshader(payload,parameters):
    data=bytes.fromhex(payload);at=0;stack=[]
    def read(fmt):
        nonlocal at
        size=struct.calcsize(fmt)
        if at+size>len(data):raise ValueError('Truncated skin expression')
        result=struct.unpack_from(fmt,data,at);at+=size;return result
    while at<len(data):
        op=read('<B')[0]
        if op==2:
            count=read('<B')[0]
            if count not in (1,2,3,4):raise ValueError('Invalid skin constant')
            stack.append(np.array(read('<'+'f'*count),np.float32))
        elif op==3:stack.append(np.asarray(parameters[read('<H')[0]],np.float32))
        elif op in (4,5,6,7):
            right=stack.pop();left=stack.pop();stack.append({4:np.add,5:np.subtract,6:np.multiply,7:np.divide}[op](left,right))
        elif op==23:stack.append(np.reciprocal(stack.pop()))
        elif op==26:stack.append(np.clip(stack.pop(),0,1))
        elif op==37:
            count,*components=read('<B4b');value=stack.pop()
            if count not in (1,2,3,4) or any(c<0 or c>=value.size for c in components[:count]):raise ValueError('Invalid skin swizzle')
            stack.append(value[components[:count]])
        else:raise ValueError('Unsupported skin expression')
    if len(stack)!=1 or not np.isfinite(stack[0]).all():raise ValueError('Invalid skin expression result')
    return stack[0]

def bilinear(image,u,v):
    height,width=image.shape[:2];x=np.mod(u,1)*width-.5;y=np.mod(v,1)*height-.5
    ix=np.floor(x).astype(np.int32);iy=np.floor(y).astype(np.int32);fx=(x-ix)[...,None];fy=(y-iy)[...,None]
    top=image[iy%height,ix%width]*(1-fx)+image[iy%height,(ix+1)%width]*fx
    bottom=image[(iy+1)%height,ix%width]*(1-fx)+image[(iy+1)%height,(ix+1)%width]*fx
    return np.moveaxis(np.asarray(top*(1-fy)+bottom*fy,dtype=np.float32),-1,0)

class DinosaurSkins:
    def __init__(self,root=HERE):
        self.root=Path(root);path=self.root/'skin-library.json'
        if path.stat().st_size>1024*1024:raise ValueError('Skin library exceeds limit')
        self.data=json.loads(path.read_text(encoding='utf-8'))
        if self.data.get('format')!='evrima-skin-library-1':raise ValueError('Unsupported skin library')
        if hashlib.sha256((self.root/'skin_color_kernel.py').read_bytes()).hexdigest()!=self.data['kernel_sha256']:raise ValueError('Skin color code digest mismatch')
        self.profiles=self.data['profiles'];self.images=OrderedDict();self.cache=OrderedDict();self.geometry={}
        self.srgb=np.asarray(self.data['native_srgb'],np.float32)
        if self.srgb.shape!=(256,) or not np.isfinite(self.srgb).all():raise ValueError('Invalid skin color table')
        self.eyes=DinosaurEyes(self.root,self.srgb)
        from dinosaur_surface import SurfaceLibrary
        self.surfaces=SurfaceLibrary(self.root)

    def decode(self,species,code):
        if species not in self.profiles:raise ValueError('Species skin is not recovered')
        if not isinstance(code,str) or len(code)>256 or not code.startswith(species):raise ValueError('Skin code species mismatch')
        rest=code[len(species):]
        if len(rest)<3 or not re.fullmatch(r'[0-9]{3}[0-9a-fA-F]+',rest):raise ValueError('Invalid skin code')
        pattern,variation,theme=map(int,rest[:3]);patterns=self.profiles[species]['patterns']
        if pattern>=len(patterns) or theme>=len(patterns[pattern]['themes']):raise ValueError('Unsupported skin pattern or theme')
        names=patterns[pattern]['themes'][theme]['sections'];encoded=rest[3:]
        if len(encoded)!=8*len(names):raise ValueError('Skin code color count mismatch')
        chunks=[encoded[i:i+8].upper() for i in range(0,len(encoded),8)][::-1];sections=[];overrides={}
        for name,value in zip(names,chunks):
            rgba=list(bytes.fromhex(value));linear=[float(self.srgb[v]) for v in rgba[:3]]+[rgba[3]/255]
            parameter=self.data['section_parameters'].get(name)
            if parameter is None:raise ValueError('Unsupported skin color section')
            overrides[parameter]=linear;sections.append(dict(name=name,hex=value,linear=linear,parameter=parameter))
        return dict(species=species,pattern=pattern,theme=theme,variation_index=variation,sections=sections,overrides=overrides,code=code)

    def image(self,package):
        if package in self.images:
            value=self.images.pop(package);self.images[package]=value;return value
        row=self.data['textures'][package];path=self.root/row['file']
        if path.resolve().parent!=(self.root/'dinosaur-textures').resolve() or path.suffix!='.png':raise ValueError('Invalid skin texture path')
        if path.stat().st_size>8*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Skin texture digest mismatch')
        with Image.open(path) as source:
            if list(source.size)!=row['size'] or max(source.size)>2048:raise ValueError('Skin texture dimensions differ')
            pixels=np.asarray(source.convert('RGBA'))
        value=pixels.astype(np.float32)/255
        if row['srgb']:value[:,:,:3]=self.srgb[pixels[:,:,:3]]
        self.images[package]=value
        if len(self.images)>20:self.images.popitem(last=False)
        return value

    def uniforms(self,species,growth,female,variation,decoded=None):
        values=dict(self.profiles[species]['defaults'])
        if decoded is not None:values.update(decoded['overrides'])
        values.update(GrowthAmount=max(0.,min(1.,2*growth-.5)),IsFemale=float(female),SkinNoiseTiling=variation)
        params=[np.atleast_1d(np.asarray(values.get(p['name'],p['default']),np.float32)) for p in self.data['numeric_parameters']]
        cb=np.zeros(88,np.float32)
        for program in self.data['preshaders']:
            result=preshader(program['bytecode'],params)
            if len(program['fields'])!=1:raise ValueError('Unsupported skin uniform fields')
            offset,component,size=program['fields'][0]
            if component!=0 or len(result)!=size or offset+size>88:raise ValueError('Invalid skin uniform output')
            cb[offset:offset+size]=result
        return cb.reshape(22,4)

    def bake(self,species,growth,female,variation,decoded=None,pattern=0,size=512):
        if species not in self.profiles or not math.isfinite(growth) or not 0<=growth<=1 or female not in (False,True):raise ValueError('Unsupported skin state')
        if not math.isfinite(variation) or not 0<=variation<=128 or size not in (128,256,512,1024):raise ValueError('Unsupported skin preview settings')
        pattern=decoded['pattern'] if decoded is not None else pattern
        profile=self.profiles[species];selected=profile['patterns'][pattern];textures=selected['textures']
        packages={6:profile['textures']['Base_Mask'],10:self.data['common_textures']['growth_noise'],11:profile['textures']['Base_RoughAlbedoCavityMap'],
            12:textures['AdultTexture'],13:textures['JuvenileTexture'],14:textures['HatchlingTexture'],15:self.data['common_textures']['skin_noise']}
        images={slot:self.image(package) for slot,package in packages.items()};cb=self.uniforms(species,growth,female,variation,decoded)
        axis=(np.arange(size,dtype=np.float32)+.5)/size;u,v=np.meshgrid(axis,axis)
        def sample(slot,x,y):return bilinear(images[slot],x,y)
        with np.errstate(divide='ignore',invalid='ignore'):rgb=color(sample,cb,u,v)
        if rgb.shape!=(size,size,3) or not np.isfinite(rgb).all():raise ValueError('Invalid rendered skin colors')
        out=np.empty((size,size,4),np.uint8);out[:,:,:3]=np.rint(linear_to_srgb(rgb)*255).astype(np.uint8);out[:,:,3]=255
        return out

    def body_geometry(self,mesh,species):
        if species not in self.geometry:
            uvs=np.asarray(mesh.data['uvs'],np.float32)
            channels=mesh.data['uv_channels']
            if uvs.shape==(len(mesh.positions)*channels,2):uvs=uvs.reshape(len(mesh.positions),channels,2)[:,0,:]
            if uvs.shape!=(len(mesh.positions),2) or not np.isfinite(uvs).all():raise ValueError('Invalid skin mesh UVs')
            body=[];other=[]
            for section in mesh.data['sections']:
                start=section['base_index'];end=start+section['triangles']*3
                (body if section['material']==0 else other).extend(mesh.indices[start:end])
            if len(body)+len(other)!=len(mesh.indices):raise ValueError('Skin section coverage mismatch')
            colors=np.ones_like(mesh.colors)
            packed=bytes.fromhex(mesh.data['tangent_bytes_hex'])
            high=mesh.data['high_precision_tangents']
            stride=16 if high else 8
            if len(packed)!=len(mesh.positions)*stride:raise ValueError('Invalid packed dinosaur tangents')
            tangents=np.frombuffer(packed,dtype='<i2' if high else 'i1').reshape(-1,8)
            source_normals=np.ascontiguousarray(np.maximum(tangents[:,4:7].astype(np.float32)/(32767 if high else 127),-1))
            for section in mesh.data['sections']:
                if section['material']==0:colors[section['base_vertex']:section['base_vertex']+section['vertices']]=1
            self.geometry[species]=dict(positions=mesh.positions,normals=mesh.normals,colors=np.ascontiguousarray(colors),
                indices=np.ascontiguousarray(other,np.uint32),skin_uv=np.ascontiguousarray(uvs),skin_indices=np.ascontiguousarray(body,np.uint32),wet_source_normals=source_normals)
        return self.geometry[species]

    def neutral_surface(self,mesh,species):
        """Show condition maps over the viewer's neutral color, without inventing a skin code."""
        geometry=dict(self.body_geometry(mesh,species))
        geometry['colors']=mesh.colors
        if not hasattr(self,'neutral_color'):
            pixels=np.empty((128,128,4),np.uint8)
            pixels[:]=[110,148,163,255]
            self.neutral_color=pixels
        return SimpleNamespace(**geometry,skin_texture=self.neutral_color,surface=self.surfaces.material(species))

    def material(self,mesh,species,growth,female,variation,code=None,preview_defaults=False,pattern=0):
        if growth is None:return mesh,'Skin preview unavailable: growth not recorded'
        if not math.isfinite(growth) or not 0<=growth<=1:return mesh,'Skin preview unavailable: growth outside supported range'
        if code is None and not preview_defaults:return mesh,'Skin code not recorded; neutral preview'
        try:
            decoded=self.decode(species,code) if code is not None else None
            unknown=[]
            if female is None:female=False;unknown.append('sex unknown: male preview')
            if variation is None:
                variation=8.
                unknown.append('variation unknown: material default')
            # The body-color cache updates at 1/256 growth steps; geometry keeps exact recorded growth.
            rounded=round(growth*256)/256
            key=(species,rounded,bool(female),float(variation),code,pattern)
            if key in self.cache:image=self.cache.pop(key);self.cache[key]=image
            else:
                image=self.bake(species,rounded,bool(female),float(variation),decoded,pattern);self.cache[key]=image
                if len(self.cache)>16:self.cache.popitem(last=False)
            geometry_data=self.body_geometry(mesh,species)
            eye_image=self.eyes.bake(species,decoded)
            geometry=SimpleNamespace(**geometry_data,skin_texture=image,eye_texture=eye_image,surface=self.surfaces.material(species))
            eye_origin='recorded eye color' if decoded and 'Color_Iris_Primary' in decoded['overrides'] else 'eye colors: material defaults'
            return geometry,('Recorded skin colors' if decoded else 'Material defaults')+' · body / open-eye preview; approximate lighting · '+eye_origin+(' · '+'; '.join(unknown) if unknown else '')
        except (ValueError,IndexError,KeyError) as error:return mesh,'Skin preview unavailable: '+str(error)

class DinosaurEyes(DinosaurSkins):
    """Original iris/pupil color slices with explicitly fixed open-eye state."""
    def __init__(self,root,srgb):
        self.root=Path(root);path=self.root/'eye-library.json'
        if path.stat().st_size>256*1024:raise ValueError('Eye library exceeds limit')
        self.data=json.loads(path.read_text(encoding='utf-8'))
        if self.data.get('format')!='evrima-eye-library-1':raise ValueError('Unsupported eye library')
        if hashlib.sha256((self.root/'eye_color_kernel.py').read_bytes()).hexdigest()!=self.data['kernel_sha256']:raise ValueError('Eye color code digest mismatch')
        self.profiles=self.data['profiles'];self.srgb=srgb;self.images=OrderedDict();self.cache=OrderedDict()

    def uniforms(self,species,decoded=None):
        values=dict(self.profiles[species]['defaults'])
        if decoded is not None and 'Color_Iris_Primary' in decoded['overrides']:
            values['Color_Iris_Primary']=decoded['overrides']['Color_Iris_Primary']
        params=[np.atleast_1d(np.asarray(values.get(p['name'],p['default']),np.float32)) for p in self.data['numeric_parameters']]
        cb=np.zeros(52,np.float32)
        for program in self.data['preshaders']:
            result=preshader(program['bytecode'],params)
            if len(program['fields'])!=1:raise ValueError('Unsupported eye uniform fields')
            offset,component,size=program['fields'][0];offset+=12
            if component!=0 or len(result)!=size or offset+size>52:raise ValueError('Invalid eye uniform output')
            cb[offset:offset+size]=result
        return cb.reshape(13,4)

    def bake(self,species,decoded=None,size=512):
        if species not in self.profiles or size not in (128,256,512,1024):raise ValueError('Unsupported eye preview')
        primary=decoded['overrides'].get('Color_Iris_Primary') if decoded else None
        if primary is not None and (len(primary)!=4 or not np.isfinite(primary).all()):raise ValueError('Invalid recorded eye color')
        key=(species,tuple(primary) if primary is not None else None,size)
        if key in self.cache:value=self.cache.pop(key);self.cache[key]=value;return value
        from eye_color_kernel import color_6931,color_3188
        profile=self.profiles[species];kernel={'6931':color_6931,'3188':color_3188}[profile['kernel']]
        textures={int(slot):self.image(package) for slot,package in profile['textures'].items()};cb=self.uniforms(species,decoded)
        axis=(np.arange(size,dtype=np.float32)+.5)/size;u,v=np.meshgrid(axis,axis)
        def sample(slot,x,y):return bilinear(textures[slot],x,y)
        with np.errstate(divide='ignore',invalid='ignore',over='ignore'):rgb=kernel(sample,cb,u,v)
        if rgb.shape!=(size,size,3) or not np.isfinite(rgb).all():raise ValueError('Invalid rendered eye colors')
        result=np.empty((size,size,4),np.uint8);result[:,:,:3]=np.rint(linear_to_srgb(rgb)*255).astype(np.uint8);result[:,:,3]=255
        self.cache[key]=result
        if len(self.cache)>16:self.cache.popitem(last=False)
        return result
