"""Offline wheel/sdist/npm acceptance. Use a pinned isolated build interpreter."""
import email
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ENV = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'NODE_PATH')}
ENV.update(PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
           SOURCE_DATE_EPOCH='1700000000', npm_config_offline='true', npm_config_audit='false', npm_config_fund='false')
PIP = os.environ.get('BOOKING_PIP_PYTHON', sys.executable)
WHEELHOUSE = Path(os.environ['BOOKING_BUILD_WHEELHOUSE']).resolve()


def run(*args, cwd, capture=False):
    return subprocess.run(args, cwd=cwd, env=ENV, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def inspect(wheel):
    with zipfile.ZipFile(wheel) as archive:
        assert all(n.startswith(('library_room_booking/', 'mathist_library_room_booking-')) for n in archive.namelist())
        metadata = email.message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith('/METADATA'))))
        assert metadata['Name'] == 'mathist-library-room-booking'
        assert metadata['Version'] == '0.0.0.dev1'
        assert metadata['Requires-Python'] == '>=3.11'
        assert metadata.get_all('Requires-Dist') == ['mathist-gmail-connector==0.0.0.dev1; extra == "gmail"']


def consume(wheel, target):
    target.mkdir()
    run(sys.executable, '-m', 'venv', '--without-pip', str(target/'venv'), cwd=target)
    python = str(target/'venv/bin/python')
    run(PIP, '-m', 'pip', '--python', python, 'install', '--no-index', '--no-deps', str(wheel), cwd=target)
    run(python, '-I', '-c', "import importlib.util, pathlib, sys, library_room_booking as p; assert pathlib.Path(p.__file__).is_relative_to(sys.prefix); assert all(importlib.util.find_spec(n) is None for n in ('meetup_management', 'gmail', 'google', 'PIL', 'mathist_gmail_connector'))", cwd=target)
    shutil.copy(ROOT/'tests/contracts.py', target/'contracts.py')
    run(python, '-I', '-B', str(target/'contracts.py'), str(ROOT/'contracts/time.json'), cwd=target)
    shutil.copy(ROOT/'tests/libcal_contracts.py', target/'libcal_contracts.py')
    run(python, '-I', '-B', str(target/'libcal_contracts.py'), cwd=target)
    shutil.copy(ROOT/'tests/email_contracts.py', target/'email_contracts.py')
    run(python, '-I', '-B', str(target/'email_contracts.py'), cwd=target)
    for name in ('gmail_connector_contracts.py',):
        shutil.copy(ROOT/'tests'/name, target/name)
        run(python, '-I', '-B', str(target/name), cwd=target)
    shutil.copy(ROOT/'tests/evidence_contracts.py', target/'evidence_contracts.py')
    run(python, '-I', '-B', str(target/'evidence_contracts.py'), cwd=target)
    for name in ('consumer_example.py', 'consumer_contracts.py'):
        shutil.copy(ROOT/'tests'/name, target/name)
    run(python, '-I', '-B', str(target/'consumer_example.py'), cwd=target)
    run(python, '-I', '-B', str(target/'consumer_contracts.py'), cwd=target)

    if gmail_wheelhouse := os.environ.get('BOOKING_GMAIL_WHEELHOUSE'):
        run(PIP, '-m', 'pip', '--python', python, 'install', '--no-index',
            '--find-links', str(Path(gmail_wheelhouse).resolve()), f'{wheel}[gmail]', cwd=target)
        run(python, '-I', '-c', 'import mathist_gmail_connector', cwd=target)
        run(python, '-I', '-B', str(target/'gmail_connector_contracts.py'), cwd=target)
        run(python, '-I', '-B', str(target/'consumer_contracts.py'), cwd=target)



assert importlib.metadata.version('setuptools') == '84.2.1'
print(sys.version, 'setuptools', importlib.metadata.version('setuptools'), flush=True)
for binary in ('node', 'npm'):
    print(run(binary, '--version', cwd=ROOT, capture=True).strip(), flush=True)
with tempfile.TemporaryDirectory(prefix='booking-offline-') as directory:
    tmp = Path(directory)
    ENV['npm_config_cache'] = str(tmp/'npm-cache')
    source = tmp/'source'
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns('.git', '.private', '__pycache__', '*.egg-info', 'build', 'dist', 'node_modules'))
    output = tmp/'artifacts'
    output.mkdir()
    run(sys.executable, '-c', 'from setuptools.build_meta import build_wheel, build_sdist; import sys; out=sys.argv[1]; build_wheel(out); build_sdist(out)', str(output), cwd=source)
    wheel = next(output.glob('*.whl'))
    inspect(wheel)
    consume(wheel, tmp/'wheel-consumer')
    with tarfile.open(next(output.glob('*.tar.gz'))) as archive:
        archive.extractall(tmp/'unpacked', filter='data')
    build = tmp/'build-venv'
    run(sys.executable, '-m', 'venv', '--without-pip', str(build), cwd=tmp)
    build_python = str(build/'bin/python')
    run(PIP, '-m', 'pip', '--python', build_python, 'install', '--no-index', '--find-links', str(WHEELHOUSE), '--require-hashes', '-r', str(ROOT/'requirements-build.txt'), cwd=tmp)
    rebuilt = tmp/'rebuilt'
    rebuilt.mkdir()
    run(build_python, '-c', 'from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])', str(rebuilt), cwd=next((tmp/'unpacked').iterdir()))
    wheel = next(rebuilt.glob('*.whl'))
    inspect(wheel)
    consume(wheel, tmp/'sdist-consumer')
    npm = tmp/'npm-consumer'
    npm.mkdir()
    (npm/'package.json').write_text('{"private":true,"type":"module"}')
    packed = json.loads(run('npm', 'pack', '--json', '--ignore-scripts', '--pack-destination', str(npm), cwd=source/'javascript', capture=True))
    assert {item['path'] for item in packed[0]['files']} == {'README.md', 'LICENSE.md', 'NOTICE', 'package.json', 'src/index.js', 'src/libcal.js'}
    run('npm', 'install', '--offline', '--ignore-scripts', '--no-audit', '--no-fund', str(npm/packed[0]['filename']), cwd=npm)
    shutil.copy(ROOT/'tests/contracts.mjs', npm/'contracts.mjs')
    run('node', 'contracts.mjs', str(ROOT/'contracts/time.json'), cwd=npm)
    shutil.copy(ROOT/'tests/libcal_contracts.mjs', npm/'libcal_contracts.mjs')
    run('node', 'libcal_contracts.mjs', str(ROOT/'contracts/providers.json'), cwd=npm)
print('Offline wheel, rebuilt sdist and npm contract consumption passed.', flush=True)
