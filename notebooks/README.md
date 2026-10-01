# notebooks/

Exploration lives here: plotting FIRMS detections, poking at HRRR wind, testing OR-Tools on
toy problems, calibration charts.

Rules so notebooks don't rot:
- Name them `<owner>_<topic>.ipynb`, e.g. `ml1_firms_eaton.ipynb`.
- Import shared types from `backend.schemas` so what you prototype already fits the contracts.
- Once something works, move it into `engines/` (or `scripts/`, `evaluation/`) with a
  test. The backend never imports a notebook.
- Clear large outputs before committing.

Run Jupyter with the project environment:

```bash
uv run --with jupyterlab jupyter lab
```
