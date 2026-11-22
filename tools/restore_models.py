"""Download and verify model objects from the private GitHub release."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import re
import subprocess
import tempfile


def digest(path):
    h=sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--object',dest='object_id',help='Full model-object SHA256')
    parser.add_argument('--principal',action='store_true',help='Restore only the principal QLoRA adapter')
    parser.add_argument('--all',action='store_true',help='Restore every distinct object')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,default=Path(__file__).resolve().parents[1]/'models/MODEL_OBJECTS.json')
    args=parser.parse_args()
    if sum((bool(args.object_id),args.principal,args.all))!=1:parser.error('Choose exactly one of --object, --principal or --all')
    manifest=json.loads(args.manifest.read_text())
    wanted=manifest['principal_adapter_sha256'] if args.principal else args.object_id
    objects=[o for o in manifest['objects'] if args.all or o['sha256']==wanted]
    if not objects:parser.error('Unknown model object')
    args.out.mkdir(parents=True,exist_ok=True)
    for obj in objects:
        oid=obj['sha256']
        if not re.fullmatch(r'[a-f0-9]{64}',oid):raise ValueError('Invalid object identifier')
        target=args.out/(oid+'.bin')
        if target.exists():
            if target.stat().st_size==obj['bytes'] and digest(target)==oid:
                print('Verified existing '+target.name,flush=True);continue
            raise FileExistsError('Refusing to replace a different file: '+str(target))
        with tempfile.TemporaryDirectory(prefix='brainhr-',dir=args.out) as temporary:
            folder=Path(temporary)
            for part in obj['parts']:
                name=part['name']
                if Path(name).name!=name or not re.fullmatch(r'w-[a-f0-9]{64}(?:-p[0-9]+of[0-9]+)?\.bin',name):raise ValueError('Invalid asset name')
                subprocess.run(['gh','release','download',manifest['release_tag'],'--repo',manifest['repository'],
                                '--pattern',name,'--dir',str(folder)],check=True)
                downloaded=folder/name
                if downloaded.stat().st_size!=part['bytes'] or digest(downloaded)!=part['sha256']:raise ValueError('Asset integrity failure: '+name)
            assembled=folder/'assembled.bin'
            with assembled.open('wb') as out:
                for part in obj['parts']:
                    with (folder/part['name']).open('rb') as f:
                        for block in iter(lambda:f.read(8*1024*1024),b''):out.write(block)
            if assembled.stat().st_size!=obj['bytes'] or digest(assembled)!=oid:raise ValueError('Assembled model integrity failure')
            assembled.rename(target)
        print('Restored '+str(target),flush=True)


if __name__=='__main__':main()
