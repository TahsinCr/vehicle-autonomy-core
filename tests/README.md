# Test layout

The test suite is organized around the public packages:

- `dependency/`: registration, injection, scopes and resource cleanup
- `events/`: synchronous and asynchronous buses, hooks and periodic delivery
- `mission/`: lifecycle, scheduling, transitions, conflicts, retries and chains
- `mavlink/`: transport contracts, codecs, concurrency and runtime behavior
- `test_core.py`: shared core contracts and integration smoke tests
- `test_package_layout.py`: `src/core`, relative-import and metadata guarantees

Run the complete suite from the repository root:

```bash
python tests/run.py
```

The runner discovers every `test*.py` file under `tests` and exits with a
non-zero status when a test fails. The equivalent standard-library command is:

```bash
python -m unittest discover -v
```

Run a focused area while developing:

```bash
python -m unittest discover -s tests/dependency -t . -v
python -m unittest discover -s tests/events -t . -v
python -m unittest discover -s tests/mission -t . -v
python -m unittest discover -s tests/mavlink -t . -v
```

Finish with a source compilation check:

```bash
python -m compileall -q .
```

The tests do not require vehicle hardware. MAVLink-facing tests use fakes;
serial links, radios and hardware-in-the-loop behavior remain the consuming
vehicle project's responsibility.

The supported interpreter floor is Python 3.10. Run the complete suite on each
Python version claimed by a release when preparing a tag.
