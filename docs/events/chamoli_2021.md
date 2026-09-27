# Chamoli / Rishi Ganga — 7 February 2021 event record

## Sourced reconstruction facts

Primary reference: Shugar et al. (2021), `src_042`, *Science* 373, eabh4455.

- **Event type:** a rock-and-ice avalanche from the north face of Ronti Peak transformed into
  a debris flow and downstream flood. It was not a glacial-lake outburst or a dam-break flood.
- **Onset:** 2021-02-07 04:51:13–04:51:21 UTC (10:21 IST stated in the paper).
- **Source:** about 5,500 m above sea level; the released rock and ice volume is estimated at
  26.9 million m³ with a 95% interval of 26.5–27.3 million m³.
- **Material/process:** approximately 80% rock and 20% glacier ice by volume; the ice melt and
  entrainment/transformation are part of the event dynamics. Clear-water D-Flow FM cannot
  reproduce those processes.
- **Rishiganga project observations:** roughly 15 km downstream of the source, reconstructed
  frontal speed is about 25 m/s; mean discharge is estimated at 8,200–14,200 m³/s, with event
  duration estimated at 10–20 minutes. The study says discharge-curve shapes are uncertain.
- **Tapovan observations:** just upstream of the project, frontal speed is about 16 m/s; below
  the project, about 12 m/s. Mean discharge downstream of Tapovan is estimated at 2,900–4,900
  m³/s. The project dam affects the flow and the study reports poorer model agreement there.
- **Depositional change:** about 40 m of debris blocked the Rishiganga near the Ronti Gad
  confluence; a lake roughly 700 m long formed behind the deposit. Total deposits at and just
  downstream of the confluence are estimated at about 8 million m³.

These are event-scale reconstructions and broad ranges, not a time-series boundary condition,
depth raster, or surveyed terrain surface. Do not convert the reported discharge range and
10–20 minute duration into a triangular hydrograph without an explicit modeling decision.

## M3/M5 implications

`backend/m3_dflowfm/generator.py` currently builds its upstream forcing from M2's dam-break
`hydrograph()` and assumes a configured dam with a breach location. That does not describe the
2021 Ronti Peak avalanche. `backend/m2_breach` also models breach hydrographs, not the avalanche,
debris entrainment, or mass-flow-to-flood transition. Treating the observed event as a dam breach
would misstate the event and violate the site-data rules.

The current handoff contract's M3/M4 run bundle has POI depth/velocity/WSE time series, but no
event-observation or routed-discharge schema. A future Chamoli validation run therefore needs an
approved source representation and a matching validation artifact before M5 can score it.
The standard `mass_flow_approximation` caveat identifies the limitation but does not define the
source hydrograph or physics.

## Still needed before an M3/M5 campaign

- An approved event representation for M3: for example, an externally sourced, time-resolved
  water-discharge boundary and location, plus an explicit decision about representing the mixed
  debris flow as clear-water routing. The primary paper reports a mean discharge range and
  uncertain duration, not the time-varying curve.
- A sourced GIS/DEM domain and model inlet/outlet geometry from the Ronti Gad source path through
  Rishiganga and the selected downstream limit. No `sites/rishiganga.yaml` or Chamoli terrain
  products currently exist.
- An event validation target in contract-compatible form. The cited paper does not supply a
  gridded observed maximum-depth or arrival-time dataset.
- Separate, sourced geometry and storage/breach inputs for the post-event Raunthi Gad landslide-
  lake scenario. Those inputs must not be conflated with the 2021 avalanche source.
