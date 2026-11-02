"""Studio-only lighting controls over the shared renderer's existing light inputs."""
import ctypes as C
import math
import threading
from mesh_renderer import GLRenderer

# Ambient, directional diffuse, global fill. These are authored inspection
# presets, not decoded Unreal environment/exposure settings.
PRESETS = {
    'Studio': ((.30,.30,.30),(.80,.80,.80),(.20,.20,.20)),
    'Soft neutral': ((.40,.40,.40),(.35,.35,.35),(.20,.20,.20)),
    'Warm light': ((.20,.16,.12),(.95,.65,.35),(.10,.10,.10)),
    'Cool light': ((.12,.18,.30),(.35,.50,.80),(.08,.08,.08)),
    'Dim neutral': ((.02,.02,.02),(.08,.08,.08),(.01,.01,.01)),
}
DIRECTIONS = {
    'Original': (-.3,.7,1.),
    'Front': (0.,.2,1.),
    'Left': (-1.,.35,.6),
    'Right': (1.,.35,.6),
    'Behind': (0.,.5,-1.),
}


class StudioRenderer(GLRenderer):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.lighting = ('Studio','Original',1.)
        self.gl.glLightModelfv.restype=None
        self.gl.glLightModelfv.argtypes=[C.c_uint,C.POINTER(C.c_float)]

    @property
    def lighting_label(self):
        preset,direction,strength=self.lighting
        return f'{preset} / {direction} / {strength:g}x'

    def set_lighting(self,preset='Studio',direction='Original',strength=1.):
        if preset not in PRESETS or direction not in DIRECTIONS:
            raise ValueError('Choose a listed lighting preset and direction.')
        if type(strength) not in (int,float) or not math.isfinite(strength) or not 0<=strength<=2:
            raise ValueError('Light strength must be from 0 to 2.')
        self.lighting=(preset,direction,float(strength))

    def draw(self,*args,**kwargs):
        if threading.get_ident()!=self.thread:raise RuntimeError('OpenGL renderer used on another thread')
        if not self.context or not self.current(self.dc,self.context):raise RuntimeError('Rendering context is closed')
        preset,direction,strength=self.lighting
        ambient,diffuse,fill=PRESETS[preset];gl=self.gl
        # Define the light in camera space each frame; the shared draw routine
        # installs its camera view afterward. Defaults match the original path.
        gl.glMatrixMode(0x1700);gl.glLoadIdentity()
        gl.glLightfv(0x4000,0x1203,(C.c_float*4)(*DIRECTIONS[direction],0.))
        for key,values in ((0x1200,ambient),(0x1201,diffuse)):
            gl.glLightfv(0x4000,key,(C.c_float*4)(*(v*strength for v in values),1.))
        gl.glLightModelfv(0x0b53,(C.c_float*4)(*(v*strength for v in fill),1.))
        self.info['studio_lighting']=self.lighting_label
        return super().draw(*args,**kwargs)
