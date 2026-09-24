# Azmi — Updated data-fusion (DFM) dam-breach equations

Source: Azmi M., "An update on Data-Fusion-based Dam Breach Empirical Equations Based on a Worldwide Historical Dam Failure Database". Research Square preprint, posted 2025-10-12, doi:10.21203/rs.3.rs-7289241/v1. Published version: *Natural Hazards*, 2026-06-11, doi:10.1007/s11069-026-08239-x.

> All numbers here come from the **preprint**; lines marked "our rule" or "SIH26" are ours.
> Check the published version before treating any coefficient as final.

## What the paper does

- Starts from the Bernard-Garcia & Mahdi (2020) worldwide database (3,861 failures) and keeps man-made earthfill/rockfill embankment dams.
- Three subsets, one per output: B_ave 130 cases, T_f 65 cases, Q_p 54 cases (only cases with W_ave recorded).
- Gap-filling: missing h_d → h_d = h_b; missing erodibility → medium (M); reported range → midpoint.
- Picks three base equations per output using dendrogram clustering, factor analysis (scree test, Kaiser eigenvalue > 1) and stepwise regression with a collinearity check.
- Fuses them with a no-intercept linear model Y = a·X1 + b·X2 + c·X3, fitted by Levenberg–Marquardt (relative error threshold 1e-2) over 100,000 bootstrap iterations, each with a random 80/20 train/test split. Final coefficient = median over iterations; spread = median ± MAD.
- Compares the updated DFM with the base equations and with DFM 2024 (Azmi & Thomson 2024) using R², NSE, RMSE, MPE (PE% = 100·(X_m − X_o)/X_o), t/F-tests, K-S test, Q-Q and boxplots.
- Recommends two methods per output, chosen so each covers the other's weak criteria.

## Symbols and site-config mapping

| Symbol | Meaning | Unit | `sites/<id>.yaml` → `breach_inputs.*` |
|---|---|---|---|
| Q_p | breach peak outflow | m³/s | output |
| B_ave | final breach average width (mean of top and bottom widths) | m | output |
| T_f | failure time: onset to full breach formation | h | output |
| V_w | water volume above breach invert | m³ | `water_volume_above_invert` |
| h_w | water height above breach invert | m | `water_height_above_invert` |
| h_b | breach height | m | `breach_height` |
| h_d | dam height | m | `dam_height` |
| W_ave | average embankment width | m | `average_embankment_width` |
| — | dam type: HD homogeneous, CD core wall, FD concrete-faced, ZD zoned-fill | enum | `dam_type` |
| — | failure mode: O overtopping, P piping | enum | `failure_mode` |
| — | erodibility: H / M / L | enum | `erodibility` |

## Updated DFM equations (Table 5, median of 100,000 simulations)

Each code is the output of a base equation (listed at the end), in the same unit as the result.

```
Q_p   [m³/s] =  0.3048·F16 + 0.4804·XZ9 + 0.1674·Z20
B_ave [m]    = -0.8220·F95 + 1.0021·F8  + 1.1031·XZ9
T_f   [h]    = -1.0648·F95 + 1.5875·F8  + 0.6189·MCLM
```

Coefficient spread, median ± MAD shown as [low, high]:

| Output | a | b | c |
|---|---|---|---|
| Q_p | F16: 0.3048 [−0.22, 0.82] | XZ9: 0.4804 [0.17, 0.77] | Z20: 0.1674 [−0.42, 0.74] |
| B_ave | F95: −0.8220 [−1.10, −0.54] | F8: 1.0020 [0.68, 1.32] | XZ9: 1.1031 [0.95, 1.26] |
| T_f | F95: −1.0648 [−2.10, −0.03] | F8: 1.5875 [0.58, 2.59] | MCLM: 0.6189 [0.39, 0.84] |

Implementation notes:

- Pair each coefficient with its equation as in Table 5. Table 4 lists the Q_p equations in a different order (F16, Z20, XZ9).
- Because of the negative coefficients, B_ave or T_f can come out ≤ 0 for unusual inputs. Raise or flag this; don't clip it silently. (This is our rule, not the paper's.)
- All base T_f equations must return **hours** before fusing. The paper converts F8's T_f from seconds to hours.
- The ranges are wide, and two Q_p ranges straddle zero. Treat the fused value as a point estimate with real spread, not a tight fit.

## Recommended method pair per output

| Output | Primary | Complement | Why this complement (paper's reasoning) |
|---|---|---|---|
| Q_p | Updated DFM | DFM 2024 | Z20 ranked 2nd but behaves like the updated DFM; DFM 2024 has the lowest median MPE (−9.8%) and a narrower MPE range |
| B_ave | Updated DFM | XZ9 | DFM 2024 ranked 2nd but behaves similarly; XZ9 has lower MAD and a smaller upper tail |
| T_f | Updated DFM | F8 | no clear winner; updated DFM is the only one with positive NSE (0.17); F8 has median MPE −7.3%, low RMSE, upper range < 30% |

The paper says the pair gives "the most comprehensive and reliable range" but doesn't say how to combine the two values. **SIH26 interpretation:** compute both and use them as the low/high bounds of that output's scenario range.

## Performance — Table 7 (full comparison)

RMSE units: Q_p m³/s, B_ave m, T_f h. MPE columns are in %.

| Output | Method | R² | NSE | RMSE | MPE median | MPE MAD | MPE range |
|---|---|---|---|---|---|---|---|
| Q_p | F16 | 0.82 | 0.78 | 6246 | −10.1 | 31.9 | (−42.0, 21.8) |
| Q_p | XZ9 | 0.81 | 0.81 | 5844 | −13.2 | 36.1 | (−49.3, 22.9) |
| Q_p | Z20 | 0.85 | 0.85 | 5214 | −26.2 | 34.0 | (−60.2, 7.8) |
| Q_p | DFM 2024 | 0.83 | 0.79 | 6175 | −9.8 | 36.1 | (−45.9, 26.2) |
| Q_p | **Updated DFM** | 0.88 | 0.88 | 4691 | −19.9 | 32.2 | (−52.1, 12.3) |
| B_ave | F95 | 0.60 | 0.58 | 36.4 | −5.2 | 23.2 | (−28.4, 17.9) |
| B_ave | F8 | 0.59 | 0.57 | 36.6 | −1.8 | 29.8 | (−31.6, 28.0) |
| B_ave | XZ9 | 0.71 | 0.67 | 32.3 | −17.0 | 23.6 | (−40.6, 6.6) |
| B_ave | DFM 2024 | 0.70 | 0.70 | 30.8 | 23.0 | 35.0 | (−12.0, 58.0) |
| B_ave | **Updated DFM** | 0.72 | 0.72 | 29.8 | 10.8 | 30.6 | (−19.7, 41.4) |
| T_f | F95 | 0.27 | 0.01 | 1.15 | −11.3 | 36.6 | (−48.0, 25.3) |
| T_f | F8 | 0.25 | 0.02 | 1.14 | −7.3 | 35.3 | (−42.6, 28.0) |
| T_f | MCLM | 0.15 | −0.02 | 1.17 | 3.4 | 59.4 | (−56.0, 62.9) |
| T_f | DFM 2024 | 0.29 | −0.26 | 1.45 | 47.9 | 60.9 | (−13.0, 99.9) |
| T_f | **Updated DFM** | 0.24 | 0.17 | 1.05 | 20.8 | 45.7 | (−24.8, 66.6) |

Updated DFM test stage only (Table 6), median [median ± MAD]:

| Output | Pearson | Spearman | NSE | MPE % |
|---|---|---|---|---|
| Q_p | 0.92 [0.87, 0.97] | 0.87 [0.81, 0.92] | 0.45 [0.18, 0.81] | −16.42 [−53.54, 20.70] |
| B_ave | 0.85 [0.81, 0.87] | 0.81 [0.78, 0.85] | 0.66 [0.60, 0.71] | −10.54 [−18.52, −2.56] |
| T_f | 0.35 [0.22, 0.47] | 0.52 [0.42, 0.61] | −0.16 [−0.41, 0.09] | −14.96 [−34.20, 4.28] |

K-S test at 5%: every model passes except DFM 2024 for T_f (statistic 0.246 > critical 0.238).

## Limitations

- **Embankment dams only** (earthfill/rockfill). The paper says the equations are not recommended for **concrete dams**, or for embankment dams with extensive safety elements (wave walls, additional rock-mesh protection).
- **Failure time is unreliable.** Best R² is 0.29, all but the updated DFM have NSE ≤ 0.02, and the updated DFM's test-stage median NSE is −0.16. The author blames poor observed data.
- The updated DFM underestimates Q_p on the median (−19.9% in Table 7, −16.42% in Table 6). For warnings, use the upper value of the pair.
- The fit uses man-made dams only. A natural moraine dam (South Lhonak) is outside the calibration population, so label those results as extrapolation.
- Z20 is given only for HD and CD dams, and the preprint doesn't say how FD/ZD cases were handled. Settle this from Zhong et al. (2020) before running an FD dam (Teesta III is FD in `sites/teesta.yaml`, still a placeholder).
- The gap-filling assumptions (h_d = h_b, default erodibility M) are built into the fit.
- The Xu & Zhang (2009) T_f equation was excluded because it defines T_f differently (the whole erosion period).

## Inconsistencies in the preprint

- The text says 104 cases were selected, but the B_ave subset has 130.
- The B_ave coefficient b is 1.0020 in the coefficient column and 1.0021 in the equation column (Table 5).
- The footnotes don't match: Table 1 gives CD = core wall, FD = concrete-faced, but Table 3 labels concrete-faced as "(CD)". This is one reason not to copy base equations from this PDF.
- MCLM and Hooshyaripor et al. (2014) are used but are missing from the reference list.

## Base equations — IMPLEMENT FROM ORIGINAL PAPER

Do **not** transcribe these from the Azmi PDF. Implement each from its original source, cite the equation number in the docstring, and unit-test it against a worked example from that source. The input lists below come from the forms reproduced in the PDF, so confirm them against the originals.

| Code | Used for | Original source | Inputs (confirm) |
|---|---|---|---|
| F16 | Q_p | Froehlich (2016b), Predicting peak discharge from gradually breached embankment dam, J Hydrol Eng 21(11), doi:10.1061/(asce)he.1943-5584.0001424 | V_w, h_w, h_b, W_ave, failure mode |
| XZ9 | Q_p, B_ave | Xu & Zhang (2009), Breaching parameters for earth and rockfill dams, J Geotech Geoenviron Eng 135(12):1957–1970, doi:10.1061/(asce)gt.1943-5606.0000162 | V_w, h_w, h_b, h_d, dam type, failure mode, erodibility |
| Z20 | Q_p | Zhong et al. (2020), New empirical model for breaching of earth-rock dams, Nat Hazards Rev 21(2), doi:10.1061/(asce)nh.1527-6996.0000374 | V_w, h_w, h_b, h_d, dam type |
| F95 | B_ave, T_f | Froehlich (1995), Embankment dam breach parameters revisited, Water Resources Engineering (ASCE) | V_w, h_b, failure mode (B_ave only) |
| F8 | B_ave, T_f | Froehlich (2008), Embankment dam breach parameters and their uncertainties, J Hydraul Eng | V_w, h_b, failure mode (B_ave only) |
| MCLM | T_f | MacDonald & Langridge-Monopolis (1984); not in this paper's reference list, so locate the original | V_w, h_w |
| DFM 2024 | Q_p complement | Azmi & Thomson (2024), Dam breach parameters: from data-driven-based estimates to 2-dimensional modeling, Nat Hazards 120:4423–4461 | fuses F16, H14, XZ9 |
| H14 | only inside DFM 2024 | Hooshyaripor et al. (2014); not in this paper's reference list, so locate the original | per original |

## Guidance for Claude Code

- Write one module per base equation, plus `dfm.py` holding only the Table 5 coefficients (and the DFM 2024 coefficients taken from Azmi & Thomson 2024).
- Return both values of the recommended pair for every output, plus which equations and branches were used.
- Refuse `kind: concrete_dam`, and warn on `kind: moraine_dammed_lake` (out of calibration range).
- Carry `status` through: if any input is a placeholder, mark the output as a placeholder.
