# Controlled M4 launcher execution — 2026-09-27

This is the stock DualSPHysics 5.4.3 `CaseDambreakVal2D` controlled benchmark, not a target-site
or terrain-cut run. It verifies the existing campaign/worker → detached GenCase/DualSPHysics
launcher → solver output and run registration path. It provides no Teesta/Rishi Ganga or scientific
validation evidence.

- GenCase return code: 0; 0.100 s.
- DualSPHysics GPU solver return code: 0; 10.873 s.
- Total elapsed: 10.978 s.
- Sampled peak VRAM: 845 MiB (1 s `nvidia-smi` interval).
- Nonempty `Run.out` and particle outputs; worker integration test registered outputs.
- Full raw particle directory remains in the local pytest temp run (`/tmp/pytest-of-mprohit/pytest-128/test_stock_3d_dambreak_execute0/run/raw`, about 88 MB); the repository copy retains logs, the concise solver output, resource manifest and VRAM samples.

`execution.json`, `gencase.log`, `solver.log`, `solver_combined.log`, `Run.out`, and `nvidia_smi.csv`
are the preserved controlled-run evidence.
