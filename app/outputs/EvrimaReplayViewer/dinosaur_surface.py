"""Recovered clean body surface inputs with a bounded, independent lighting preview."""
from collections import OrderedDict
import ctypes as C
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent

def data_mips(image):
    """Filter numeric normal-map channels without applying a color transfer curve."""
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=4 or not image.flags.c_contiguous:raise ValueError('Invalid surface image')
    if any(n<1 or n>2048 or n&(n-1) for n in image.shape[:2]):raise ValueError('Invalid surface dimensions')
    current=image;yield current
    while max(current.shape[:2])>1:
        height,width=current.shape[:2];dy,dx=min(1,height-1),min(1,width-1);a=current.astype(np.uint16)
        current=np.ascontiguousarray(np.rint((a[::2,::2]+a[::2,dx::2]+a[dy::2,::2]+a[dy::2,dx::2])/4).astype(np.uint8));yield current

class SurfaceLibrary:
    def __init__(self,root=HERE):
        self.root=Path(root);path=self.root/'surface-library.json'
        if path.stat().st_size>256*1024:raise ValueError('Surface library exceeds limit')
        self.data=json.loads(path.read_text(encoding='utf-8'))
        if self.data.get('format')!='evrima-surface-library-1':raise ValueError('Unsupported surface library')
        source=self.root/'skin_normal.glsl'
        if source.stat().st_size>32*1024 or hashlib.sha256(source.read_bytes()).hexdigest()!=self.data['normal_kernel_sha256']:raise ValueError('Normal shader digest mismatch')
        path=self.root/'reflectance-library.json'
        if path.stat().st_size>64*1024:raise ValueError('Reflectance library exceeds limit')
        self.reflectance=json.loads(path.read_text(encoding='utf-8'))
        if self.reflectance.get('format')!='evrima-reflectance-library-1':raise ValueError('Unsupported reflectance library')
        reflected=self.root/'skin_reflectance.glsl'
        if reflected.stat().st_size>4096 or hashlib.sha256(reflected.read_bytes()).hexdigest()!=self.reflectance['kernel_sha256']:raise ValueError('Reflectance shader digest mismatch')
        path=self.root/'wetness-library.json'
        if path.stat().st_size>4096:raise ValueError('Wetness library exceeds limit')
        wetness=json.loads(path.read_text(encoding='utf-8'));wet=self.root/'skin_wetness.glsl'
        if wetness.get('format')!='evrima-wetness-library-1':raise ValueError('Unsupported wetness library')
        if wet.stat().st_size>4096 or hashlib.sha256(wet.read_bytes()).hexdigest()!=wetness['kernel_sha256']:raise ValueError('Wetness shader digest mismatch')
        path=self.root/'injury-library.json'
        if path.stat().st_size>8192:raise ValueError('Injury library exceeds limit')
        self.injury=json.loads(path.read_text(encoding='utf-8'));injury=self.root/'skin_injury.glsl'
        if self.injury.get('format')!='evrima-injury-library-1':raise ValueError('Unsupported injury library')
        if injury.stat().st_size>4096 or hashlib.sha256(injury.read_bytes()).hexdigest()!=self.injury['kernel_sha256']:raise ValueError('Injury shader digest mismatch')
        path=self.root/'blood-library.json'
        if path.stat().st_size>8192:raise ValueError('Blood library exceeds limit')
        self.blood=json.loads(path.read_text(encoding='utf-8'));blood=self.root/'skin_blood.glsl'
        if self.blood.get('format')!='evrima-blood-library-1':raise ValueError('Unsupported blood library')
        if blood.stat().st_size>4096 or hashlib.sha256(blood.read_bytes()).hexdigest()!=self.blood['kernel_sha256']:raise ValueError('Blood shader digest mismatch')
        self.kernel=source.read_text()+reflected.read_text()+wet.read_text()+injury.read_text()+blood.read_text();self.images={};self.materials={}

    def image(self,package):
        if package not in self.images:
            tables=(self.data['textures'],self.reflectance['textures'],self.injury['textures'],self.blood['textures'])
            row=next(table[package] for table in tables if package in table);path=self.root/row['file']
            if path.resolve().parent!=(self.root/'dinosaur-textures').resolve() or path.suffix!='.png':raise ValueError('Invalid surface image path')
            if path.stat().st_size>8*1024*1024 or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Surface image digest mismatch')
            with Image.open(path) as source:
                if list(source.size)!=row['size'] or max(source.size)>1024:raise ValueError('Surface image dimensions differ')
                image=np.ascontiguousarray(source.convert('RGBA'),dtype=np.uint8)
            self.images[package]=(image,bool(row['srgb']))
        return self.images[package]

    def material(self,species):
        if species not in self.materials:
            profile=self.data['profiles'][species];scale=profile['detail_scale']
            if not isinstance(scale,(int,float)) or not np.isfinite(scale) or not 0<scale<=128:raise ValueError('Invalid normal detail scale')
            maps=tuple(self.image(profile['textures'][str(slot)]) for slot in (4,5,6));cb=np.zeros((4,4),np.float32);cb[3,1]=scale
            roughness=self.image(self.reflectance['profiles'][species])
            if roughness[1]:raise ValueError('Roughness must use numeric channels')
            wound=self.image(self.injury['package'])
            if wound[1]:raise ValueError('Wound normal must use numeric channels')
            blood_noise=self.image(self.blood['package'])
            if blood_noise[1]:raise ValueError('Blood mask must use numeric channels')
            self.materials[species]=dict(maps=maps,uniforms=cb,kernel=self.kernel,roughness=roughness,wound=wound,blood_noise=blood_noise)
        return self.materials[species]

VERTEX='''#version 120
varying vec3 eye_position;
varying vec3 eye_normal;
varying vec2 body_uv;
varying float wet_source_normal_z;
void main() {
    vec4 position=gl_ModelViewMatrix*gl_Vertex;
    eye_position=position.xyz;
    eye_normal=gl_NormalMatrix*gl_Normal;
    body_uv=gl_MultiTexCoord0.xy;
    wet_source_normal_z=gl_MultiTexCoord1.z;
    gl_Position=ftransform();
}
'''
FRAGMENT_PREFIX='''#version 120
uniform sampler2D body_color;
uniform sampler2D base_normal;
uniform sampler2D detail_normal;
uniform sampler2D body_mask;
uniform sampler2D roughness_map;
uniform bool skin_shine;
uniform float body_cutout_threshold;
uniform bool masked_normals;
uniform float full_wet_amount;
uniform float wet_direction;
uniform float low_health;
uniform sampler2D wound_normal;
uniform sampler2D blood_noise;
uniform float blood_amount;
uniform float dry_blood;
uniform vec4 material[4];
varying vec3 eye_position;
varying vec3 eye_normal;
varying vec2 body_uv;
varying float wet_source_normal_z;
vec4 read_map(int slot,float u,float v) {
    if(slot==4) return texture2D(base_normal,vec2(u,v));
    if(slot==5) return texture2D(detail_normal,vec2(u,v));
    return texture2D(body_mask,vec2(u,v));
}
'''
FRAGMENT_SUFFIX='''
void main() {
    vec3 opacity_mask=texture2D(body_mask,body_uv).rgb;
    float opacity=clamp((opacity_mask.g+opacity_mask.b)+opacity_mask.r,0.0,1.0);
    if(opacity < body_cutout_threshold) discard;
    vec3 n=normalize(eye_normal);
    vec4 injury=vec4(0.0);
    if(low_health>0.0) injury=recovered_injury(body_uv,low_health);
    vec3 dpdx=dFdx(eye_position),dpdy=dFdy(eye_position);
    vec2 dx=dFdx(body_uv),dy=dFdy(body_uv);
    float determinant=dx.x*dy.y-dx.y*dy.x;
    if(abs(determinant)>1e-12) {
        vec3 tangent=(dpdx*dy.y-dpdy*dx.y)/determinant;
        vec3 bitangent=(dpdy*dx.x-dpdx*dy.x)/determinant;
        tangent-=n*dot(n,tangent);
        if(dot(tangent,tangent)>1e-16 && dot(bitangent,bitangent)>1e-16) {
            tangent=normalize(tangent);
            float handedness=dot(cross(n,tangent),bitangent)<0.0?-1.0:1.0;
            bitangent=normalize(cross(n,tangent))*handedness;
            vec3 mapped=masked_normals ? recovered_dilophosaurus_normal(body_uv) : recovered_normal(body_uv);
            if(low_health>0.0) mapped=mapped+(injury.xyz-mapped)*injury.w;
            n=normalize(tangent*mapped.x+bitangent*mapped.y+n*mapped.z);
        }
    }
    if(!gl_FrontFacing) n=-n;
    vec3 light=normalize(gl_LightSource[0].position.xyz);
    vec3 shade=clamp(gl_LightSource[0].ambient.rgb+gl_LightModel.ambient.rgb+
                     gl_LightSource[0].diffuse.rgb*max(0.0,dot(n,light)),0.0,1.0);
    float wet_factor=recovered_wet_factor(full_wet_amount,wet_direction,wet_source_normal_z);
    float blood_coverage=0.0;
    if(blood_amount>0.0) blood_coverage=recovered_blood_coverage(body_uv,blood_amount);
    vec3 albedo=texture2D(body_color,body_uv).rgb;
    if(wet_factor>0.0 || low_health>0.0 || blood_coverage>0.0) {
        vec3 linear_albedo=mix(albedo/12.92,pow((albedo+0.055)/1.055,vec3(2.4)),step(vec3(0.04045),albedo));
        if(low_health>0.0) linear_albedo=recovered_injury_color(linear_albedo,low_health);
        if(blood_coverage>0.0) linear_albedo=recovered_blood_color(linear_albedo,blood_coverage);
        linear_albedo=recovered_wet_color(linear_albedo,wet_factor);
        albedo=mix(linear_albedo*12.92,1.055*pow(linear_albedo,vec3(1.0/2.4))-0.055,step(vec3(0.0031308),linear_albedo));
    }
    vec3 color=albedo*shade;
    if(skin_shine) {
        vec2 surface=recovered_reflectance(body_uv);
        if(low_health>0.0) surface.x=recovered_injury_roughness(surface.x,injury.w);
        if(blood_coverage>0.0) surface.x=recovered_blood_roughness(surface.x,blood_coverage,dry_blood);
        surface.x=recovered_wet_roughness(surface.x,wet_factor);
        float alpha=pow(max(surface.x,0.08),2.0),a2=alpha*alpha;
        // The viewer uses an orthographic camera: the view direction is constant.
        vec3 half_vector=normalize(light+vec3(0.0,0.0,1.0));
        float nl=max(dot(n,light),0.0),nv=max(n.z,0.0);
        float nh=max(dot(n,half_vector),0.0),vh=max(half_vector.z,0.0);
        float denominator=nh*nh*(a2-1.0)+1.0;
        float distribution=a2/(3.14159265359*denominator*denominator);
        float visibility=0.5/max(nl*sqrt(nv*nv*(1.0-a2)+a2)+nv*sqrt(nl*nl*(1.0-a2)+a2),1e-6);
        float fresnel=surface.y+(1.0-surface.y)*pow(1.0-vh,5.0);
        float reflection=nl>0.0 && nv>0.0 ? distribution*visibility*fresnel*nl : 0.0;
        vec3 linear_color=mix(color/12.92,pow((color+0.055)/1.055,vec3(2.4)),step(vec3(0.04045),color));
        linear_color=clamp(linear_color+gl_LightSource[0].diffuse.rgb*reflection,0.0,1.0);
        color=mix(linear_color*12.92,1.055*pow(linear_color,vec3(1.0/2.4))-0.055,step(vec3(0.0031308),linear_color));
    }
    gl_FragColor=vec4(color,1.0);
}
'''

class SurfaceRenderer:
    """Compatibility GLSL for dinosaur bodies only; other drawing retains its state."""
    def __init__(self,gl,kernel):
        self.gl=gl;self.program=0;self.cache=OrderedDict();self.functions={}
        gl.wglGetProcAddress.argtypes=[C.c_char_p];gl.wglGetProcAddress.restype=C.c_void_p
        declarations={
            'glCreateShader':(C.c_uint,[C.c_uint]),'glShaderSource':(None,[C.c_uint,C.c_int,C.POINTER(C.c_char_p),C.POINTER(C.c_int)]),
            'glCompileShader':(None,[C.c_uint]),'glGetShaderiv':(None,[C.c_uint,C.c_uint,C.POINTER(C.c_int)]),
            'glGetShaderInfoLog':(None,[C.c_uint,C.c_int,C.POINTER(C.c_int),C.c_char_p]),'glDeleteShader':(None,[C.c_uint]),
            'glCreateProgram':(C.c_uint,[]),'glAttachShader':(None,[C.c_uint,C.c_uint]),'glLinkProgram':(None,[C.c_uint]),
            'glGetProgramiv':(None,[C.c_uint,C.c_uint,C.POINTER(C.c_int)]),'glGetProgramInfoLog':(None,[C.c_uint,C.c_int,C.POINTER(C.c_int),C.c_char_p]),
            'glDeleteProgram':(None,[C.c_uint]),'glUseProgram':(None,[C.c_uint]),'glGetUniformLocation':(C.c_int,[C.c_uint,C.c_char_p]),
            'glUniform1i':(None,[C.c_int,C.c_int]),'glUniform1f':(None,[C.c_int,C.c_float]),'glUniform4fv':(None,[C.c_int,C.c_int,C.POINTER(C.c_float)]),'glActiveTexture':(None,[C.c_uint]),'glClientActiveTexture':(None,[C.c_uint])}
        for name,(result,args) in declarations.items():
            address=gl.wglGetProcAddress(name.encode())
            if address in (None,0,1,2,3,C.c_void_p(-1).value):raise RuntimeError('Surface detail needs OpenGL shader support: '+name)
            self.functions[name]=C.WINFUNCTYPE(result,*args)(address)
        shaders=[]
        try:
            masked_kernel=(HERE/'dinosaur_masked_normal.glsl').read_text(encoding='utf-8')
            for kind,source in ((0x8b31,VERTEX),(0x8b30,FRAGMENT_PREFIX+kernel+masked_kernel+FRAGMENT_SUFFIX)):
                shader=self.call('glCreateShader',kind)
                if not shader:raise RuntimeError('Cannot allocate surface shader')
                shaders.append(shader);raw=source.encode();pointer=C.c_char_p(raw);length=C.c_int(len(raw))
                self.call('glShaderSource',shader,1,C.byref(pointer),C.byref(length));self.call('glCompileShader',shader)
                self._check(shader,False)
            self.program=self.call('glCreateProgram')
            if not self.program:raise RuntimeError('Cannot allocate surface program')
            for shader in shaders:self.call('glAttachShader',self.program,shader)
            self.call('glLinkProgram',self.program);self._check(self.program,True)
            self.uniforms={name:self.call('glGetUniformLocation',self.program,name.encode()) for name in ('body_color','base_normal','detail_normal','body_mask','roughness_map','wound_normal','blood_noise','skin_shine','body_cutout_threshold','masked_normals','full_wet_amount','wet_direction','low_health','blood_amount','dry_blood','material[0]')}
            if any(value<0 for value in self.uniforms.values()):raise RuntimeError('Surface uniforms did not link')
        except BaseException:
            self.close();raise
        finally:
            for shader in shaders:self.call('glDeleteShader',shader)

    def call(self,name,*args):return self.functions[name](*args)

    def _check(self,value,program):
        prefix='Program' if program else 'Shader';status=C.c_int();self.call('glGet'+prefix+'iv',value,0x8b82 if program else 0x8b81,C.byref(status))
        if not status.value:
            log=C.create_string_buffer(8192);self.call('glGet'+prefix+'InfoLog',value,len(log),None,log)
            raise RuntimeError('Surface '+prefix.lower()+': '+log.value.decode('utf-8','replace'))

    def _texture(self,pixels,srgb):
        key=(id(pixels),srgb);cached=self.cache.pop(key,None);gl=self.gl
        if cached is None:
            from replay_texture_filter import mip_chain
            tex=C.c_uint();gl.glGenTextures(1,C.byref(tex));gl.glBindTexture(0x0de1,tex.value)
            try:
                for level,image in enumerate(mip_chain(pixels) if srgb else data_mips(pixels)):
                    gl.glTexImage2D(0x0de1,level,0x8c43 if srgb else 0x8058,image.shape[1],image.shape[0],0,0x1908,0x1401,image.ctypes.data)
                for setting,value in ((0x2801,0x2703),(0x2800,0x2601),(0x2802,0x2901),(0x2803,0x2901)):gl.glTexParameteri(0x0de1,setting,value)
                error=gl.glGetError()
                if error:raise RuntimeError(f'Surface map upload failed: 0x{error:x}')
            except BaseException:gl.glDeleteTextures(1,C.byref(tex));raise
            if len(self.cache)>=16:
                _,old=self.cache.popitem(last=False);gl.glDeleteTextures(1,C.byref(old[1]))
            cached=(pixels,tex)
        self.cache[key]=cached;gl.glBindTexture(0x0de1,cached[1].value)

    def begin(self,surface,shine=True,wetness=0.,injury=0.,blood=0.,dry_blood=0.):
        if len(surface['maps'])!=3 or surface['uniforms'].shape!=(4,4) or not np.isfinite(surface['uniforms']).all():raise ValueError('Invalid surface material')
        if not isinstance(wetness,(int,float)) or not np.isfinite(wetness) or not 0<=wetness<=1:raise ValueError('Invalid wetness preview amount')
        if not isinstance(injury,(int,float)) or not np.isfinite(injury) or not 0<=injury<=1:raise ValueError('Invalid injury preview amount')
        for value in (blood,dry_blood):
            if not isinstance(value,(int,float)) or not np.isfinite(value) or not 0<=value<=1:raise ValueError('Invalid blood preview amount')
        try:
            maps=surface['maps']+(surface.get('roughness',surface['maps'][0]),surface.get('wound',surface['maps'][0]),surface.get('blood_noise',surface['maps'][0]))
            for unit,(pixels,srgb) in enumerate(maps,1):
                self.call('glActiveTexture',0x84c0+unit);self._texture(pixels,srgb)
            self.call('glActiveTexture',0x84c0);self.call('glUseProgram',self.program)
            for unit,name in enumerate(('body_color','base_normal','detail_normal','body_mask','roughness_map','wound_normal','blood_noise')):self.call('glUniform1i',self.uniforms[name],unit)
            self.call('glUniform1i',self.uniforms['skin_shine'],int(bool(shine and 'roughness' in surface)))
            self.cutout(0.)
            self.call('glUniform1i',self.uniforms['masked_normals'],int(bool(surface.get('masked_normals',False))))
            self.call('glUniform1f',self.uniforms['full_wet_amount'],wetness)
            self.call('glUniform1f',self.uniforms['wet_direction'],0.)
            self.call('glUniform1f',self.uniforms['low_health'],injury if 'wound' in surface else 0.)
            self.call('glUniform1f',self.uniforms['blood_amount'],blood if 'blood_noise' in surface else 0.)
            self.call('glUniform1f',self.uniforms['dry_blood'],dry_blood)
            cb=np.ascontiguousarray(surface['uniforms'],np.float32);self.call('glUniform4fv',self.uniforms['material[0]'],4,cb.ctypes.data_as(C.POINTER(C.c_float)))
        except BaseException:self.end();raise

    def cutout(self,threshold):
        if not np.isfinite(threshold) or not 0 <= threshold <= 1:raise ValueError('Invalid body cutout threshold')
        self.call('glUniform1f',self.uniforms['body_cutout_threshold'],threshold)

    def direction(self,value,normals):
        if type(value) not in (int,float) or not np.isfinite(value) or abs(value)>3.4028234663852886e38:raise ValueError('Invalid wet direction')
        if normals is None or normals.dtype!=np.float32 or normals.ndim!=2 or normals.shape[1]!=3 or not normals.flags.c_contiguous or not np.isfinite(normals).all() or np.any(abs(normals)>1):raise ValueError('Invalid wet source normals')
        self.call('glUniform1f',self.uniforms['wet_direction'],value)
        self.call('glClientActiveTexture',0x84c1)
        try:
            self.gl.glTexCoordPointer(3,0x1406,0,normals.ctypes.data)
            self.gl.glEnableClientState(0x8078)
        finally:self.call('glClientActiveTexture',0x84c0)

    def end(self):
        self.call('glUseProgram',0)
        self.call('glClientActiveTexture',0x84c1)
        self.gl.glDisableClientState(0x8078)
        self.call('glClientActiveTexture',0x84c0)
        for unit in (6,5,4,3,2,1):
            self.call('glActiveTexture',0x84c0+unit);self.gl.glBindTexture(0x0de1,0)
        self.call('glActiveTexture',0x84c0)

    def close(self):
        for pixels,texture in self.cache.values():self.gl.glDeleteTextures(1,C.byref(texture))
        self.cache.clear()
        if self.program:self.call('glDeleteProgram',self.program);self.program=0
