# Fresh consumer quickstart

Use Python 3.11+ with pip/venv and Git plus Node.js 20+ and npm.
The provisioning interpreter needs pip 22.3+ (`--python` support); it installs
into isolated venvs even on systems without ensurepip.
Commands below use a POSIX shell; on Windows use the venv's Scripts/python.exe
and equivalent copy/path commands. Python needs IANA timezone data for booking;
Linux/macOS normally supply it, while other consumers may install tzdata.
The recorded validation platform is described in [validation](validation.md).

Run in a new work directory. Resolve main once, record its full Git SHA, and use
that exact revision again to reproduce the source. The commands deliberately
build artifacts locally, without registry publication. The first build downloads
only the pinned build dependency; subsequent consumer installation is offline.

```sh
git clone https://github.com/Mathist-Consulting-LLC/library-room-booking-public.git
cd library-room-booking-public
REVISION=$(git rev-parse HEAD)
printf '%s\n' "$REVISION" > ../source-revision.txt
git checkout --detach "$REVISION"
SOURCE=$(pwd)
PIP_PYTHON=$(command -v python3)
"$PIP_PYTHON" -m pip --version
"$PIP_PYTHON" -m venv --without-pip ../build-env
BUILD_PYTHON="$(cd ../build-env && pwd)/bin/python"
"$PIP_PYTHON" -m pip --python "$BUILD_PYTHON" install --require-hashes -r requirements-build.txt
mkdir -p ../wheels
WHEELS="$(cd ../wheels && pwd)"
"$PIP_PYTHON" -m pip --python "$BUILD_PYTHON" wheel --no-build-isolation --no-deps . --wheel-dir "$WHEELS"
cd ..
mkdir consumer
cd consumer
"$PIP_PYTHON" -m venv --without-pip .venv
PYTHON="$(pwd)/.venv/bin/python"
"$PIP_PYTHON" -m pip --python "$PYTHON" install --no-index --find-links "$WHEELS" 'mathist-library-room-booking==0.0.0.dev1'
"$PYTHON" -I -c 'import pathlib,sys,library_room_booking as p; assert pathlib.Path(p.__file__).is_relative_to(sys.prefix); print("installed package")'
cp "$SOURCE/examples/availability.py" .
cp "$SOURCE/tests/consumer_example.py" .
"$PYTHON" -I availability.py
"$PYTHON" -I consumer_example.py
```

Expected first script output:

```text
installed package
room=30; outcome=available; calls=3
invalid offset rejected; no booking attempted
```

The realistic [consumer example](../tests/consumer_example.py) prints the exact
[workflow output](examples/workflow-output.txt): three status projections in
`site_updates` and the same three in `optional_email_sink`, then the alternate
provider/recovery success line. It models submission, pending, explicit selected
approval and no replay after a lost response. The sink sends no mail; permissions,
claims and storage are in-memory examples. Gmail is not required. All provider
and inbox responses are synthetic.

## JavaScript consumer

Continue in the separate consumer directory with SOURCE still set. The Python
and npm names differ; do not install a same-named registry package by accident.

```sh
(cd "$SOURCE/javascript" && npm pack --ignore-scripts --pack-destination "$WHEELS")
printf '{"private":true,"type":"module"}\n' > package.json
npm install --offline --ignore-scripts --no-audit --no-fund "$WHEELS/mathist-library-room-booking-0.0.0-dev.1.tgz"
cp "$SOURCE/examples/availability.mjs" .
node availability.mjs
```

Expected output:

```text
room=30; outcome=available; calls=1
availability=available; calls=2
booking=unsupported; no booking attempted
```

This installs the packed public package rather than importing from source.
For broader coverage follow [validation](validation.md). npm pack remains local;
the package's private flag prevents ordinary registry publication.

Keep `source-revision.txt`, built artifact SHA256 and your consumer lockfile in
your own reproducibility record. A future same-version source build can differ;
Git SHA plus artifact hash is the pin. Read [setup](setup.md) before replacing
fixtures, [API](api.md) for returned shapes, and [recovery](recovery.md) for errors.
These commands create only local environments/artifacts. To clean up, remove
those directories after retaining any records you need.
