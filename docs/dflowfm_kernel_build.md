# D-Flow FM kernel build (WSL, Intel oneAPI 2024.2)

Status: **WORKING** (2026-09-26). D-Flow FM **1.2.184** (DIMRset 2026.01) + DIMR 2.00, built from
unmodified Deltares source with Intel oneAPI 2024.2. It ran Deltares' `examples/dflowfm/01_dflowfm_sequential`
and the D-Flow FM tutorial06 (Western Scheldt, 10 days) with 0 errors.

## Quick reference

| What | Where |
|---|---|
| Install tree (Deltares `lnx64` layout) | `~/delft3d/dflowfm-2026.01/lnx64/{bin,lib}` (347 MB, self-contained: bundles Intel runtime, Intel MPI, netcdf-fortran, PETSc) |
| Kernel executable | `~/delft3d/dflowfm-2026.01/lnx64/bin/dflowfm` (`--version`: "Deltares, D-Flow FM Version 1.2.184.Unknown … Compiled with Intel ifort … MPI: yes") |
| Kernel library (loaded by DIMR) | `~/delft3d/dflowfm-2026.01/lnx64/lib/libdflowfm.so` |
| DIMR | `~/delft3d/dflowfm-2026.01/lnx64/bin/dimr`, `lib/libdimr.so` |
| Run a plain `.mdu` | `cd <case>; ~/delft3d/dflowfm-2026.01/lnx64/bin/run_dflowfm.sh <model>.mdu` → `DFM_OUTPUT_<model>/` (or the MDU's `OutputDir`) |
| Run via DIMR | `cd <case>; ~/delft3d/dflowfm-2026.01/lnx64/bin/run_dimr.sh -m dimr_config.xml` |
| Build env | `source ~/delft3d/intel-env.sh` (only needed to rebuild; the run scripts set `LD_LIBRARY_PATH` themselves) |
| Python tools | The project's own `.venv` (M3-B, 2026-09-26): hydrolib-core 1.4.0, meshkernel 8.3.0, dfm_tools 0.47.0, pinned in `environment.yml`/`requirements.txt`. Verified against this kernel with no version drift in any already-installed package. (First verified in a separate throwaway venv, `~/delft3d/fm-py-venv`, since retired.) |
| Source + build dirs | `~/delft3d/Delft3D-DIMRset_2026.01/{build_dflowfm,build_dimr}` |

"Version 1.2.184.Unknown / Source: Unknown" is expected. The tarball has no git/svn metadata, so
the build can't stamp a commit. The release identity is DIMRset 2026.01.

**Run from WSL with `/mnt/*` stripped from `PATH`** (same reason as problem 2), e.g.
`PATH=$(echo "$PATH" | tr : '\n' | grep -v '^/mnt/' | paste -sd:) run_dflowfm.sh model.mdu`.

**The run scripts exit 0 even when the kernel refuses the input** (seen three times, see "Runs").
M0/M3 must decide success from the `.dia` (`** ERROR` lines) and the presence of `_map.nc`/`_his.nc`,
never from the exit code.

## Release

- Source: Deltares **Delft3D DIMRset 2026.01** source tarball
  (`Delft3D-all-release-2026.01/Delft3D-DIMRset_2026.01`, downloaded to
  `C:\Users\mprro\Downloads\` on the Windows side). Built **unmodified**: no Deltares source is
  patched.
- Copied into the WSL filesystem (not built from `/mnt/c`):

  ```bash
  mkdir -p ~/delft3d
  rsync -a "/mnt/c/Users/mprro/Downloads/Delft3D-all-release-2026.01/Delft3D-DIMRset_2026.01" ~/delft3d/
  rsync -a "/mnt/c/Users/mprro/Downloads/Tutorial Data/Tutorial_D-Flow_FM/tutorial06" ~/delft3d/tutorials/
  ```

- Machine: WSL2, Ubuntu 24.04.4, 16 cores, 7.7 GB RAM visible to WSL.
- The release's Linux docs are `README.md` ("`./build.sh fm-suite --compiler intel21`") and
  `Linux_setup.md` (Intel oneAPI, apt packages, netcdf-fortran from source, pkg-config files).
  `src/setenv.sh` shows what Deltares' own Linux systems use for `intel24`: Intel 2024.2.0,
  Intel MPI 2021.13.0, netCDF 4.9.2 + netcdf-fortran 4.6.1, PETSc 3.21.3, PROJ 9.2, GDAL 3.6.3.
  We match the compiler, MPI, netcdf-fortran and PETSc versions. C libraries come from Ubuntu
  apt (netCDF-C 4.9.2, PROJ 9.4.0, GDAL 3.8.4).

## Route

- Compiler: **Intel oneAPI 2024.2** (`ifort` + `icx`) + **Intel MPI 2021.13**, from Intel's apt
  repo. 2024.2 is the last oneAPI release that still ships `ifort`.
- Built from source with Intel: **netcdf-fortran 4.6.1** and **PETSc 3.21.3**. Ubuntu's `petsc-dev`
  is built with OpenMPI/gfortran and can't be mixed with Intel MPI.
- Everything else comes from Ubuntu apt.
- Configs: `CONFIGURATION_TYPE=dflowfm` (kernel without the interacter GUI) and
  `CONFIGURATION_TYPE=dimr`, Release, built separately. We did not build the full `fm-suite`.
- We ran the same `cmake` commands as `build.sh`, but used `make -j6` instead of the script's
  unbounded `make -j`, because WSL has only 7.7 GB RAM.
- All cmake/make commands run with `/mnt/*` stripped from `PATH` (see problem 2).

## Commands

### 1. Ubuntu packages (apt)

```bash
sudo apt-get update && sudo apt-get install -y gfortran g++ make ninja-build pkg-config patchelf \
  subversion openmpi-bin libopenmpi-dev libnetcdf-dev libnetcdff-dev netcdf-bin libhdf5-dev \
  hdf5-tools hdf5-helpers petsc-dev libmetis-dev metis libproj-dev libgdal-dev uuid-dev sqlite3 \
  libsqlite3-dev libtiff-dev
```

These were installed for the GNU attempt. The Intel build still uses the C libraries (netCDF-C,
HDF5, PROJ, GDAL, METIS, SQLite, TIFF, BLAS/LAPACK) and `patchelf`/`svnversion`, which
`build.sh` checks for. It does not use apt's OpenMPI, gfortran, `libnetcdff-dev` or `petsc-dev`.

### 2. Intel oneAPI 2024.2 (Intel apt repo)

Package names and versions were checked against
`https://apt.repos.intel.com/oneapi/dists/all/main/binary-amd64/Packages.gz` before installing:
`intel-oneapi-compiler-fortran-2024.2` 2024.2.2-78 ("Fortran Compiler & Fortran Compiler
Classic"), `intel-oneapi-compiler-dpcpp-cpp-2024.2` 2024.2.2-78, `intel-oneapi-mpi-devel-2021.13`
2021.13.1-767.

```bash
wget -O- https://apt.repos.intel.com/intel-gpg-keys/GPG-PUB-KEY-INTEL-SW-PRODUCTS.PUB \
  | gpg --dearmor | sudo tee /usr/share/keyrings/oneapi-archive-keyring.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/oneapi-archive-keyring.gpg] https://apt.repos.intel.com/oneapi all main" \
  | sudo tee /etc/apt/sources.list.d/oneAPI.list
sudo apt-get update
sudo apt-get install -y intel-oneapi-compiler-fortran-2024.2 intel-oneapi-compiler-dpcpp-cpp-2024.2 \
  intel-oneapi-mpi-devel-2021.13 libgtest-dev
```

### 3. cmake >= 3.30 (release requirement; Ubuntu 24.04 apt has 3.28)

The system Python has no `python3-venv`/`ensurepip`, so the venv is created without pip and
populated with the project venv's pip:

```bash
/home/mprohit/main/Hackathon/SIH26-161/.venv/bin/python -m venv --without-pip ~/delft3d/buildtools-venv
/home/mprohit/main/Hackathon/SIH26-161/.venv/bin/python -m pip --python ~/delft3d/buildtools-venv/bin/python \
  install "cmake>=3.30,<4"          # -> cmake 3.31.10
```

It is pinned below 4 because cmake 4 rejects `cmake_minimum_required(VERSION <3.5)`, which old
bundled third-party code may still use.

### 4. Dependency sources

```bash
mkdir -p ~/delft3d/deps-src && cd ~/delft3d/deps-src
curl -sSfL -o netcdf-fortran-4.6.1.tar.gz https://github.com/Unidata/netcdf-fortran/archive/refs/tags/v4.6.1.tar.gz
curl -sSfL -o petsc-3.21.3.tar.gz https://web.cels.anl.gov/projects/petsc/download/release-snapshots/petsc-3.21.3.tar.gz
tar xzf netcdf-fortran-4.6.1.tar.gz && tar xzf petsc-3.21.3.tar.gz
```

### 5. Build environment (`~/delft3d/intel-env.sh`, source before every build or run)

```bash
export PATH=$(echo "$PATH" | tr : '\n' | grep -v '^/mnt/' | paste -sd:)   # no Windows dirs
source /opt/intel/oneapi/setvars.sh > /dev/null 2>&1
export PATH=$HOME/delft3d/buildtools-venv/bin:$PATH
export D3D_LOCAL=$HOME/delft3d/local
export NFDIR=$D3D_LOCAL/netcdf-ifort/4.6.1
export PETSC_DIR=$D3D_LOCAL/petsc-intel/3.21.3
export PKG_CONFIG_PATH=$HOME/delft3d/pkgconfig:$PETSC_DIR/lib/pkgconfig:$NFDIR/lib/pkgconfig:/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig
export LD_LIBRARY_PATH=$NFDIR/lib:$PETSC_DIR/lib:$LD_LIBRARY_PATH
```

Versions: ifort 2021.13.2 (oneAPI 2024.2), icx 2024.2.1, Intel MPI 2021.13 Build 20240701.
The prefix is user-owned (`~/delft3d/local`, not `/usr/local` as in `Linux_setup.md`), so
`make install` needs no sudo. netcdf-fortran installs its own `netcdf-fortran.pc`, and apt
provides `proj.pc`/`sqlite3.pc`, so the hand-written pkgconfig files in `Linux_setup.md` aren't
needed.

### 6. netcdf-fortran 4.6.1 with ifort (flags from `Linux_setup.md`)

```bash
source ~/delft3d/intel-env.sh
cd ~/delft3d/deps-src/netcdf-fortran-4.6.1
export CC=icx CXX=icpx FC=ifort F77=ifort F90=ifort CPP='icx -E -mcmodel=large' CXXCPP='icx -E -mcmodel=large'
export LDFLAGS="-L/usr/lib/x86_64-linux-gnu" CPPFLAGS="-DNDEBUG -DpgiFortran"
export OPTIM="-O3 -mcmodel=large -fPIC"
export CFLAGS="$OPTIM" CXXFLAGS="$OPTIM" FCFLAGS="$OPTIM -diag-disable=10448" FFLAGS="$OPTIM -diag-disable=10448"
./configure --prefix=$NFDIR --enable-large-file-tests --with-pic
make -j6 && make check -j6 && make install        # make check: 61/61 PASS
$NFDIR/bin/nf-config --version --fc                 # netCDF-Fortran 4.6.1 / ifort
```

### 7. PETSc 3.21.3 with Intel MPI

```bash
source ~/delft3d/intel-env.sh
cd ~/delft3d/deps-src/petsc-3.21.3
env PETSC_DIR=$PWD ./configure --prefix=$PETSC_DIR \
  --with-cc=mpiicx --with-cxx=mpiicpx --with-fc=mpiifort \
  --with-debugging=0 --with-shared-libraries=1 \
  COPTFLAGS="-O2 -fPIC" CXXOPTFLAGS="-O2 -fPIC" FOPTFLAGS="-O2 -fPIC -diag-disable=10448" \
  --with-blaslapack-lib="$HOME/delft3d/local/blaslapack/liblapack.so $HOME/delft3d/local/blaslapack/libblas.so" \
  --with-x=0 --with-make-np=4
# Any -L/usr/lib/x86_64-linux-gnu in PETSc's link line makes -lmpi resolve to apt's OpenMPI (problem 4).
# PETSc turns full paths into -L<dir> -l<name>, so BLAS/LAPACK go through a private symlink dir:
#   mkdir -p ~/delft3d/local/blaslapack
#   ln -sf /usr/lib/x86_64-linux-gnu/liblapack.so.3 ~/delft3d/local/blaslapack/liblapack.so
#   ln -sf /usr/lib/x86_64-linux-gnu/libblas.so.3   ~/delft3d/local/blaslapack/libblas.so
make PETSC_DIR=$PWD PETSC_ARCH=arch-linux-c-opt all
make PETSC_DIR=$PWD PETSC_ARCH=arch-linux-c-opt install
```

BLAS/LAPACK are Ubuntu's reference `libblas`/`liblapack`, not MKL, to save the 2–3 GB MKL
download. `--with-make-np=4` keeps the parallel build within the 7.7 GB of RAM.

### 8. dflowfm + dimr

```bash
source ~/delft3d/intel-env.sh
export FC=mpiifort CC=mpiicx CXX=mpiicpx          # Linux_setup.md says mpiicc/mpiicpc; classic icc is gone in 2024.x
cd ~/delft3d/Delft3D-DIMRset_2026.01
for c in dflowfm dimr; do
  rm -rf build_$c && mkdir build_$c && cd build_$c
  cmake ../src/cmake -G "Unix Makefiles" -B . -D CONFIGURATION_TYPE=$c -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_INSTALL_PREFIX=../build_$c/install/
  make -j6 install                                 # dflowfm 3 min 36 s, dimr 8 s; 0 compile errors
  cd ..
done
# merge into one Deltares-style tree (dimr finds libdflowfm.so in ../lib)
D=~/delft3d/dflowfm-2026.01/lnx64; mkdir -p $D
cp -a build_dflowfm/install/. $D/
cp -a --update=none build_dimr/install/. $D/
```

Checks after merging:

```bash
for f in $D/lib/*.so* $D/bin/*; do readelf -d $f 2>/dev/null | grep -q libmpi.so.40 && echo "OpenMPI in $f"; done   # must print nothing
$D/bin/dflowfm --version
```

## Runs

### A. `examples/dflowfm/01_dflowfm_sequential` (release's own example, via DIMR)

```bash
cp -a ~/delft3d/Delft3D-DIMRset_2026.01/examples/dflowfm/01_dflowfm_sequential ~/delft3d/runs/
cd ~/delft3d/runs/01_dflowfm_sequential
~/delft3d/dflowfm-2026.01/lnx64/bin/run_dimr.sh -m dimr_config.xml
```

The model has 222 cells. It simulated 25 h in 1.34 s with 0 errors. The 5 warnings are unused
legacy keywords in Deltares' own `f34.mdu`. Output is `dflowfm/dflowfmoutput/f34_map.nc`
(1.3 MB), `f34_his.nc` and 3 restart files. The examples'
own `run.sh` hard-codes `dimrdir=/p/d-hydro/dimrset/latest` (a Deltares path) and rewrites
`dimr_config.xml` with `sed -i`, so we call `run_dimr.sh` directly on a copy.

### B. Tutorial_D-Flow_FM/tutorial06 (Western Scheldt)

We ran `tutorial06/finished/`, the tutorial's completed model with observation points and a
cross-section, 10 days. The top-level `tutorial06/westernscheldt06.mdu` is the starting state,
with no obs/crs. Its `TStop = 8640000 s` is 100 days, which we estimated at ~75 min and
~20 GB of map output for no extra proof.

This tutorial input dates from 2015 (FM 1.1.148), and the 2026 kernel rejects it three times in
a row. All fixes were made **in the run copy** (`~/delft3d/runs/tutorial06`). The originals are
untouched, and the run copy keeps `*.tutorial_original` backups.

| # | Kernel message | Cause | Fix (run copy only) |
|---|---|---|---|
| T1 | `keyword [numerics] transportmethod is obsolete` (+ `thindykecontraction`, `[output] writebalancefile`) → `Old unsupported keywords used` | 2015 MDU keywords removed from the kernel (`fm_deprecated_keywords.f90`) | Deleted the 3 lines. Physics-neutral here: `TransportMethod=1` is the only method left, thin-dyke contraction needs a `ThindykeFile` (empty), and `Writebalancefile=0` is an output switch that was already off. |
| T2 | `Error occurs when reading the restart file.` (no restart file configured) | Misleading. The real error is `Requested time preceeds current forcing EC-timelevel by 0.500 days … in file: 'Discharge.bc'`: its time axis is `minutes since 2001-01-01 12:00:00` but `RefDate = 20010101`, so the series starts 12 h after t0. The `error` flag from `set_external_forcings_boundaries` (`flow_flowinit.f90:227`) is reported by the restart check at line 252. | Added `-720 1000` (hold the first value back to t0), which is what the 2015 kernel did implicitly |
| T3 | `Error found in EC-module` at t = 129 630 s | `Discharge.bc` ends at 1440 min (t = 36 h), but the run is 10 days: `Datablock end (eof) has been reached (READING BEYOND FINAL TIME)` | Added `14400 2000` (hold the last value past `TStop`) |

```bash
cd ~/delft3d/runs/tutorial06        # copy of tutorial06/finished + the fixes above
~/delft3d/dflowfm-2026.01/lnx64/bin/run_dflowfm.sh westernscheldt06.mdu
```

Result: 8355 cells, 240 h simulated in 3 min 29 s, peak RSS 137 MB, **0 errors**, no forcing
warnings. `DFM_OUTPUT_westernscheldt06/westernscheldt06_map.nc` (805 MB) and
`westernscheldt06_his.nc` (2.4 MB) were written, plus daily restart files. End of `.dia`:

```
** INFO   : Computation started  at: 07:21:37, 26-09-2026
** INFO   : Computation finished at: 07:25:06, 26-09-2026
** INFO   : simulation period      (h)  :           240.0000000000
** INFO   : total time in timeloop (h)  :             0.0579816597
** INFO   : MPI    : no.
** INFO   : OpenMP : unavailable.
** INFO   : crosssection discharges (m3/s) :
** INFO   :     -93571.427
** INFO   :     -59433.357
** INFO   :     -22522.092
** INFO   :       1537.062
** INFO   : crosssection areas (m2) :
** INFO   :     120951.459
** INFO   :      90399.795
** INFO   :      27023.352
** INFO   :       9646.740
```

"OpenMP: unavailable" means this Release config doesn't enable OpenMP threading, so runs are
single-core unless MPI-partitioned.

### C. hydrolib-core → kernel → dfm_tools round trip (step 5 check)

The script is kept outside the repo (session scratchpad). Here is what it does:

1. **hydrolib-core** reads tutorial06's `.ext`, both `.bc` files (10 + 1 forcing blocks), both
   boundary `.pli`, the obs `.xyn` (6 points) and the crs `.pli` (4 sections). **meshkernel**
   (through hydrolib's `NetworkModel`) reads the net: 8915 nodes, 17 269 edges, 8355 faces.
2. hydrolib-core builds a **new** `FMModel` (net, RefDate 20010101, TStop 1 day, DtMax 30 s,
   the ext, obs and crs), writes it to `~/delft3d/runs/tut06_hydrolib/`, and re-reads the MDU.
3. The **kernel runs the hydrolib-written MDU**: 24 h, 0 errors, `_map.nc` 106 MB + `_his.nc`.
4. **dfm_tools** `open_partitioned_dataset` reads the map (73 times × 8355 faces, s1 at the last
   step −1.86 … 3.52 m). xarray reads the his (289 times, stations Obs01–06, 4 cross-sections).

Findings that matter for M3:

| Finding | Consequence |
|---|---|
| hydrolib-core 1.4.0 writes `.ext` as `fileVersion = 3.00`; this kernel accepts major 1 or 2 only (`fm_external_forcings_init.f90:102`) and logs `Unsupported format … v3.00 … Ignoring this file.` Then it runs **with no boundaries** and exit code 0. | M3 must set `ext.general.fileversion = "2.01"` (done in the check; the content has no v3-only keywords), or pin a hydrolib-core that writes v2. |
| hydrolib-core's `FMModel` parser rejects the 2015 tutorial MDU (unknown legacy keywords). | Fine for M3: we generate MDUs, we don't parse old ones. |
| hydrolib-core's net **writer** fails on the 2015 net: meshkernel drops 1 of 8916 nodes on read but `node_z` keeps 8916 values (`shape mismatch (8915,) vs (8916,)`). | The check copied the original net. M3 builds nets with meshkernel from scratch, but re-check the writer on our own nets. |
| hydrolib writes absolute child paths in the MDU when children were loaded from absolute paths. | M3 should write relative paths so cases are relocatable. |

## Problems and fixes

| # | Problem | Fix |
|---|---|---|
| 1 | `python3 -m venv` fails (no `ensurepip`) | `venv --without-pip` + install via project venv's `pip --python` |
| 2 | cmake found **Windows anaconda's** GTest (`/mnt/c/Users/mprro/anaconda3/Library/lib/cmake/GTest`) through the Windows dirs WSL appends to `PATH`. On Linux `src/third_party_open/googletest/CMakeLists.txt` uses `find_package(GTest REQUIRED)`. | `apt install libgtest-dev`, and strip `/mnt/*` from `PATH` for every cmake/make. GTest was the only `/mnt/` hit in `CMakeCache.txt`. |
| 3 | netcdf-fortran `make`: `module_tests.F90(35): error #7013: This module file was not generated by any release of this compiler [NETCDF4_F03]`. An extra `-I/usr/include` made ifort read **gfortran's** `.mod` files from Ubuntu's `libnetcdff-dev` in `/usr/include`. | Drop `-I/usr/include` from `CPPFLAGS`. Also `sudo apt-get remove -y libnetcdff-dev` (no installed reverse deps) so the dflowfm build can't pick them up either. |
| 4 | After the first successful dflowfm build, `ldd libdflowfm.so` showed **both** Intel MPI (`libmpi.so.12`) and OpenMPI (`libmpi.so.40`). `readelf -d` traced it to our `libpetsc.so.3.21`: `--with-blaslapack-lib="-L/usr/lib/x86_64-linux-gnu -llapack -lblas"` put Ubuntu's lib dir ahead of Intel MPI's, so PETSc's `-lmpi` resolved to apt's OpenMPI (left over from the GNU attempt). PETSc was compiled against Intel's `mpi.h` but linked to OpenMPI, an ABI mismatch. | Passing full `.so` paths did **not** work, because PETSc rewrites them to `-L<dir> -l<name>`. What worked was a private symlink dir for BLAS/LAPACK (step 7), so `/usr/lib/x86_64-linux-gnu` never appears as `-L`. Then rebuild PETSc and relink dflowfm. Check: `readelf -d $PETSC_DIR/lib/libpetsc.so.3.21 \| grep NEEDED.*mpi` must list only `libmpi.so.12`/`libmpifort.so.12`. |

## Tried and failed: GNU toolchain (gfortran 13.3 + OpenMPI) — Intel extensions

We tried first because the release ships `src/cmake/compiler_options/gnu.cmake` and Ubuntu's
`libnetcdff-dev` is gfortran-built. Deltares does not document or test this route. It was
abandoned on 2026-09-26: the source relies on Intel Fortran extensions that gfortran rejects.
Two fixes were tried and then **reverted**. The source tree was checked byte-identical to the
Windows copy afterwards, so nothing we use contains patched Deltares source. The failed build
tree is kept at `~/delft3d/Delft3D-DIMRset_2026.01/build_dflowfm_gnu_failed/` for reference only.

Configure (`FC=mpif90 CC=mpicc CXX=mpicxx`, `-D CONFIGURATION_TYPE=dflowfm`) succeeded. `make -k -j6`
got about 45% of the way. Every target downstream of `flow1d_core` was skipped, including all
of `dflowfm_kernel`, so the counts below are a floor:

| Count | gfortran error | Where | Nature |
|---|---|---|---|
| 1 | `gfortran: fatal error: no input files` | `f90tw-main/CMakeLists.txt:9`: `set(CMAKE_Fortran_FLAGS ${CMAKE_Fortran_FLAGS} "-ffree-line-length-none")` makes a cmake list; `;` splits the command | cmake bug in a GNU-only branch (tried `string(APPEND ...)`, reverted) |
| 2 | Different CHARACTER lengths in array constructor | `deltares_common/unit_utils.f90:76-77` | Intel extension (tried a `character(len=IdLen) ::` type-spec, reverted) |
| 13 | Dummy of `BIND(C)` procedure not C-interoperable (`t_ug_charinfo`, `t_ug_meta`) | `io_netcdf_api.F90` | Intel extension |
| 1 | `C_F_POINTER` SHAPE size ≠ rank of FPTR | `io_netcdf_api.F90:1479` | Intel extension |
| 7 | `OPEN(... FORM='binary')` | `flow1d_implicit`: FLMINMAX, FLWRHI, GAREADHEAD, MOZOPENHS | Intel extension |
| 1 | Syntax error in argument list | `flow1d_implicit/SOFLOW_wrap.f90:297` | not diagnosed |
| 1 | Character dummy with `VALUE` must have constant length | `flow1d_core/structures.f90:468` | Intel extension |
| 3 | Mixed CHARACTER lengths / undeclared `date` | `test_deltares_common` (unit tests) | Intel extension |

`dflowfm_kernel/CMakeLists.txt:130` links `flow1d_implicit`, so the failing libraries can't be
skipped.

## Backup option (not built): Delft3D 4 `flow2d3d` from the same release

This release also contains the classic Delft3D 4 FLOW kernel: `src/engines_gpl/flow2d3d`, `src/engines_gpl/d_hydro`,
cmake config `flow2d3d` (or the `d3d4-suite` bundle), and a test case at `examples/delft3d4/01_standard`
(`f34.mdf` + `config_d_hydro.xml`). Rough estimate from what this build showed:

- **Extra packages:** none expected. `flow2d3d_configuration.cmake` + `d_hydro_configuration.cmake` pull in
  deltares_common, ec_module, NEFIS, delftio, esmfsm, io_netcdf, morphology, kdtree, triangle, shapelib,
  fortrangis, PROJ and dwaq_base. All of these either build from the tarball or are already installed
  (netCDF, PROJ). No PETSc dependency seen in its config.
- **Build time:** flow2d3d has ~760 Fortran files vs ~1490 in dflowfm, which took 3.6 min at `-j6`. So
  expect roughly 5 min of compile, plus configure. With the example run and a doc update, **under an hour**
  if it builds as cleanly as dflowfm (it's also Deltares-built on Linux with Intel).
- **Command:** as in step 8, with `CONFIGURATION_TYPE=flow2d3d` (kernel + `d_hydro`); run with the
  installed `run_dhydro.sh`/`d_hydro config_d_hydro.xml`. Not verified.
- **Caveat:** this is the DIMRset 2026.01 FLOW kernel, not the 4.07.02 build behind the Windows GUIs. File
  formats (`.mdf`, `.grd`, `.dep`, ...) are the same family, but mixing GUI-written inputs with this kernel
  would need its own tutorial check.

## Proposed WSL memory change (NOT applied)

Current: no `C:\Users\mprro\.wslconfig`, so WSL2 uses its default of 50% of Windows RAM. The VM sees
7.6 GB (`free -m`: 7578 MB total), 16 processors, and WSL 2.6.3.0.

Proposal, file `C:\Users\mprro\.wslconfig`:

```ini
[wsl2]
memory=12GB      # of 16 GB physical; leaves ~4 GB for Windows + desktop
swap=8GB         # spill-over instead of OOM-kill on a big run
processors=16    # unchanged
```

To apply: write the file on the Windows side, then run `wsl --shutdown` from PowerShell and reopen WSL.
`wsl --shutdown` stops **every** WSL process, including any running solver job and this Claude session.
