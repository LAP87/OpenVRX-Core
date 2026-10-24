"""Record build inputs and accept only a fresh, timing-clean toolchain result."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inputs(root, top, copy_to=None):
    gw = root / 'gateware'
    paths = [gw / 'build.sh', gw / 'tools/build_manifest.py',
             gw / 'top' / f'{top}.v', gw / 'boards/tangnano20k.cst']
    paths += [p for p in (gw / 'rtl').iterdir() if p.suffix in ('.v', '.vh')]
    paths += [p for ext in ('cst', 'sdc', 'seed') if (p := gw / 'boards' / f'{top}.{ext}').exists()]
    hashes = {}
    for p in sorted(paths):
        name = p.relative_to(root)
        if copy_to is None:
            hashes[str(name)] = digest(p)
        else:
            # Hash the exact bytes the compiler will read, even if an editor
            # changes the original file and restores it during the build.
            data = p.read_bytes()
            hashes[str(name)] = hashlib.sha256(data).hexdigest()
            copied = copy_to / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(data)
    return hashes


def git_state(root):
    def git(*args):
        try:
            r = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
        except FileNotFoundError:
            return None
        return r.stdout.strip() if r.returncode == 0 else None
    commit = git('rev-parse', 'HEAD')
    status = git('status', '--porcelain') if commit else None
    return dict(commit=commit, dirty=bool(status) if status is not None else None)


def tool_versions():
    versions = {}
    for package in ('yowasp-yosys', 'yowasp-nextpnr-himbaechel-gowin', 'apycula'):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def route_result(log):
    text = log.read_text()
    if re.search(r'(^|[\s:])ERROR(?:\s|:)', text, re.I | re.M):
        raise ValueError('nextpnr log contains ERROR')
    pattern = re.compile(r"Max frequency for clock\s+'([^']+)':\s*([0-9.]+) MHz \((PASS|FAIL) at ([0-9.]+) MHz\)")
    clocks = {}
    # nextpnr reports placement and routing: retain the last result per clock.
    for clock, maximum, status, required in pattern.findall(text):
        clocks[clock] = dict(max_mhz=float(maximum), required_mhz=float(required), passed=status == 'PASS')
    if not clocks:
        raise ValueError('nextpnr log has no clock timing result')
    if any(not c['passed'] or c['max_mhz'] < c['required_mhz'] for c in clocks.values()):
        raise ValueError('nextpnr clock timing did not pass')
    return clocks


def finish(root, snapshot, prefix, output):
    record = json.loads(snapshot.read_text())
    if inputs(root, record['top']) != record['inputs']:
        raise ValueError('build inputs changed while the tools were running')
    record['timing'] = route_result(snapshot.parent / f'{prefix}.pnr.log')
    artifacts = {}
    for ext in ('fs', 'cst', 'synth.json', 'stat.txt', 'yosys.log', 'pnr.json', 'pnr.log'):
        path = snapshot.parent / f'{prefix}.{ext}'
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f'missing or empty build artifact: {path.name}')
        artifacts[path.name] = digest(path)
    sdc = snapshot.parent / f'{prefix}.sdc'
    if sdc.exists():
        artifacts[sdc.name] = digest(sdc)
    record.update(completed_utc=datetime.now(timezone.utc).isoformat(), bitstream=f'{prefix}.fs', artifacts=artifacts)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')


def verify(manifest, root=None):
    record = json.loads(manifest.read_text())
    if record.get('format_version') != 1 or not record.get('completed_utc'):
        raise ValueError('not a completed build manifest')
    artifacts = record['artifacts']
    if record['bitstream'] not in artifacts:
        raise ValueError('manifest has no bitstream hash')
    for name, expected in artifacts.items():
        if Path(name).name != name or digest(manifest.parent / name) != expected:
            raise ValueError(f'build artifact does not match its manifest: {name}')
    if root is not None and inputs(root.resolve(), record['top']) != record['inputs']:
        raise ValueError('current sources do not match the build manifest')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    begin = commands.add_parser('snapshot')
    begin.add_argument('root', type=Path)
    begin.add_argument('top')
    begin.add_argument('output', type=Path)
    begin.add_argument('--copy-to', type=Path)
    for option in ('freq', 'seed', 'pull', 'phase', 'ioreg', 'vinterp', 'hdmi', 'mspi', 'tvp', 'low', 'devcmd',
                   'uart-baud', 'digin'):
        begin.add_argument(f'--{option}', default='')
    route = commands.add_parser('route')
    route.add_argument('log', type=Path)
    end = commands.add_parser('finish')
    end.add_argument('root', type=Path)
    end.add_argument('snapshot', type=Path)
    end.add_argument('prefix')
    end.add_argument('output', type=Path)
    check = commands.add_parser('verify')
    check.add_argument('manifest', type=Path)
    check.add_argument('--root', type=Path, help='also compare with current source and constraint files')
    args = parser.parse_args()
    try:
        if args.command == 'route':
            route_result(args.log)
        elif args.command == 'verify':
            verify(args.manifest, args.root)
            print(f'verified {args.manifest}')
        elif args.command == 'snapshot':
            record = dict(format_version=1, top=args.top, inputs=inputs(args.root.resolve(), args.top, args.copy_to),
                          git=git_state(args.root), tool_versions=tool_versions(),
                          options=dict(freq_mhz=args.freq, seed=args.seed, pull=args.pull, sdram_phase=args.phase,
                                       ioreg=args.ioreg, vinterp=args.vinterp, hdmi=args.hdmi, mspi=args.mspi,
                                       tvp_addr=args.tvp, low=args.low, devcmd=args.devcmd,
                                       uart_baud=args.uart_baud, digin=args.digin))
            args.output.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
        else:
            finish(args.root.resolve(), args.snapshot, args.prefix, args.output)
    except (OSError, ValueError, KeyError) as e:
        parser.exit(1, f'build rejected: {e}\n')


if __name__ == '__main__':
    main()
