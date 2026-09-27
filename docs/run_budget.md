# M3/M4 run budget (pilot evidence and planning options)

## Scope and status

This is an evidence-backed planning estimate for a 30-day machine-time window, with at most one D-Flow FM job and one DualSPHysics job running concurrently. It separates measured pilot values from domain scaling estimates.

M3 Phase 0 has a working, hand-reviewed D-Flow FM Teesta case and a kernel success record. The M4 pilot has three real DualSPHysics 3D benchmark runs. Neither pilot is a site-calibrated production case: M3's inputs are placeholders and its independent generator still fails the recorded Phase 3 reproduction checks; M4's benchmark is a stock dam-break box rather than Teesta or Chamoli terrain. D-Flow FM is serial-only on this host. The installed bundle has no MPI launcher, partitioner, or partitioned mesh, so no MPI timing was available.

The Teesta production far-field grid/domain and breach facts remain placeholders. `sites/rishiganga.yaml` and the event reconstruction files for Chamoli are absent. Rishi Ganga 2021 was a rock-ice avalanche/mass flow, not a dam breach; a clear-water FM run would be a limited routing comparison, not a physical mass-flow reconstruction. No production-quality site budget can be claimed for Chamoli until its site/domain inputs exist.

## Measured D-Flow FM timings

The short runs use the same frozen Teesta pilot scenario and 9,000 s stop time (2 h spin-up plus 30 min after t0), 120 s map interval, lean depth/velocity maps, serial D-Flow FM 1.2.184, and the existing 33,018-face pilot domain. The refined variant applies one MeshKernel Casulli refinement and samples the existing pilot bed/friction fields onto the new mesh. The third timing was not run; two resolution points satisfy the requested short-run comparison. Timings below are actual solver wall time and the measured post-processing call, not a performance-model fit.

| Mesh used by kernel | MeshKernel-generated counts (nodes / edges / faces) | Written-net reread counts | FM wall time | Peak RAM | Raw `_map.nc` | `_his.nc` | Post-processing wall time | Case + post-processing outputs, raw map kept |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Pilot, 90 m source-grid scale | 18,034 / 51,051 / 33,018 | 18,034 / 51,051 / 33,018 | 13.21 s | 228 MiB | 46,126,676 B | 25,780 B | 2.71 s | 54,719,722 B |
| One refinement | 104,682 / 206,452 / 98,121 | 104,682 / 206,318 / 98,121 | 278.51 s | 623 MiB | 144,177,500 B | 25,780 B | 7.52 s | 169,718,240 B |

The refined kernel run completed without a `.dia` `** ERROR` and wrote both NetCDF outputs. Its written net reread has 134 fewer edges than the generated in-memory mesh. This is a writer round-trip mismatch against M3 rule 3, so the timing is useful as an exploratory solver measurement, not an accepted generated-mesh check. The baseline pilot mesh does pass the exact count and coordinate round-trip check.

The frozen 30-hour, 33,018-face pilot run is the only full-event FM anchor: 475.09 s solver runtime, 234,048 KB peak RAM, 481,977,476 B raw map, and 236,980 B history. Running contract post-processing over this full map took 5.07 s. The total case and post-processing footprint was 493,389,090 B with the raw map retained, or 11,411,614 B after removing `_map.nc` (removal is only after post-processing succeeds and metadata validates).

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

The following extrapolations use the frozen 33,018-face, 30-hour pilot as a linear cell-count anchor. That is a coarse planning model only: the refined run was much slower than simple cell scaling would predict, and site topography, time-step behavior, mesh quality, map interval, and SPH particle counts can change costs materially.

| Option | Resolution and scenario target per site | Attempts with 30% failure allowance | Approximate FM budget for both sites | 30-day fit |
|---|---|---:|---:|---|
| A — lower-risk training set | 90 m; 24 design + 5 holdout + 1 historical = 30 successful records/site | 43/site, 86 total | At Teesta's provisional full-domain 90 m equivalent of 1.41 M cells: about 5.7 h/run × 86 = 490 h (20.4 days), before M4 cost and workflow overhead | Fits only if the unknown Chamoli domain and per-run M4 cost stay within the remaining time; reduces training below M5's default 30 design points |
| **B — M5-default design (provisional recommendation)** | 90 m; 30 design + 5 holdout + 1 historical = 36 successful records/site | 52/site, 104 total | About 5.7 h/run × 104 = 593 h (24.7 days), using the same Teesta-equivalent 1.41 M cell assumption | Fits narrowly on the FM stream if Chamoli is comparable; leaves about 5 days for overhead, but no measured site SPH allowance |
| C — Teesta 30 m far-field grid | 30 m; 30 design + 5 holdout + 1 historical = 36 records/site | 52/site, 104 total | Teesta's provisional 12.7 M cells imply about 50.8 h/run; Teesta alone would use about 2,642 h (110 days) | Does not fit 30 days; at most 14 Teesta attempts, roughly 9 successful records at a 70% success rate, before Chamoli or SPH work |

For option B, the 1.41 M-cell estimate is the Teesta 12.7 M-cell, 30 m estimate divided by nine for 90 m cells. It is not a sourced Chamoli mesh size. The recommendation is to plan around option B only as a provisional ceiling, retain a historical Teesta 2023 scenario, reserve one Chamoli 2021 validation record with a clear-water/mass-flow caveat, and re-evaluate as soon as the Chamoli config and both pilot site meshes exist. Option A is the safer schedule if a 24-point training design is accepted. Option C is not feasible in the stated window.

Storage also needs an explicit quota. The measured 33,018-face full pilot map is about 482 MB at a 120 s map interval. At the production generator's 60 s interval, linear scaling gives roughly 41 GB per 30-hour run at 1.41 M faces (90 m Teesta-equivalent) and roughly 371 GB per run at 12.7 M faces (30 m Teesta estimate), before any other fields. These are extrapolations, not measured outputs. Deleting `_map.nc` after validated post-processing reduces retained disk, but peak free space still has to cover the raw map while a run is active. M3 post-processing currently loads complete timestep-by-face depth and velocity arrays; at the 90 m domain estimate those arrays alone exceed the 16 GB RAM budget. Chunked post-processing and an output-size check are prerequisites before a full-domain campaign.

## Demo-mode setting options (~15 minutes end to end)

1. **Measured pilot-sized route:** at most 33,018 FM faces, 30-hour stop, 120 s map interval, depth and velocity map fields only, and one scenario. FM plus full-map post-processing took about 480 s (8.0 min); pairing this with the 9.8–20.7 s stock SPH benchmark keeps measured solver/post-processing time under 8.5 min. That leaves about 6.5 min for setup, which was not measured. This is not evidence that a Teesta or Chamoli SPH case will meet the target.
2. **Short, lower-resolution route:** at most 33,018 faces, 9,000 s stop (2 h spin-up plus 30 min after t0), 120 s maps, one scenario, and `dp=0.020 m` for a tiny SPH demonstration. Measured FM + post-processing was about 16 s; benchmark SPH solver time was 9.8 s. This is a truncated, placeholder pilot demonstration, not a complete historical reconstruction.
3. **Higher-detail demo:** one-refinement mesh (98,121 faces), 9,000 s stop, lean maps, and one scenario. The measured FM run took 4 min 39 s and post-processing 7.5 s, still below 15 minutes before case generation and SPH setup. The net edge-count mismatch means this mesh is exploratory and does not pass the M3 writer gate.

Use option 1 when the demo must span the pilot's full simulated event window. Use option 2 when speed is the priority and label the truncation. None of these settings establishes a 15-minute end-to-end runtime on either production site; real site SPH post-processing and Chamoli terrain runs have not been timed.
