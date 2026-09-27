# M3/M4 run budget (pilot evidence and planning options)

## Scope and status

This is an evidence-backed planning estimate for a 30-day machine-time window, with at most one D-Flow FM job and one DualSPHysics job running concurrently. It separates measured pilot values from domain scaling estimates.

M3 Phase 0 has a working, hand-reviewed D-Flow FM Teesta case and a kernel success record. The M4 pilot has three real DualSPHysics 3D benchmark runs. Neither pilot is a site-calibrated production case: M3's inputs are placeholders and its independent generator still fails the recorded Phase 3 reproduction checks; M4's benchmark is a stock dam-break box rather than Teesta or Chamoli terrain. D-Flow FM is serial-only on this host. The installed bundle has no MPI launcher, partitioner, or partitioned mesh, so no MPI timing was available.

The Teesta production far-field grid/domain and breach facts remain placeholders. `sites/rishiganga.yaml` and the event reconstruction files for Chamoli are absent. Rishi Ganga 2021 was a rock-ice avalanche/mass flow, not a dam breach; a clear-water FM run would be a limited routing comparison, not a physical mass-flow reconstruction. No production-quality site budget can be claimed for Chamoli until its site/domain inputs exist.

## Measured D-Flow FM timings

The repository contains two retained short D-Flow FM trial runs for the same frozen placeholder Teesta scenario, both stopped at 36,000 s (10 simulated hours), with 120 s map interval and serial D-Flow FM 1.2.184. They are at two nearby mesh sizes, not a controlled resolution sweep: the 26,888-face run uses the unsimplified mesh and has a different numerical configuration; the 33,018-face run uses the cleaned reference mesh. Their timings are real values recorded in each run's `run_meta_pilot.json`. The earlier table's 9,000 s / 98,121-face timings do not have corresponding retained run directories or metadata in this workspace, so they are excluded here. The two available runs are useful anchors only; do not interpret their runtime ratio as a resolution-scaling law.

| Mesh used by kernel | Nodes / edges / faces | FM wall time | Peak RAM | Raw `_map.nc` | `_his.nc` | Contract post-processing time | Case disk as recorded, raw map kept | Same case disk less `_map.nc` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Unsimplified trial mesh | 16,258 / 43,145 / 26,888 | 139.76 s | 201 MiB | 134,459,196 B | 83,380 B | Not recorded for this retained trial | 143,245,295 B | 8,786,099 B |
| Cleaned reference mesh | 18,034 / 51,051 / 33,018 | 5.49 s | 229 MiB | 164,995,076 B | 83,380 B | Not recorded for this retained trial | 175,390,782 B | 10,395,706 B |

Both trials completed and wrote map/history output, but the 26,888-face unsimplified mesh is not a production candidate. These are two different resolutions for one scenario and a truncated stop time, but the changed mesh cleanup/numerics make them unsuitable as a clean scaling experiment. An MPI run was unavailable: the installed kernel bundle has no MPI launcher or mesh partitioner, and there is no partitioned network. No MPI timing is claimed. The cleaned 33,018-face reference mesh passes the recorded exact count/coordinate writer round-trip check; see `docs/m3_spec.md`.

The frozen 30-hour, 33,018-face pilot run is the only full-event FM anchor: 475.09 s solver runtime, 234,048 KB peak RAM, 481,977,476 B raw map, and 236,980 B history. Contract post-processing over this full map took 5.07 s. The run metadata records 492,784,953 B for the case tree with the raw map retained; subtracting the map gives 10,807,477 B without it. A separate earlier total of 493,389,090 B included post-processing outputs and is not directly comparable with the case-tree measurement. Raw-map deletion is only after post-processing succeeds and metadata validates.

## Measured DualSPHysics pilot timings

These are real runs on an NVIDIA RTX 4060 Laptop GPU, DualSPHysics 5.4.355 / GenCase 5.4.354.01. Each is the same stock 3D dam-break benchmark with only particle spacing changed. Runtime and disk are for that benchmark workload; they are not a site near-field runtime estimate.

| `dp` | Particles | Cells | Solver wall time | Peak VRAM | Disk at capture |
|---:|---:|---:|---:|---:|---:|
| 0.0200 m | 17,446 | 960 | 9.77 s | 677 MiB | 92,554,114 B |
| 0.0150 m | 37,896 | 2,604 | 18.10 s | 695 MiB | 200,431,814 B |
| 0.0125 m | 60,887 | 4,736 | 20.67 s | 649 MiB | 321,739,608 B |

`backend/m4_pilot/` contains calibration logs and run summaries, not the benchmark's complete solver-output set. Therefore M4 post-processing wall time and the post-processed/raw-retained disk delta cannot be measured from this pilot. The site generator, terrain-cut STL, routed inlet hydrograph, and site SPH solver run are also missing. Do not use the benchmark's 10–21 s runtime as the site SPH cost in a commitment.

## Capacity model for 30 days

Thirty days is 2,592,000 s per solver stream. The campaign's 30 design scenarios plus 5 optional holdouts are the current M5 defaults. Add one historical reconstruction per site as a separate target: 36 successful scenario records per site. A 30% failure allowance means `ceil(36 / 0.70) = 52` attempts per site, or 104 attempts across Teesta and Chamoli. Historical records count toward those 36; an optional live-demo run is separate. FM and SPH streams can run concurrently, so the capacity limit is whichever site's total wall time is longer. Post-processing was 5.07 s on the full pilot and is negligible at pilot scale; the domain-scale extrapolations below do not include M4 post-processing because it has not been measured.

For a planning window of `N` days, each serial solver stream has `86,400 × N` seconds available. If one scenario requires one FM and one SPH run, and they may run concurrently, the pair capacity is `min(floor(86,400 × N / t_FM), floor(86,400 × N / t_SPH))`; preparation and post-processing must be added to the respective run times. The numerical options below use `N = 30`, matching the existing planning window. FM projections use the 33,018-face, 30-hour pilot as a linear cell-count anchor; this is coarse planning only. Mesh quality, time-step behavior, output cadence, setup, and SPH particle counts can change costs materially. Because there is no site SPH measurement, the options are FM-only capacity estimates, not verified FM+SPH campaign fits.

| Option | Resolution and scenario target per site | Attempts with 30% failure allowance | Approximate FM budget for both sites | 30-day fit |
|---|---|---:|---:|---|
| A — lower-risk training set | 90 m; 24 design + 5 holdout + 1 historical = 30 successful records/site | 43/site, 86 total | At Teesta's provisional full-domain 90 m equivalent of 1.41 M cells: about 5.7 h/run × 86 = 490 h (20.4 days), before M4 cost and workflow overhead | Fits only if the unknown Chamoli domain and per-run M4 cost stay within the remaining time; reduces training below M5's default 30 design points |
| **B — M5-default design (provisional recommendation)** | 90 m; 30 design + 5 holdout + 1 historical = 36 successful records/site | 52/site, 104 total | About 5.7 h/run × 104 = 593 h (24.7 days), using the same Teesta-equivalent 1.41 M cell assumption | Fits narrowly on the FM stream if Chamoli is comparable; leaves about 5 days for overhead, but no measured site SPH allowance |
| C — Teesta 30 m far-field grid | Teesta only: 30 m; 30 design + 5 holdout + 1 historical = 36 records. Chamoli resolution remains unknown. | Teesta: 52 attempts | Teesta's provisional 12.7 M cells imply about 50.8 h/run; 52 attempts require about 2,642 h (110 days) | Does not fit 30 days; about 14 Teesta attempts (roughly 9 successful at 70%) before Chamoli or SPH work |

For options A and B, the 1.41 M-cell estimate is the Teesta 12.7 M-cell, 30 m estimate divided by nine for 90 m cells. It is not a sourced Chamoli mesh size. The recommendation is to treat option A as the conservative planning choice and option B as a provisional ceiling only: both need a Chamoli site config/mesh and measured site-SPH timings before claiming the paired campaign fits. Each option includes one historical target per site; Chamoli 2021 is a rock-ice avalanche/mass-flow validation record, not a dam-breach reconstruction. Option C is not feasible in the stated window even for Teesta alone.

Storage also needs an explicit quota. The measured 33,018-face full pilot map is about 482 MB at a 120 s map interval. At the production generator's 60 s interval, linear scaling gives roughly 41 GB per 30-hour run at 1.41 M faces (90 m Teesta-equivalent) and roughly 371 GB per run at 12.7 M faces (30 m Teesta estimate), before any other fields. These are extrapolations, not measured outputs. Deleting `_map.nc` after validated post-processing reduces retained disk, but peak free space still has to cover the raw map while a run is active. M3 post-processing currently loads complete timestep-by-face depth and velocity arrays; at the 90 m domain estimate those arrays alone exceed the 16 GB RAM budget. Chunked post-processing and an output-size check are prerequisites before a full-domain campaign. For SPH, the three benchmark disk figures are total bytes at capture; the pilot does not retain enough of the output tree to measure a post-processed disk size or a cleanup delta.

## Demo-mode setting options (~15 minutes end to end)

1. **Full pilot window:** at most 33,018 FM faces, 30-hour stop, 120 s map interval, depth/velocity maps, one scenario. Measured solver plus contract post-processing is 480.16 s (8.0 min). Setup time and a site SPH run have not been measured, so a 15-minute site end-to-end claim is not supported.
2. **Truncated pilot demo:** at most 33,018 FM faces, 9,000 s stop (2 h spin-up plus 30 min after t0), 120 s maps, one scenario, and `dp=0.020 m` for a tiny SPH demonstration. The retained short FM trials ran 5.49–139.76 s at 36,000 s stop, but contract post-processing time for those trials and SPH post-processing time are unmeasured. The 9.77 s SPH value is the stock benchmark only. This is a proposed end-to-end setting, not a demonstrated 15-minute completion.
3. **Higher-detail demo:** no verified retained timing at 98,121 faces exists in this workspace. Do not use the earlier 4 min 39 s figure as a measured option until its run artifacts are restored.

Use option 1 when the demo must span the pilot's full simulated event window. Use option 2 when speed is the priority and label the truncation. None of these settings establishes a 15-minute end-to-end runtime on either production site; real site SPH solver/post-processing, case setup, and Chamoli terrain runs have not been timed. For an honest 15-minute demonstration, run the truncated pilot path first and expose completion timing before promising either real site.
