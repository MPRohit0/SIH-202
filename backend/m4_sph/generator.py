"""M4: DualSPHysics near-field case generation (`docs/handoff_contract.md` §4.4).

`pilot_case_spec()` reproduces `m4_pilot`'s calibration run (the stock DualSPHysics 5.4.3 example
`examples/main/01_DamBreak/CaseDambreakVal2D_Def.xml`) as a `case_xml.CaseSpec`, to check the
writer against a real, GenCase-validated file (`tests/m4_sph/test_pilot_regen.py`) before it is
used to build real near-field cases.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from .case_xml import CaseSpec, E, SwlGauge


def pilot_case_spec() -> CaseSpec:
    """`CaseDambreakVal2D` (Koshizuka & Oka 1996 dam-break validation), as shipped with
    DualSPHysics 5.4.3. 2D (`y` fixed at 0), no boundary STL, no inlet — used only to validate
    `case_xml`'s writer against a real GenCase file."""
    constants = [
        ("gravity", {"x": 0, "y": 0, "z": -9.81, "comment": "Gravitational acceleration", "units_comment": "m/s^2"}),
        ("rhop0", {"value": 1000, "comment": "Reference density of the fluid", "units_comment": "kg/m^3"}),
        ("rhopgradient", {"value": 2, "comment": "Initial density gradient 1:Rhop0, 2:Water column, 3:Max. water height (default=2)"}),
        ("hswl", {"value": 0, "auto": True, "comment": "Maximum still water level to calculate speedofsound using coefsound", "units_comment": "metres (m)"}),
        ("gamma", {"value": 7, "comment": "Polytropic constant for water used in the state equation"}),
        ("speedsystem", {"value": 0, "auto": True, "comment": "Maximum system speed (by default the dam-break propagation is used)"}),
        ("coefsound", {"value": 20, "comment": "Coefficient to multiply speedsystem"}),
        ("speedsound", {"value": 0, "auto": True, "comment": "Speed of sound to use in the simulation (by default speedofsound=coefsound*speedsystem)"}),
        ("coefh", {"value": 1.0, "comment": "Coefficient to calculate the smoothing length (h=coefh*sqrt(3*dp^2) in 3D)"}),
        ("_hdp", {"value": 2, "comment": "Alternative option to calculate the smoothing length (h=hdp*dp)"}),
        ("cflnumber", {"value": 0.2, "comment": "Coefficient to multiply dt"}),
    ]

    draw_commands = [
        E("setdrawmode", {"mode": "full"}),
        E("setmkfluid", {"mk": 0}),
        E("drawbox", children=[
            _text_el("boxfill", "solid"),
            E("point", {"x": 0, "y": -1, "z": 0}),
            E("size", {"x": 1, "y": 2, "z": 2}),
        ]),
        E("setmkbound", {"mk": 0}),
        E("drawbox", children=[
            _text_el("boxfill", "bottom | left | right | front | back"),
            E("point", {"x": 0, "y": -1, "z": 0}),
            E("size", {"x": 4, "y": 2, "z": 3}),
        ]),
    ]

    gauges_default = E("default", children=[
        E("savevtkpart", {"value": True, "comment": "Creates VTK files for each PART (default=false)"}),
        E("_computedt", {"value": 0.001, "comment": "Time between measurements. 0:all steps (default=TimeOut)", "units_comment": "s"}),
        E("_computetime", {"start": 0.1, "end": 0.2, "comment": "Start and end of measures. (default=simulation time)", "units_comment": "s"}),
        E("output", {"value": True, "comment": "Creates CSV files of measurements (default=false)"}),
        E("_outputdt", {"value": 0, "comment": "Time between output measurements. 0:all steps (default=TimeOut)", "units_comment": "s"}),
        E("_outputtime", {"start": 0, "end": 10, "comment": "Start and end of output measures. (default=simulation time)", "units_comment": "s"}),
    ])

    swl_gauge_1 = SwlGauge("Swl_x02", point0_xyz=(0.2, 0, -0.05), point2_xyz=(0.2, 0, 2.1))
    swl_gauge_2 = SwlGauge(
        "Swl_z003", point0_xyz=(-0.05, 0, 0.03), point2_xyz=(4.05, 0, 0.03),
        compute_dt_s=0.005, output_dt_s=0.005,
    )

    parameters = [
        ("SavePosDouble", 0, "Saves particle position using double precision (default=0)"),
        ("StepAlgorithm", 1, "Step Algorithm 1:Verlet, 2:Symplectic (default=1)"),
        ("VerletSteps", 40, "Verlet only: Number of steps to apply Euler timestepping (default=40)"),
        ("Kernel", 2, "Interaction Kernel 1:Cubic Spline, 2:Wendland (default=2)"),
        ("ViscoTreatment", 1, "Viscosity formulation 1:Artificial, 2:Laminar+SPS, 3:Laminar (default=1)"),
        ("Visco", 0.02, "Viscosity value. Typically 0.01 for Artificial and 1e-6 m^2/s (water kinematic viscosity) for Laminar"),
        ("ViscoBoundFactor", 1, "Multiply viscosity value with boundary (default=1)"),
        ("DensityDT", 2, "Density Diffusion Term 0:None, 1:Molteni, 2:Fourtakas, 3:Fourtakas(full) (default=0)"),
        ("DensityDTvalue", 0.1, "DDT value (default=0.1)"),
        ("Shifting", 0, "Shifting mode 0:None, 1:Ignore bound, 2:Ignore fixed, 3:Full (default=0)"),
        ("ShiftCoef", -2, "Coefficient for shifting computation (default=-2)"),
        ("ShiftTFS", 0, "Threshold to detect free surface. Typically 1.5 for 2D and 2.75 for 3D (default=0)"),
        ("RigidAlgorithm", 1, "Rigid Algorithm 0:collision-free, 1:SPH, 2:DEM, 3:Chrono (default=1)"),
        ("FtPause", 0.0, "Time to freeze the floatings at simulation start (warmup) (default=0)"),
        ("CoefDtMin", 0.05, "Coefficient to calculate minimum time step dtmin=coefdtmin*h/speedsound (default=0.05)"),
        ("DtIni", 0, "Initial time step. Use 0 to default use (default=h/speedsound)"),
        ("DtMin", 0, "Minimum time step. Use 0 to default use (default=coefdtmin*h/speedsound)"),
        ("DtFixed", 0, "Fixed Dt value. Use 0 to disable (default=disabled)"),
        ("DtFixedFile", "NONE", "Dt values are loaded from file. Use NONE to disable (default=disabled)"),
        ("DtAllParticles", 0, "Velocity of particles used to calculate DT. 1:All, 0:Only fluid/floating (default=0)"),
        ("TimeMax", 2.0, "Time of simulation"),
        ("TimeOut", 0.01, "Time out data"),
        ("PartsOutMax", 1, "%/100 of fluid particles allowed to be excluded from domain (default=1)"),
        ("RhopOutMin", 700, "Minimum rhop valid (default=700)"),
        ("RhopOutMax", 1300, "Maximum rhop valid (default=1300)"),
    ]

    return CaseSpec(
        dp_m=0.01,
        pointref_xyz=(0, 0, 0),
        pointmin_xyz=(-1, 0, -1),
        pointmax_xyz=(4.5, 0, 3.5),
        constants=constants,
        mk_boundcount=240,
        mk_fluidcount=9,
        draw_commands=draw_commands,
        parameters=parameters,
        gauges_default=gauges_default,
        swl_gauges=[swl_gauge_1, swl_gauge_2],
        simdomain_posmax=("default", "default", "default + 50%"),
    )


def _text_el(tag: str, text: str) -> ET.Element:
    el = ET.Element(tag)
    el.text = text
    return el
