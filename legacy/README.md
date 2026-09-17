# Legacy scripts

These are the original standalone scripts that the `dxp_analyzer` package was
built from. They are kept for reference only and are **superseded** by the
package under `src/dxp_analyzer/`.

- `analisi_dxp_spotfire.py` — original inventory/table extractor.
- `documentazione_dxp.py` — original migration document generator (contained a
  full copy of the analyzer class).

Do not use these for new work; use the package instead:

```bash
dxp-analyzer all path/to/dashboard.dxp -o out
```
