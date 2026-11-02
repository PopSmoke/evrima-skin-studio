"""Depth-tested rendering of decoded owned mesh geometry using Windows OpenGL."""
import ctypes as C
from ctypes import wintypes as W
import json
import math
from pathlib import Path
import threading
from itertools import chain
import numpy as np
from PIL import Image


def matrix(transform):
    x,y,z,w=transform[:4]
    q=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]],dtype=np.float64)
    out=np.eye(4);out[:3,:3]=q*np.array(transform[7:]);out[:3,3]=transform[4:7]
    return out


def component_matrices(bones, transforms):
    result=[]
    if len(bones)!=len(transforms):raise ValueError('Bone/transform mismatch')
    for i,((_,parent),transform) in enumerate(zip(bones,transforms)):
        if not (-1<=parent<i) or (i>0 and parent==-1):raise ValueError('Invalid bone hierarchy')
        value=matrix(transform)
        result.append(value if parent==-1 else result[parent]@value)
    return np.asarray(result)


class Mesh:
    def __init__(self,path):
        path=Path(path)
        if path.stat().st_size>64*1024*1024:raise ValueError('Mesh cache exceeds size limit')
        self.data=json.loads(path.read_text(encoding='utf-8'))
        if self.data['format']!='evrima-render-mesh-1':raise ValueError('Unsupported mesh cache')
        self.positions=np.asarray(self.data['positions'],dtype=np.float64)
        self.indices=np.ascontiguousarray(self.data['indices'],dtype=np.uint32)
        if self.positions.ndim!=2 or self.positions.shape[1]!=3 or not np.isfinite(self.positions).all():raise ValueError('Invalid positions')
        if len(self.indices)%3 or np.any(self.indices>=len(self.positions)):raise ValueError('Invalid indices')
        self.bones=self.data['bones']
        self.bind=component_matrices(self.bones,self.data['reference_local_transforms'])
        self.inverse_bind=np.linalg.inv(self.bind)
        self.bone_indices=np.asarray(self.data['bone_indices'],dtype=np.int32)
        self.weights=np.asarray(self.data['weights'],dtype=np.float64)/self.data['weight_denominator']
        if self.bone_indices.shape!=self.weights.shape or len(self.weights)!=len(self.positions):raise ValueError('Invalid weights')
        if np.any(self.bone_indices<0) or np.any(self.bone_indices>=len(self.bones)):raise ValueError('Invalid bone index')
        if not np.allclose(self.weights.sum(axis=1),1) or np.any(self.weights<0):raise ValueError('Invalid weight sum')
        self.homogeneous=np.column_stack((self.positions,np.ones(len(self.positions))))
        self.colors=np.empty((len(self.positions),3),dtype=np.float32)
        self.colors[:]=(0.43,0.58,0.64)
        for section in self.data['sections']:
            if section['material']==1:
                start=section['base_vertex'];self.colors[start:start+section['vertices']]=(0.8,0.57,0.22)

    def skin(self,component,positions=None):
        component=np.asarray(component,dtype=np.float64)
        if component.shape!=self.bind.shape or not np.isfinite(component).all():raise ValueError('Invalid pose matrices')
        delta=component@self.inverse_bind
        homogeneous=self.homogeneous
        if positions is not None:
            positions=np.asarray(positions,dtype=np.float64)
            if positions.shape!=self.positions.shape or not np.isfinite(positions).all():raise ValueError('Invalid morphed positions')
            homogeneous=np.column_stack((positions,np.ones(len(positions))))
        result=np.zeros((len(self.positions),3),dtype=np.float64)
        for influence in range(self.weights.shape[1]):
            selected=delta[self.bone_indices[:,influence]]
            transformed=np.einsum('nij,nj->ni',selected,homogeneous)[:,:3]
            result+=transformed*self.weights[:,influence,None]
        return result

    def normals(self,positions):
        tri=self.indices.reshape(-1,3)
        a,b,c=positions[tri[:,0]],positions[tri[:,1]],positions[tri[:,2]]
        face=np.cross(b-a,c-a)
        normals=np.zeros_like(positions)
        for i in range(3):np.add.at(normals,tri[:,i],face)
        normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-20)
        return normals


class PixelFormat(C.Structure):
    _fields_=[('size',W.WORD),('version',W.WORD),('flags',W.DWORD),
              ('pixel_type',C.c_ubyte),('color_bits',C.c_ubyte),('red_bits',C.c_ubyte),('red_shift',C.c_ubyte),
              ('green_bits',C.c_ubyte),('green_shift',C.c_ubyte),('blue_bits',C.c_ubyte),('blue_shift',C.c_ubyte),
              ('alpha_bits',C.c_ubyte),('alpha_shift',C.c_ubyte),('accum_bits',C.c_ubyte),('accum_red',C.c_ubyte),
              ('accum_green',C.c_ubyte),('accum_blue',C.c_ubyte),('accum_alpha',C.c_ubyte),('depth',C.c_ubyte),
              ('stencil',C.c_ubyte),('aux',C.c_ubyte),('layer_type',C.c_ubyte),('reserved',C.c_ubyte),
              ('layer_mask',W.DWORD),('visible_mask',W.DWORD),('damage_mask',W.DWORD)]


class GLRenderer:
    """Own hidden rendering surface; no game process, browser, or external window capture."""
    def __init__(self,width=1600,height=1000):
        self.thread=threading.get_ident();self.width=width;self.height=height
        self.user=C.WinDLL('user32',use_last_error=True);self.gdi=C.WinDLL('gdi32',use_last_error=True);self.gl=C.WinDLL('opengl32',use_last_error=True)
        self.hwnd=self.dc=self.context=None
        self._visibility_id=None;self._visibility_source=None
        self._skin_cache={}
        self._hangar=None;self._hangar_error=None
        self._sharp_rock=None;self._sharp_rock_error=None
        self._road=None;self._road_error=None
        self._water_surface=None;self._water_error=None
        self.snow_coverage=0.;self._snow=None
        self.wet_direction_preview=0.
        self.surface_detail=True;self.skin_shine=True;self.wetness_preview=0.;self.injury_preview=0.;self.blood_preview=0.;self.dry_blood_preview=0.;self._surface=None;self._surface_error=None
        self._color_id=None;self._color_source=None;self._color_cache={}
        self._color_mip_levels=0;self._terrain_anisotropy=1.
        def bind(dll,name,result,args):
            fn=getattr(dll,name);fn.restype=result;fn.argtypes=args;return fn
        self.create=bind(self.user,'CreateWindowExW',W.HWND,[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p])
        self.getdc=bind(self.user,'GetDC',W.HDC,[W.HWND]);self.releasedc=bind(self.user,'ReleaseDC',C.c_int,[W.HWND,W.HDC])
        self.destroy=bind(self.user,'DestroyWindow',W.BOOL,[W.HWND])
        self.resize=bind(self.user,'SetWindowPos',W.BOOL,[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT])
        choose=bind(self.gdi,'ChoosePixelFormat',C.c_int,[W.HDC,C.POINTER(PixelFormat)])
        setformat=bind(self.gdi,'SetPixelFormat',W.BOOL,[W.HDC,C.c_int,C.POINTER(PixelFormat)])
        createcontext=bind(self.gl,'wglCreateContext',C.c_void_p,[W.HDC])
        self.current=bind(self.gl,'wglMakeCurrent',W.BOOL,[W.HDC,C.c_void_p])
        self.deletecontext=bind(self.gl,'wglDeleteContext',W.BOOL,[C.c_void_p])
        self.hwnd=self.create(0,'STATIC','Replay mesh rendering surface',0x80000000,0,0,width,height,None,None,None,None)
        if not self.hwnd:raise C.WinError(C.get_last_error())
        try:
            self.dc=self.getdc(self.hwnd)
            p=PixelFormat();p.size=C.sizeof(p);p.version=1;p.flags=0x4|0x20|0x1;p.color_bits=24;p.depth=24
            index=choose(self.dc,C.byref(p))
            if not index or not setformat(self.dc,index,C.byref(p)):raise C.WinError(C.get_last_error())
            self.context=createcontext(self.dc)
            if not self.context or not self.current(self.dc,self.context):raise C.WinError(C.get_last_error())
            specifications={
                'glGetString':(C.c_char_p,[C.c_uint]),'glGetError':(C.c_uint,[]),
                'glGetIntegerv':(None,[C.c_uint,C.POINTER(C.c_int)]),
                'glGetFloatv':(None,[C.c_uint,C.POINTER(C.c_float)]),
                'glGenTextures':(None,[C.c_int,C.POINTER(C.c_uint)]),'glDeleteTextures':(None,[C.c_int,C.POINTER(C.c_uint)]),
                'glBindTexture':(None,[C.c_uint,C.c_uint]),'glTexParameteri':(None,[C.c_uint,C.c_uint,C.c_int]),
                'glTexParameterf':(None,[C.c_uint,C.c_uint,C.c_float]),
                'glTexEnvi':(None,[C.c_uint,C.c_uint,C.c_int]),'glAlphaFunc':(None,[C.c_uint,C.c_float]),
                'glTexImage2D':(None,[C.c_uint,C.c_int,C.c_int,C.c_int,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_void_p]),
                'glTexCoordPointer':(None,[C.c_int,C.c_uint,C.c_int,C.c_void_p]),
                'glViewport':(None,[C.c_int]*4),'glClearColor':(None,[C.c_float]*4),'glClear':(None,[C.c_uint]),'glPointSize':(None,[C.c_float]),
                'glEnable':(None,[C.c_uint]),'glDisable':(None,[C.c_uint]),'glFrontFace':(None,[C.c_uint]),'glMatrixMode':(None,[C.c_uint]),
                'glLoadIdentity':(None,[]),'glOrtho':(None,[C.c_double]*6),'glLoadMatrixd':(None,[C.POINTER(C.c_double)]),
                'glLightfv':(None,[C.c_uint,C.c_uint,C.POINTER(C.c_float)]),'glColorMaterial':(None,[C.c_uint,C.c_uint]),
                'glLightModeli':(None,[C.c_uint,C.c_int]),'glEnableClientState':(None,[C.c_uint]),'glDisableClientState':(None,[C.c_uint]),
                'glVertexPointer':(None,[C.c_int,C.c_uint,C.c_int,C.c_void_p]),'glNormalPointer':(None,[C.c_uint,C.c_int,C.c_void_p]),
                'glColorPointer':(None,[C.c_int,C.c_uint,C.c_int,C.c_void_p]),'glDrawElements':(None,[C.c_uint,C.c_int,C.c_uint,C.c_void_p]),
                'glBlendFunc':(None,[C.c_uint,C.c_uint]),'glDepthFunc':(None,[C.c_uint]),'glDepthMask':(None,[C.c_ubyte]),
                'glReadPixels':(None,[C.c_int,C.c_int,C.c_int,C.c_int,C.c_uint,C.c_uint,C.c_void_p]),
                'glPixelStorei':(None,[C.c_uint,C.c_int]),'glFinish':(None,[]),'glReadBuffer':(None,[C.c_uint]),'glDrawBuffer':(None,[C.c_uint])}
            for name,(result,args) in specifications.items():bind(self.gl,name,result,args)
            self.info={k:self.gl.glGetString(v).decode('ascii','replace') for k,v in [('vendor',0x1f00),('renderer',0x1f01),('version',0x1f02)]}
            extensions=(self.gl.glGetString(0x1f03) or b'').split()
            if b'GL_EXT_texture_filter_anisotropic' in extensions or b'GL_ARB_texture_filter_anisotropic' in extensions:
                maximum=C.c_float();self.gl.glGetFloatv(0x84ff,C.byref(maximum))
                if math.isfinite(maximum.value) and maximum.value>=1:self._terrain_anisotropy=min(8.,maximum.value)
            self.info['terrain_filtering']='Trilinear preview mips; linear-light RGB reduction; linear visibility weights'
            self.info['terrain_anisotropy']=self._terrain_anisotropy
            self.gl.glEnable(0x0b71);self.gl.glEnable(0x0b50);self.gl.glEnable(0x4000);self.gl.glEnable(0x0ba1)
            self.gl.glLightModeli(0x0b52,1)
            # The shared camera reflects screen-right, reversing projected winding.
            self.gl.glFrontFace(0x0900)
            self.gl.glEnable(0x0b57);self.gl.glColorMaterial(0x0408,0x1602)
            for key,values in ((0x1200,(.30,.30,.30,1)),(0x1201,(.80,.80,.80,1)),(0x1203,(-.3,.7,1.,0))):self.gl.glLightfv(0x4000,key,(C.c_float*4)(*values))
            self.gl.glPixelStorei(0x0d05,1);self.gl.glDrawBuffer(0x0405);self.gl.glReadBuffer(0x0405)
        except Exception:
            self.close();raise

    def draw(self,mesh,instances,camera,width,height,terrain=None,water=None,scenery=(),models=()):
        if threading.get_ident()!=self.thread:raise RuntimeError('OpenGL renderer used on another thread')
        if not (0<width<=8192 and 0<height<=8192):raise ValueError('Frame exceeds 8192-pixel rendering limit')
        if width>self.width or height>self.height:
            self.width=max(width,self.width);self.height=max(height,self.height)
            if not self.resize(self.hwnd,None,0,0,self.width,self.height,0x2|0x4|0x10):raise C.WinError(C.get_last_error())
        if not self.context or not self.current(self.dc,self.context):raise RuntimeError('Rendering context is closed')
        gl=self.gl;self.info['dinosaur_surface_detail']='Basic lighting';gl.glViewport(0,0,width,height);gl.glClearColor(16/255,25/255,33/255,1);gl.glClear(0x4000|0x100)
        half=camera.span/2;ratio=width/height
        xhalf,yhalf=(half*ratio,half) if width>=height else (half,half/ratio)
        depth_range=max(10000,camera.span*10)
        if terrain is not None:
            depth_range=max(depth_range,float(np.max(np.abs((terrain.positions-np.asarray(camera.center))@np.asarray(camera.basis()[2]))))+1000)
        gl.glMatrixMode(0x1701);gl.glLoadIdentity();gl.glOrtho(-xhalf,xhalf,-yhalf,yhalf,-depth_range,depth_range)
        right,up,depth=camera.basis();view=np.eye(4);view[:3,:3]=np.array([right,up,depth])
        gl.glMatrixMode(0x1700);v=np.ascontiguousarray(view.T);gl.glLoadMatrixd(v.ctypes.data_as(C.POINTER(C.c_double)))
        gl.glEnableClientState(0x8074);gl.glEnableClientState(0x8075);gl.glEnableClientState(0x8076)
        batches=chain(([(terrain,[terrain.positions])] if terrain is not None else []),
                      ([(water,[water.positions])] if water is not None else []),
                      ((g,[g.positions]) for g in scenery),[(mesh,instances)],
                      ((g,[p]) for g,p in models))
        batches=list(batches)
        # Surface overlays follow all opaque geometry, including actors.
        batches=[b for b in batches if not getattr(b[0],'material_blend',False)]+[b for b in batches if getattr(b[0],'material_blend',False)]
        # Material sections often share the same large position array. Convert
        # it once per frame, without retaining camera-relative buffers afterward.
        vertex_cache={};vertex_cache_bytes=0;vertex_reuses=0
        for geometry,placements in batches:
            visibility=getattr(geometry,'visibility_texture',None)
            if visibility is not None:
                self._bind_visibility(geometry)
            else:
                gl.glDisable(0x0bc0);gl.glDisable(0x0de1);gl.glDisableClientState(0x8078)
            gl.glColorPointer(3,0x1406,0,geometry.colors.ctypes.data)
            for positions in placements:
                entry=vertex_cache.get(id(positions))
                if entry is not None:
                    vertices=entry[1];vertex_reuses+=1
                else:
                    vertices=np.ascontiguousarray(np.asarray(positions)-np.asarray(camera.center),dtype=np.float32)
                    if getattr(self,'reuse_frame_vertices',True) and vertex_cache_bytes+vertices.nbytes<=64*1024*1024:
                        vertex_cache[id(positions)]=(positions,vertices);vertex_cache_bytes+=vertices.nbytes
                normals=np.ascontiguousarray(geometry.normals(np.asarray(positions)),dtype=np.float32)
                gl.glVertexPointer(3,0x1406,0,vertices.ctypes.data);gl.glNormalPointer(0x1406,0,normals.ctypes.data)
                points=getattr(geometry,'primitive',None)=='points'
                if points:gl.glPointSize(max(1.,min(4.,float(getattr(geometry,'point_size',2.)))))
                if getattr(geometry,'skin_texture',None) is not None:
                    gl.glDisable(0x0de1);gl.glDisableClientState(0x8078)
                if getattr(geometry,'eye_texture',None) is not None:
                    self._bind_skin(geometry,eye=True)
                if getattr(geometry,'foliage_texture',None) is not None:
                    self._bind_skin(geometry,foliage=True)
                    cutoff=geometry.foliage_cutoff
                    if cutoff is not None:
                        if not math.isfinite(cutoff) or not 0<=cutoff<=1:raise ValueError('Invalid foliage cutoff')
                        gl.glAlphaFunc(0x0204,cutoff);gl.glEnable(0x0bc0)
                if getattr(geometry,'material_blend',False):
                    # Back-to-front triangle order, with depth testing but no depth writes.
                    triangles=geometry.indices.reshape(-1,3)
                    depths=vertices[triangles].mean(axis=1)@np.asarray(depth)
                    ordered=np.ascontiguousarray(triangles[np.argsort(depths,kind='stable')].ravel())
                    gl.glEnable(0x0be2);gl.glBlendFunc(0x0302,0x0303);gl.glDepthMask(0);gl.glDepthFunc(0x0203)
                    try:gl.glDrawElements(0x0004,len(ordered),0x1405,ordered.ctypes.data)
                    finally:
                        gl.glDisable(0x0be2);gl.glDepthMask(1);gl.glDepthFunc(0x0201)
                else:
                    hangar=getattr(geometry,'hangar',None)
                    sharp=getattr(geometry,'sharp_rock',None)
                    if sharp is not None and self._sharp_rock is None and self._sharp_rock_error is None:
                        from sharp_rock_surface import SharpRockSurface
                        try:self._sharp_rock=SharpRockSurface(gl,sharp['material'])
                        except RuntimeError as error:self._sharp_rock_error=str(error)
                    sharp_active=sharp is not None and self._sharp_rock is not None
                    if sharp is not None:self.info['sharp_rock_material']='Recovered color and normal layers; preview lighting' if sharp_active else 'Plain fallback: '+str(self._sharp_rock_error)
                    road=getattr(geometry,'dirt_road',None)
                    water_data=getattr(geometry,'water_surface',None)
                    if water_data is not None and self._water_surface is None and self._water_error is None:
                        from water_surface import WaterSurface
                        try:self._water_surface=WaterSurface(gl,water_data['material'])
                        except RuntimeError as error:self._water_error=str(error)
                    water_active=water_data is not None and self._water_surface is not None
                    if water_data is not None:self.info['water_material']='Recovered wave samples; opaque preview lighting' if water_active else 'Flat preview: '+str(self._water_error)
                    if water_data is not None:self.info['water_vegetation']='Recovered duckweed textures on 11 designated lakes; approximate offset and lighting' if water_active else 'Unavailable with flat water fallback'
                    if water_data is not None:self.info['water_shoreline']='Lake10 patch only; approximate terrain/rock distance with feathered broad normal flattening' if water_active else 'Unavailable with flat water fallback'
                    if water_data is not None:self.info['water_ripples']='Limited Lake10 band; approximate geometry distance and replay-relative signed ripple preview' if water_active else 'Unavailable with flat water fallback'
                    if road is not None and self._road is None and self._road_error is None:
                        from dirt_road_surface import RoadSurface
                        try:self._road=RoadSurface(gl,road['material'])
                        except RuntimeError as error:self._road_error=str(error)
                    road_active=road is not None and self._road is not None
                    if road is not None:self.info['dirt_road_material']='Recovered world-position color variation; preview lighting' if road_active else 'Base tint: '+str(self._road_error)
                    if hangar is not None and self._hangar is None and self._hangar_error is None:
                        from hangar_surface import HangarSurface
                        try:self._hangar=HangarSurface(gl,hangar['material'])
                        except RuntimeError as error:self._hangar_error=str(error)
                    active=hangar is not None and self._hangar is not None
                    if hangar is not None:self.info['hangar_material']='Recovered exterior colors; simplified lighting' if active else 'Basic lighting: '+str(self._hangar_error)
                    try:
                        if sharp_active:self._sharp_rock.begin(sharp)
                        if active:self._hangar.begin(hangar)
                        if road_active:self._road.begin(road)
                        if water_active:self._water_surface.begin(dict(water_data,view=depth))
                        gl.glDrawElements(0x0000 if points else 0x0004,len(geometry.indices),0x1405,geometry.indices.ctypes.data)
                    finally:
                        if water_active:self._water_surface.end()
                        if road_active:self._road.end()
                        if active:self._hangar.end()
                        if sharp_active:self._sharp_rock.end()
                if getattr(geometry,'skin_texture',None) is not None:
                    self._bind_skin(geometry)
                    surface=getattr(geometry,'surface',None)
                    active=surface is not None and self.surface_detail and self._surface_error is None
                    if active and self._surface is None:
                        from dinosaur_surface import SurfaceRenderer
                        try:self._surface=SurfaceRenderer(gl,surface['kernel'])
                        except RuntimeError as error:self._surface_error=str(error);active=False
                    self.info['dinosaur_surface_detail']=('Recovered normal maps'+(' and dry skin shine' if self.skin_shine and 'roughness' in surface else '')+' with preview lighting') if active else ('Basic lighting: '+self._surface_error if self._surface_error else 'Basic lighting')
                    targets=getattr(geometry,'recorded_surface_targets',{})
                    wetness=targets.get('wetness',self.wetness_preview)
                    direction=targets.get('wet_direction',0. if 'wetness' in targets else self.wet_direction_preview)
                    blood=targets.get('blood',self.blood_preview)
                    dry_blood=targets.get('dry_blood',self.dry_blood_preview)
                    if active and wetness>0:self.info['dinosaur_surface_detail']=self.info['dinosaur_surface_detail'].replace('dry skin shine','skin shine')+('; recorded wetness target preview (transitions unfinished)' if 'wetness' in targets else '; manual wet skin preview (not recorded)')+('; recorded wet direction' if 'wet_direction' in targets else '; uniform wetting: direction not recorded' if 'wetness' in targets else f'; manual wet direction {direction:.3g}')
                    recorded_injury=getattr(geometry,'recorded_injury',None)
                    injury=self.injury_preview if recorded_injury is None else recorded_injury
                    if active and recorded_injury is not None:self.info['dinosaur_surface_detail']+='; recorded injury appearance'
                    elif active and self.injury_preview>0:self.info['dinosaur_surface_detail']+='; manual injury preview (not recorded)'
                    if active and blood>0:self.info['dinosaur_surface_detail']+=('; recorded blood target preview (transitions unfinished)' if 'blood' in targets else '; manual '+('dried' if dry_blood==1 else 'fresh')+' blood preview (not recorded)')
                    if active:self._surface.begin(surface,self.skin_shine,wetness,injury,blood,dry_blood)
                    try:
                        if active and direction!=0.:
                            source_normals=getattr(geometry,'wet_source_normals',None)
                            if source_normals is None or len(source_normals)!=len(vertices):raise ValueError('Wet normal vertex count mismatch')
                            self._surface.direction(direction,source_normals)
                        gl.glDrawElements(0x0004,len(geometry.skin_indices),0x1405,geometry.skin_indices.ctypes.data)
                        cutout=getattr(geometry,'skin_cutout_indices',None)
                        if cutout is not None and len(cutout):
                            threshold=geometry.skin_cutout_threshold
                            if not math.isfinite(threshold) or not 0<=threshold<=1:raise ValueError('Invalid body cutoff')
                            if cutout.dtype!=np.uint32 or not cutout.flags.c_contiguous or cutout.ndim!=1 or len(cutout)%3 or np.any(cutout>=len(vertices)):raise ValueError('Invalid body cutout indices')
                            if active:self._surface.cutout(threshold)
                            else:gl.glAlphaFunc(0x0206,threshold);gl.glEnable(0x0bc0)
                            gl.glDrawElements(0x0004,len(cutout),0x1405,cutout.ctypes.data)
                    finally:
                        gl.glDisable(0x0bc0)
                        if active:self._surface.end()
                for page in getattr(geometry,'color_batches',()):
                    self._bind_color(page)
                    gl.glDrawElements(0x0004,len(page.color_indices),0x1405,page.color_indices.ctypes.data)
                if getattr(geometry,'color_texture',None) is not None:
                    self._bind_color(geometry)
                    gl.glDrawElements(0x0004,len(geometry.color_indices),0x1405,geometry.color_indices.ctypes.data)
                if geometry is terrain and self.snow_coverage>0:
                    if self._snow is None:
                        from terrain_snow import SnowPreview
                        self._snow=SnowPreview(gl)
                    self._snow.draw(terrain,normals,self.snow_coverage)
        gl.glDisable(0x0bc0);gl.glDisable(0x0de1);gl.glDisableClientState(0x8078)
        self.info['shared_vertex_batches']=vertex_reuses
        self.info['frame_vertex_cache_bytes']=vertex_cache_bytes
        gl.glFinish();pixels=np.empty((height,width,3),dtype=np.uint8)
        gl.glReadPixels(0,0,width,height,0x1907,0x1401,pixels.ctypes.data)
        error=gl.glGetError()
        if error:raise RuntimeError(f'OpenGL error 0x{error:x}')
        return Image.fromarray(pixels[::-1].copy())

    def _bind_skin(self,geometry,eye=False,foliage=False):
        pixels=geometry.foliage_texture if foliage else geometry.eye_texture if eye else geometry.skin_texture;uv=geometry.skin_uv;indices=geometry.indices if eye or foliage else geometry.skin_indices
        if pixels.dtype!=np.uint8 or pixels.ndim!=3 or pixels.shape[2]!=4 or (not foliage and pixels.shape[0]!=pixels.shape[1]) or any(n not in (128,256,512,1024) for n in pixels.shape[:2]) or not pixels.flags.c_contiguous:raise ValueError('Invalid surface texture')
        if uv.shape!=(len(geometry.positions),2) or uv.dtype!=np.float32 or not uv.flags.c_contiguous or not np.isfinite(uv).all():raise ValueError('Invalid dinosaur texture coordinates')
        if indices.dtype!=np.uint32 or indices.ndim!=1 or len(indices)%3 or not indices.flags.c_contiguous or np.any(indices>=len(geometry.positions)):raise ValueError('Invalid dinosaur body indices')
        grid=getattr(geometry,'foliage_atlas_grid',None) if foliage else None
        gl=self.gl;key=(id(pixels),grid);entry=self._skin_cache.pop(key,None)
        if entry is None:
            from replay_texture_filter import mip_chain,cutout_atlas_mip_chain
            texture=C.c_uint();gl.glGenTextures(1,C.byref(texture));gl.glBindTexture(0x0de1,texture.value)
            try:
                levels=cutout_atlas_mip_chain(pixels,grid) if grid is not None else mip_chain(pixels)
                for level,mip in enumerate(levels):
                    gl.glTexImage2D(0x0de1,level,0x8058,mip.shape[1],mip.shape[0],0,0x1908,0x1401,mip.ctypes.data)
                gl.glTexParameteri(0x0de1,0x813d,level) # Last valid mip; atlas tiles must never merge.
                for setting,value in ((0x2801,0x2703),(0x2800,0x2601),(0x2802,0x2901),(0x2803,0x2901)):gl.glTexParameteri(0x0de1,setting,value)
                error=gl.glGetError()
                if error:raise RuntimeError(f'Dinosaur texture upload failed: 0x{error:x}')
            except BaseException:gl.glDeleteTextures(1,C.byref(texture));raise
            # Keep one complete 52-model tree view set without evicting ordinary
            # material textures. Both categories retain bounded LRU storage.
            category=[k for k in self._skin_cache if (k[1] is not None)==(grid is not None)]
            if len(category)>=(52 if grid is not None else 16):
                old=self._skin_cache.pop(category[0]);gl.glDeleteTextures(1,C.byref(old[1]))
            entry=(pixels,texture)
        self._skin_cache[key]=entry;gl.glBindTexture(0x0de1,entry[1].value)
        gl.glDisable(0x0bc0);gl.glEnable(0x0de1);gl.glTexEnvi(0x2300,0x2200,0x2100);gl.glEnableClientState(0x8078)
        gl.glTexCoordPointer(2,0x1406,0,uv.ctypes.data)

    def _bind_visibility(self,geometry):
        mask=geometry.visibility_texture;uv=geometry.visibility_uv;threshold=geometry.visibility_threshold
        if mask.dtype!=np.uint8 or mask.ndim!=2 or not mask.flags.c_contiguous or max(mask.shape)>16384:
            raise ValueError('Invalid visibility texture')
        if uv is None or uv.shape!=(len(geometry.positions),2) or uv.dtype!=np.float32 or not uv.flags.c_contiguous or not np.isfinite(uv).all():
            raise ValueError('Invalid visibility coordinates')
        if threshold is None or not math.isfinite(threshold) or not 0<=threshold<=1:raise ValueError('Invalid visibility threshold')
        gl=self.gl
        if self._visibility_id is None:
            maximum=C.c_int();gl.glGetIntegerv(0x0d33,C.byref(maximum))
            if max(mask.shape)>maximum.value:raise RuntimeError('Graphics device cannot hold the recovered visibility map')
            self._visibility_id=C.c_uint();gl.glGenTextures(1,C.byref(self._visibility_id))
        gl.glBindTexture(0x0de1,self._visibility_id.value)
        if self._visibility_source is not mask:
            gl.glPixelStorei(0x0cf5,1)
            gl.glTexImage2D(0x0de1,0,0x803c,mask.shape[1],mask.shape[0],0,0x1906,0x1401,mask.ctypes.data)
            for key,value in ((0x2801,0x2601),(0x2800,0x2601),(0x2802,0x812f),(0x2803,0x812f)):
                gl.glTexParameteri(0x0de1,key,value)
            self._visibility_source=mask
        # Alpha contains visibility, so surviving fragments satisfy mask <= threshold.
        gl.glTexEnvi(0x2300,0x2200,0x2100);gl.glAlphaFunc(0x0203,threshold)
        gl.glEnable(0x0de1);gl.glEnable(0x0bc0);gl.glEnableClientState(0x8078)
        gl.glTexCoordPointer(2,0x1406,0,uv.ctypes.data)

    def _bind_color(self,geometry):
        image=geometry.color_texture;uv=geometry.color_uv;indices=geometry.color_indices
        if image.dtype!=np.uint8 or image.ndim!=3 or any(n not in (2048,4096,8192) for n in image.shape[:2]) or image.shape[2]!=4 or not image.flags.c_contiguous:
            raise ValueError('Invalid terrain color texture')
        if uv is None or uv.shape!=(len(geometry.positions),2) or uv.dtype!=np.float32 or not uv.flags.c_contiguous or not np.isfinite(uv).all():
            raise ValueError('Invalid terrain color coordinates')
        if indices is None or indices.dtype!=np.uint32 or indices.ndim!=1 or len(indices)%3 or not indices.flags.c_contiguous or np.any(indices>=len(geometry.positions)):
            raise ValueError('Invalid textured terrain triangles')
        threshold=geometry.visibility_threshold
        if threshold is None or not math.isfinite(threshold) or not 0<=threshold<=1:raise ValueError('Invalid texture visibility threshold')
        gl=self.gl;key=id(image);entry=self._color_cache.get(key)
        if entry is None:
            maximum=C.c_int();gl.glGetIntegerv(0x0d33,C.byref(maximum))
            if maximum.value<max(image.shape[:2]):raise RuntimeError('Graphics device cannot hold the terrain color region')
            from terrain_mip_cache import cached_mip_chain
            texture=C.c_uint();gl.glGenTextures(1,C.byref(texture));gl.glBindTexture(0x0de1,texture.value)
            try:
                gl.glPixelStorei(0x0cf5,1)
                for level,pixels in enumerate(cached_mip_chain(image)):
                    gl.glTexImage2D(0x0de1,level,0x8058,pixels.shape[1],pixels.shape[0],0,0x1908,0x1401,pixels.ctypes.data)
                for setting,value in ((0x2801,0x2703),(0x2800,0x2601),(0x2802,0x812f),(0x2803,0x812f)):
                    gl.glTexParameteri(0x0de1,setting,value)
                if self._terrain_anisotropy>1:gl.glTexParameterf(0x0de1,0x84fe,self._terrain_anisotropy)
                error=gl.glGetError()
                if error:raise RuntimeError(f'Terrain texture upload failed: 0x{error:x}')
            except BaseException:
                gl.glDeleteTextures(1,C.byref(texture))
                if self._color_id is not None:gl.glBindTexture(0x0de1,self._color_id.value)
                raise
            if len(self._color_cache)>=10:
                oldest=next(iter(self._color_cache));old=self._color_cache.pop(oldest)
                gl.glDeleteTextures(1,C.byref(old[1]))
            entry=(image,texture,level+1)
        else:
            self._color_cache.pop(key)
            gl.glBindTexture(0x0de1,entry[1].value)
        self._color_cache[key]=entry
        self._color_source,self._color_id,self._color_mip_levels=entry
        gl.glTexEnvi(0x2300,0x2200,0x2100);gl.glAlphaFunc(0x0203,threshold)
        gl.glEnable(0x0de1);gl.glEnable(0x0bc0);gl.glEnableClientState(0x8078)
        gl.glTexCoordPointer(2,0x1406,0,uv.ctypes.data)

    def close(self):
        if self.context:
            self.current(self.dc,self.context)
            if self._surface is not None:self._surface.close();self._surface=None
            if self._hangar is not None:self._hangar.close();self._hangar=None
            if self._sharp_rock is not None:self._sharp_rock.close();self._sharp_rock=None
            if self._road is not None:self._road.close();self._road=None
            if self._water_surface is not None:self._water_surface.close();self._water_surface=None
            if self._snow is not None:self._snow.close();self._snow=None
            for pixels,texture in self._skin_cache.values():self.gl.glDeleteTextures(1,C.byref(texture))
            self._skin_cache.clear()
            for image,texture,levels in self._color_cache.values():self.gl.glDeleteTextures(1,C.byref(texture))
            self._color_cache.clear();self._color_id=None;self._color_source=None;self._color_mip_levels=0
            if self._visibility_id is not None:
                self.current(self.dc,self.context);self.gl.glDeleteTextures(1,C.byref(self._visibility_id))
                self._visibility_id=None;self._visibility_source=None
            self.current(None,None);self.deletecontext(self.context);self.context=None
        if self.dc:self.releasedc(self.hwnd,self.dc);self.dc=None
        if self.hwnd:self.destroy(self.hwnd);self.hwnd=None


def world_positions(positions,location,rotation):
    """Saved CharacterMesh0 relative transform followed by the recorded actor rotation.

    This intentionally has no growth scaling, procedural animation or runtime overrides.
    """
    pitch,yaw,roll=[math.radians(x) for x in rotation]
    cp,sp,cy,sy,cr,sr=math.cos(pitch),math.sin(pitch),math.cos(yaw),math.sin(yaw),math.cos(roll),math.sin(roll)
    rotation_matrix=np.array([[cp*cy,sr*sp*cy-cr*sy,-(cr*sp*cy+sr*sy)],
                              [cp*sy,sr*sp*sy+cr*cy,cy*sr-cr*sp*sy],[sp,-sr*cp,cr*cp]])
    relative=np.array([[0,1,0],[-1,0,0],[0,0,1]],dtype=float)
    local=np.asarray(positions)@relative.T+np.array([0,0,-201])
    return local@rotation_matrix.T+np.asarray(location)
