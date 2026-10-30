"""Refresh notices for bundled dependencies from the active build environment."""
from importlib.metadata import distribution, PackageNotFoundError
from pathlib import Path
import shutil

root = Path(__file__).resolve().parent/'licenses'
packages = ['fastapi','starlette','uvicorn','python-multipart','numpy','scipy','scikit-image',
            'opencv-python-headless','onnxruntime-directml','pydantic','pydantic-core','anyio',
            'click','h11','typing-extensions','typing-inspection','annotated-types','annotated-doc',
            'networkx','pillow','imageio','tifffile','packaging','lazy-loader','sympy','mpmath','flatbuffers']
copied = []
for name in packages:
    try:
        dist = distribution(name)
    except PackageNotFoundError:
        continue
    for entry in dist.files or []:
        basename=Path(entry).name.lower()
        if not ('license' in basename or 'notice' in basename or basename.startswith('copying')):
            continue
        source = Path(dist.locate_file(entry))
        if not source.is_file():
            continue
        destination = root/name/str(entry).replace('../','').replace('..\\','')
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
        copied.append(f'{name} {dist.version}: {entry}')
root.mkdir(parents=True,exist_ok=True)
(root/'INDEX.txt').write_text('Third-party notices included with OCLAST 1.3.0\n\n'+'\n'.join(copied)+'\n',encoding='utf-8')
print(f'Collected {len(copied)} license/notice files.')

# Frontend libraries compiled into the desktop bundle, including their helpers.
import json
modules=Path(__file__).resolve().parents[1]/'frontend/node_modules'
queue=['react','react-dom','lucide-react','@radix-ui/react-toggle-group','@radix-ui/react-slot','class-variance-authority','clsx']
visited=set()
frontend_copied=[]
while queue:
    name=queue.pop()
    if name in visited: continue
    visited.add(name)
    folder=modules/name
    if not (folder/'package.json').is_file(): continue
    metadata=json.loads((folder/'package.json').read_text(encoding='utf-8'))
    queue.extend(metadata.get('dependencies',{}))
    for source in folder.iterdir():
        if source.is_file() and source.name.lower().startswith(('license','licence','notice','copying')):
            destination=root/'frontend'/name/source.name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,destination)
            frontend_copied.append(f"{name} {metadata['version']}: {source.name}")
with (root/'INDEX.txt').open('a',encoding='utf-8') as handle:
    handle.write('\nBundled frontend libraries\n'+'\n'.join(sorted(frontend_copied))+'\n')
print(f'Collected {len(frontend_copied)} frontend license/notice files.')
