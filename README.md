# SIH: Hydrodynamic Flood & Dam-Breach Digital Twin Engine

High-fidelity flood simulation, multi-scenario interpolation, and damage estimation platform for engineered dams, moraine dams (GLOF), and landslide dams.

## Architecture Highlights
- **Contracts-First Design**: Shared JSON Schemas (`contracts/schemas/`) validating backend, frontend, and solvers.
- **Multi-Fidelity Solvers**: Delft3D (2D hydrodynamics) and DualSPHysics (3D particle hydrodynamics).
- **Scenario Interpolation Engine**: Sub-second RBF/Kriging interpolation over precomputed simulation grids with dynamic confidence metrics.
- **Satellite Assimilation**: Near-real-time Sentinel-1/2 Earth observation integration via Google Earth Engine.
- **Modern React + Deck.gl UI**: Interactive 2D/3D flood map and impact analysis dashboard.
git 
