# M3 pilot workspace

The hand-reviewed D-Flow FM reference case and its builder live in `dflowfm/`. The retained
ANUGA fallback and frozen pilot exports are at this directory's top level.

From the repository root, build the D-Flow FM case and run its configured 30-hour pilot with:

```sh
.venv/bin/python backend/m3_pilot/dflowfm/build_teesta_pilot_s001__dflowfm.py
```

The builder reads `inputs/export/` and writes the generated case and compact review outputs to
`dflowfm/case/`. It requires the project Python environment, hydrolib-core, meshkernel, and the
installed D-Flow FM kernel at `~/delft3d/dflowfm-2026.01/lnx64/bin/`.

To produce contract-shaped run outputs for the available reproduction data, run:

```sh
.venv/bin/python backend/m3_pilot/postprocess_dflowfm.py
```

The reference case and site inputs are explicitly placeholder data; see `docs/m3_spec.md` and
`docs/m3_reproduction.md` for the modeling choices and reproduction status.
