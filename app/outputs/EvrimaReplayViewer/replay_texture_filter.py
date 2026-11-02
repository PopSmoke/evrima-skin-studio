"""Preview mip filtering for display-encoded terrain color and visibility weights.

These levels filter the recovered color bake; they do not reconstruct Unreal's
source-texture derivatives, virtual-texture residency or material evaluation LOD.
"""
import numpy as np


def _pad_cutout_colors(image,grid):
    """Extend edge RGB two texels inside each tile, preserving alpha and solid RGB."""
    columns,rows=grid
    output=image.copy()
    tiles=output.reshape(rows,image.shape[0]//rows,columns,image.shape[1]//columns,4)
    known=tiles[...,3]>0
    for _ in range(2):
        summed=np.zeros((*known.shape,3),np.uint16)
        count=np.zeros(known.shape,np.uint8)
        for axis in (1,3):
            for direction in (-1,1):
                target=[slice(None)]*4;source=target.copy()
                target[axis]=slice(1,None) if direction==1 else slice(None,-1)
                source[axis]=slice(None,-1) if direction==1 else slice(1,None)
                target=tuple(target);source=tuple(source)
                available=known[source]
                summed[target]+=tiles[source][...,:3].astype(np.uint16)*available[...,None]
                count[target]+=available
        fill=(~known)&(count>0)
        if not fill.any():break
        tiles[...,:3][fill]=np.rint(summed[fill]/count[fill,None]).astype(np.uint8)
        known|=fill
    return output


def cutout_atlas_mip_chain(image,grid):
    """Filter cutout color using alpha, stopping before neighboring tiles mix.

    Alpha remains average coverage; this does not thicken silhouettes. Terrain
    visibility weights deliberately retain their separate mip_chain behavior.
    """
    if not isinstance(image,np.ndarray) or image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=4 or not image.flags.c_contiguous:
        raise ValueError('Cutout source must be contiguous RGBA8')
    height,width=image.shape[:2]
    if any(n<1 or n>8192 or n&(n-1) for n in (height,width)):
        raise ValueError('Cutout source must have power-of-two dimensions')
    if not isinstance(grid,tuple) or len(grid)!=2 or any(type(n) is not int or n<1 or n&(n-1) for n in grid):
        raise ValueError('Cutout atlas grid must contain two power-of-two integers')
    columns,rows=grid
    if width%columns or height%rows:raise ValueError('Invalid cutout atlas tile dimensions')
    values=np.arange(256,dtype=np.float32)/255
    linear=np.where(values<=.04045,values/12.92,((values+.055)/1.055)**2.4)
    current=image
    yield _pad_cutout_colors(current,grid)
    while current.shape[1]>columns and current.shape[0]>rows:
        alpha=current[...,3].astype(np.float32)
        total=alpha[::2,::2]+alpha[::2,1::2]+alpha[1::2,::2]+alpha[1::2,1::2]
        output=np.zeros((current.shape[0]//2,current.shape[1]//2,4),np.uint8)
        for channel in range(3):
            weighted=linear[current[...,channel]]*alpha
            summed=weighted[::2,::2]+weighted[::2,1::2]+weighted[1::2,::2]+weighted[1::2,1::2]
            average=np.divide(summed,total,out=np.zeros_like(summed),where=total>0)
            encoded=np.where(average<=.0031308,average*12.92,1.055*average**(1/2.4)-.055)
            output[...,channel]=np.rint(np.clip(encoded,0,1)*255).astype(np.uint8)
        output[...,3]=np.rint(total/4).astype(np.uint8)
        yield _pad_cutout_colors(output,grid)
        current=output


def mip_chain(image):
    if not isinstance(image,np.ndarray) or image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=4:
        raise ValueError('Mip source must be RGBA8')
    height,width=image.shape[:2]
    if any(n<1 or n>8192 or n&(n-1) for n in (height,width)):
        raise ValueError('Mip source must be power-of-two dimensions up to 8192')
    if not image.flags.c_contiguous:raise ValueError('Mip source must be contiguous')
    values=np.arange(256,dtype=np.float32)/np.float32(255)
    linear=np.where(values<=.04045,values/12.92,((values+.055)/1.055)**2.4)
    current=image
    yield current
    while max(current.shape[:2])>1:
        height,width=current.shape[:2];dy,dx=min(1,height-1),min(1,width-1)
        output=np.empty((max(1,height//2),max(1,width//2),4),np.uint8)
        for channel in range(3):
            plane=linear[current[...,channel]]
            average=(plane[::2,::2]+plane[::2,dx::2]+plane[dy::2,::2]+plane[dy::2,dx::2])*np.float32(.25)
            encoded=np.where(average<=.0031308,average*12.92,1.055*average**(1/2.4)-.055)
            output[...,channel]=np.rint(np.clip(encoded,0,1)*255).astype(np.uint8)
        # Alpha is a visibility weight, not opacity; never premultiply RGB by it.
        alpha=current[...,3].astype(np.uint16)
        output[...,3]=np.rint((alpha[::2,::2]+alpha[::2,dx::2]+alpha[dy::2,::2]+alpha[dy::2,dx::2])/4).astype(np.uint8)
        yield output
        current=output
