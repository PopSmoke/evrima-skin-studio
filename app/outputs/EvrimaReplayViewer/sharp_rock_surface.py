"""Compatibility GPU material with bounded resources and explicit state restoration."""
import ctypes as C
import numpy as np

class SharpRockSurface:
    def __init__(self,gl,material):
        self.gl=gl;self.program=0;self.textures=[];self.functions={};self.saved=None
        gl.wglGetProcAddress.argtypes=[C.c_char_p];gl.wglGetProcAddress.restype=C.c_void_p
        declarations={
            'glCreateShader':(C.c_uint,[C.c_uint]),'glShaderSource':(None,[C.c_uint,C.c_int,C.POINTER(C.c_char_p),C.POINTER(C.c_int)]),
            'glCompileShader':(None,[C.c_uint]),'glGetShaderiv':(None,[C.c_uint,C.c_uint,C.POINTER(C.c_int)]),
            'glGetShaderInfoLog':(None,[C.c_uint,C.c_int,C.POINTER(C.c_int),C.c_char_p]),'glDeleteShader':(None,[C.c_uint]),
            'glCreateProgram':(C.c_uint,[]),'glAttachShader':(None,[C.c_uint,C.c_uint]),'glLinkProgram':(None,[C.c_uint]),
            'glGetProgramiv':(None,[C.c_uint,C.c_uint,C.POINTER(C.c_int)]),'glGetProgramInfoLog':(None,[C.c_uint,C.c_int,C.POINTER(C.c_int),C.c_char_p]),
            'glDeleteProgram':(None,[C.c_uint]),'glUseProgram':(None,[C.c_uint]),'glGetUniformLocation':(C.c_int,[C.c_uint,C.c_char_p]),
            'glUniform1i':(None,[C.c_int,C.c_int]),'glUniform4fv':(None,[C.c_int,C.c_int,C.POINTER(C.c_float)]),
            'glActiveTexture':(None,[C.c_uint]),'glClientActiveTexture':(None,[C.c_uint])}
        for name,(result,args) in declarations.items():
            address=gl.wglGetProcAddress(name.encode())
            if address in (None,0,1,2,3,C.c_void_p(-1).value):raise RuntimeError('Sharp rock shader support unavailable')
            self.functions[name]=C.WINFUNCTYPE(result,*args)(address)
        gl.glIsEnabled.argtypes=[C.c_uint];gl.glIsEnabled.restype=C.c_ubyte
        gl.glGetPointerv.argtypes=[C.c_uint,C.POINTER(C.c_void_p)];gl.glGetPointerv.restype=None
        active=self.integer(0x84e0);binding=self.integer(0x8069);shaders=[]
        try:
            if self.integer(0x8872)<10 or self.integer(0x8871)<6:raise RuntimeError('Insufficient sharp texture units')
            for kind,name in ((0x8b31,'sharp.vert'),(0x8b30,'sharp.frag')):
                raw=material.checked(name,material.meta['shaders'][name],32000).read_bytes()
                shader=self.call('glCreateShader',kind);shaders.append(shader)
                pointer=C.c_char_p(raw);length=C.c_int(len(raw));self.call('glShaderSource',shader,1,C.byref(pointer),C.byref(length))
                self.call('glCompileShader',shader);self.check(shader,False)
            self.program=self.call('glCreateProgram')
            for shader in shaders:self.call('glAttachShader',self.program,shader)
            self.call('glLinkProgram',self.program);self.check(self.program,True)
            self.locations={name:self.call('glGetUniformLocation',self.program,name.encode()) for name in ('layered','normalDetail','recoveredFrame','shorelineWetness','surfaceLighting')}
            for name,chain,srgb in material.textures():
                texture=C.c_uint();gl.glGenTextures(1,C.byref(texture));self.textures.append(texture)
                gl.glBindTexture(0x0de1,texture.value)
                for level,image in enumerate(chain):
                    gl.glTexImage2D(0x0de1,level,0x8c43 if srgb else 0x8058,image.shape[1],image.shape[0],0,0x1908,0x1401,image.ctypes.data)
                for key,value in ((0x2801,0x2703),(0x2800,0x2601),(0x2802,0x2901),(0x2803,0x2901),(0x813d,10)):gl.glTexParameteri(0x0de1,key,value)
                self.locations[name]=self.call('glGetUniformLocation',self.program,name.encode())
            self.names=[name for name,_,_ in material.textures()]
            if any(v<0 for v in self.locations.values()) or gl.glGetError():raise RuntimeError('Sharp rock shader setup failed')
        except BaseException:self.close();raise
        finally:
            for shader in shaders:self.call('glDeleteShader',shader)
            self.call('glActiveTexture',active);gl.glBindTexture(0x0de1,binding)
    def call(self,name,*args):return self.functions[name](*args)
    def integer(self,name):
        value=C.c_int();self.gl.glGetIntegerv(name,C.byref(value));return value.value
    def check(self,value,program):
        kind='Program' if program else 'Shader';status=C.c_int();self.call('glGet'+kind+'iv',value,0x8b82 if program else 0x8b81,C.byref(status))
        if not status.value:
            log=C.create_string_buffer(8192);self.call('glGet'+kind+'InfoLog',value,len(log),None,log)
            raise RuntimeError('Sharp rock '+kind+': '+log.value.decode('utf-8','replace'))
    def begin(self,data):
        gl=self.gl
        if self.saved is not None:raise RuntimeError('Nested sharp material')
        state=dict(active=self.integer(0x84e0),client=self.integer(0x84e1),program=self.integer(0x8b8d),bindings=[],arrays=[])
        self.saved=state
        try:
            for unit in range(10):
                self.call('glActiveTexture',0x84c0+unit);state['bindings'].append(self.integer(0x8069));gl.glBindTexture(0x0de1,self.textures[unit].value)
            for unit,array in enumerate((data['uv'],data['local_positions'],data['local_normals'],data['colors'],data['frame_tangent'],data['frame_normal'])):
                if array.dtype!=np.float32 or not array.flags.c_contiguous:raise ValueError('Invalid sharp draw inputs')
                self.call('glClientActiveTexture',0x84c0+unit)
                pointer=C.c_void_p();gl.glGetPointerv(0x8092,C.byref(pointer))
                state['arrays'].append((self.integer(0x8088),self.integer(0x8089),self.integer(0x808a),pointer.value,bool(gl.glIsEnabled(0x8078))))
                gl.glTexCoordPointer(array.shape[1],0x1406,0,array.ctypes.data);gl.glEnableClientState(0x8078)
            self.call('glUseProgram',self.program)
            for unit,name in enumerate(self.names):self.call('glUniform1i',self.locations[name],unit)
            self.call('glUniform1i',self.locations['layered'],1)
            self.call('glUniform1i',self.locations['normalDetail'],int(data.get('normal_detail',True)))
            self.call('glUniform1i',self.locations['recoveredFrame'],int(data.get('recovered_frame',True)))
            self.call('glUniform1i',self.locations['shorelineWetness'],int(data.get('shoreline_wetness',True)))
            self.call('glUniform1i',self.locations['surfaceLighting'],int(data.get('surface_lighting',True)))
        except BaseException:self.end();raise
    def end(self):
        if self.saved is None:return
        state=self.saved;self.saved=None;gl=self.gl
        self.call('glUseProgram',state['program'])
        for unit,(size,kind,stride,pointer,enabled) in enumerate(state['arrays']):
            self.call('glClientActiveTexture',0x84c0+unit);gl.glTexCoordPointer(size,kind,stride,pointer)
            (gl.glEnableClientState if enabled else gl.glDisableClientState)(0x8078)
        for unit,binding in enumerate(state['bindings']):
            self.call('glActiveTexture',0x84c0+unit);gl.glBindTexture(0x0de1,binding)
        self.call('glActiveTexture',state['active']);self.call('glClientActiveTexture',state['client'])
    def close(self):
        self.end()
        for texture in self.textures:self.gl.glDeleteTextures(1,C.byref(texture))
        self.textures=[]
        if self.program:self.call('glDeleteProgram',self.program);self.program=0
