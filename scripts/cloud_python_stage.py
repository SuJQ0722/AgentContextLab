#!/usr/bin/env python3
"""Stage the existing standalone interpreter; no package install or venv edit."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import tarfile
import tempfile


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def validate_members(members,root_name):
    for member in members:
        name=PurePosixPath(member.name)
        if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0]!=root_name:
            raise ValueError('Archive path escapes standalone runtime')
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            raise ValueError('Special files are not allowed in runtime archive')
        if member.issym() or member.islnk():
            link=PurePosixPath(member.linkname)
            if link.is_absolute():raise ValueError('Absolute runtime archive link is forbidden')
            resolved=posixpath.normpath(str(name.parent/link) if member.issym() else str(link))
            if resolved!=root_name and not resolved.startswith(root_name+'/'):
                raise ValueError('Runtime archive link escapes extraction root')
        member.mode &= 0o777


def restore(manifest, *, allowed_parent=Path('/root/.local/share/uv/python')):
    target=Path(manifest['target_path'])
    if not target.is_absolute() or target.parent!=allowed_parent or target.name!=manifest['archive_root']:
        raise ValueError('Unexpected standalone interpreter installation destination')
    binary=target/manifest['interpreter_relative']
    if target.exists():
        if binary.exists() and sha(binary)==manifest['interpreter_sha256']:
            return {'restored':False,'existing_binary_verified':True}
        raise RuntimeError('Existing standalone runtime differs; it will not be overwritten')
    archive=Path(manifest['archive_path'])
    if sha(archive)!=manifest['archive_sha256']:
        raise ValueError('Standalone runtime archive SHA mismatch')
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.acl-python-',dir=target.parent))
    try:
        with tarfile.open(archive,'r:gz') as tar:
            members=tar.getmembers();validate_members(members,target.name)
            tar.extractall(staging,members=members)
        extracted=staging/target.name
        if sha(extracted/manifest['interpreter_relative'])!=manifest['interpreter_sha256']:
            raise ValueError('Extracted interpreter SHA mismatch')
        extracted.rename(target)
    finally:shutil.rmtree(staging,ignore_errors=True)
    return {'restored':True,'archive_sha256':manifest['archive_sha256']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args();source=args.source.resolve();binary=source/'bin/python3.11'
    if not binary.is_file():raise ValueError('Expected the existing standalone CPython 3.11 directory')
    args.archive.parent.mkdir(parents=True,exist_ok=True)
    if args.archive.exists():raise ValueError('Never overwrite a staged runtime archive')
    with tarfile.open(args.archive,'w:gz',compresslevel=3) as tar:tar.add(source,arcname=source.name)
    with tarfile.open(args.archive,'r:gz') as tar:validate_members(tar.getmembers(),source.name)
    value={'version':'standalone-python-stage-v1','archive_path':str(args.archive.resolve()),
           'archive_sha256':sha(args.archive),'archive_bytes':args.archive.stat().st_size,
           'archive_root':source.name,'target_path':str(source),'interpreter_relative':'bin/python3.11',
           'interpreter_sha256':sha(binary),'shared_venv_changed':False}
    args.manifest.parent.mkdir(parents=True,exist_ok=True)
    args.manifest.write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps({'manifest':str(args.manifest),'archive_bytes':value['archive_bytes'],'model_calls':0}))


if __name__=='__main__':main()
