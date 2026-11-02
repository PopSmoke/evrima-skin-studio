"""Disposable disk cache of exact terrain preview mip levels, excluding the source."""
from pathlib import Path
import hashlib,json,os
import numpy as np
from replay_texture_filter import mip_chain

REVISION='terrain-preview-mips-1'
DISK_LIMIT=512*1024*1024

def cached_mip_chain(image,directory=None):
    # The normal generator owns source validation, including its first yield.
    generated=mip_chain(image);base=next(generated)
    root=Path(directory) if directory is not None else Path(__file__).parent/'texture-mip-cache'
    digest=hashlib.sha256(memoryview(image)).hexdigest()
    key=hashlib.sha256((REVISION+str(image.shape)+digest).encode()).hexdigest()
    folder=root/key;manifest=folder/'manifest.json'
    shapes=[];h,w=image.shape[:2]
    while max(h,w)>1:
        h,w=max(1,h//2),max(1,w//2);shapes.append((h,w,4))
    valid=False
    try:
        metadata=json.loads(manifest.read_text())
        if metadata['revision']!=REVISION or metadata['source_sha256']!=digest or len(metadata['levels'])!=len(shapes):
            raise ValueError('Mip cache metadata mismatch')
        for i,(row,shape) in enumerate(zip(metadata['levels'],shapes)):
            path=folder/f'{i+1}.npy'
            if row['shape']!=list(shape) or path.stat().st_size>np.prod(shape)+256:raise ValueError('Invalid cached mip size')
            with path.open('rb') as file:
                if hashlib.file_digest(file,'sha256').hexdigest()!=row['sha256']:raise ValueError('Cached mip hash mismatch')
        valid=True
    except (OSError,ValueError,KeyError,TypeError):pass
    yield base
    if valid:
        for i,shape in enumerate(shapes):
            pixels=np.load(folder/f'{i+1}.npy',allow_pickle=False)
            if pixels.shape!=shape or pixels.dtype!=np.uint8 or not pixels.flags.c_contiguous:raise ValueError('Invalid cached mip array')
            yield pixels
        return
    writable=False
    try:
        used=sum(p.stat().st_size for p in root.glob('*/*') if p.is_file())
        if used+sum(np.prod(s)+256 for s in shapes)<=DISK_LIMIT:
            folder.mkdir(parents=True,exist_ok=True);writable=True
    except OSError:pass
    rows=[]
    for i,pixels in enumerate(generated,1):
        if writable:
            try:
                path=folder/f'{i}.npy';temporary=folder/f'{i}.{os.getpid()}.tmp'
                with temporary.open('wb') as file:np.save(file,pixels,allow_pickle=False)
                temporary.replace(path)
                with path.open('rb') as file:checksum=hashlib.file_digest(file,'sha256').hexdigest()
                rows.append(dict(shape=list(pixels.shape),sha256=checksum))
            except OSError:writable=False
        yield pixels
    if writable:
        try:
            temporary=folder/f'manifest.{os.getpid()}.tmp'
            temporary.write_text(json.dumps(dict(revision=REVISION,source_sha256=digest,levels=rows)))
            temporary.replace(manifest)
        except OSError:pass
