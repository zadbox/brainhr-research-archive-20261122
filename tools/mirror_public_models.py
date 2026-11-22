"""Mirror only hash-identical, explicitly listed public model files to the release."""
from pathlib import Path
from hashlib import sha256
import argparse,json,os,subprocess,tempfile,time,urllib.request


def gh_json(endpoint):
    result=subprocess.run(['gh','api',endpoint],capture_output=True,text=True,check=True)
    return json.loads(result.stdout)


def assets(repository,release_id):
    return {a['name']:a for a in gh_json(f'repos/{repository}/releases/{release_id}/assets?per_page=100')}


def digest(path):
    h=sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(16*1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--object',required=True)
    parser.add_argument('--release-id',required=True,type=int)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'models/MODEL_OBJECTS.json').read_text())
    sources=json.loads((root/'models/PUBLIC_BINARY_SOURCES.json').read_text())
    source=next(s for s in sources if s['sha256']==args.object)
    obj=next(o for o in manifest['objects'] if o['sha256']==args.object)
    assert source['bytes']==obj['bytes']
    assert source['url'].startswith('https://huggingface.co/')
    repository=manifest['repository']
    existing=assets(repository,args.release_id)
    def present(part):
        a=existing.get(part['name'])
        return bool(a and a['state']=='uploaded' and a['size']==part['bytes'] and a.get('digest') in (None,'sha256:'+part['sha256']))
    if all(present(p) for p in obj['parts']):
        print('All object parts already verified',flush=True);return
    with tempfile.TemporaryDirectory(prefix='brainhr-model-') as temporary:
        folder=Path(temporary);model=folder/'source.bin'
        for attempt in range(3):
            try:
                request=urllib.request.Request(source['url'],headers={'User-Agent':'BrainHR-Archive/1.0'})
                h=sha256();size=0
                with urllib.request.urlopen(request,timeout=120) as response,model.open('wb') as out:
                    while True:
                        block=response.read(16*1024*1024)
                        if not block:break
                        out.write(block);h.update(block);size+=len(block)
                assert size==obj['bytes'] and h.hexdigest()==obj['sha256'],'Public source differs from the archived local object'
                break
            except Exception:
                if attempt==2:raise
                time.sleep(2**attempt)
        print(json.dumps({'source_verified':obj['sha256'],'bytes':size}),flush=True)
        offset=0
        with model.open('rb') as inp:
            for part in obj['parts']:
                existing=assets(repository,args.release_id)
                if present(part):offset+=part['bytes'];continue
                inp.seek(offset);path=folder/part['name'];remaining=part['bytes'];h=sha256()
                with path.open('wb') as out:
                    while remaining:
                        block=inp.read(min(16*1024*1024,remaining));assert block
                        out.write(block);h.update(block);remaining-=len(block)
                assert h.hexdigest()==part['sha256']
                for attempt in range(3):
                    result=subprocess.run(['gh','release','upload',manifest['release_tag'],'--repo',repository,str(path),'--clobber'],capture_output=True,text=True)
                    if result.returncode==0:break
                    if attempt==2:raise RuntimeError(result.stderr[-1200:])
                    time.sleep(2**attempt)
                actual=assets(repository,args.release_id)[part['name']]
                assert actual['state']=='uploaded' and actual['size']==part['bytes']
                assert actual.get('digest') in (None,'sha256:'+part['sha256'])
                path.unlink();offset+=part['bytes']
                print(json.dumps({'asset_verified':part['name'],'bytes':part['bytes']}),flush=True)
    summary=os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary,'a') as out:out.write(f'Verified model object `{obj["sha256"]}` and its {len(obj["parts"])} release parts.\n')


if __name__=='__main__':main()
