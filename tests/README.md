# Test layout

The test suite follows the public modules:

- `events/`: sync/async buses, hooks, periodic delivery, and named engines
- `mission/`: contracts, component composition, transitions, scheduling,
  conflicts, retries, and chains
- `mavlink/`: transport contracts, protocol codecs, concurrency, and runtime
- `dependency/`: injection, scopes, unregister, and cleanup behavior
- `test_core.py`: universal core contracts and integration smoke tests
- `test_imports.py`: standalone and `src/core` package layouts

Run everything from the repository root:

```bash
python -m unittest discover -v
python -m compileall -q .
```

Run one area while developing:

```bash
python -m unittest discover -s tests/events -t . -v
python -m unittest discover -s tests/mission -t . -v
python -m unittest discover -s tests/mavlink -t . -v
python -m unittest discover -s tests/dependency -t . -v
```
