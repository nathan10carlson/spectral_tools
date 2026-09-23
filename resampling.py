"""Editable HELMET resampling settings and gap-safe interpolation.

Edit TARGET_BANDS_NM, EXCLUDED_RANGES_NM, or INTERPOLATION_METHOD below.
Restart HELMET after changing this file. Saved presets retain their own snapshot.
Original measurements are never modified. All wavelengths are nanometers.
"""
import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator

# Legacy HELMET band centers, including explicitly excluded detector bands.
TARGET_BANDS_NM = [445.5, 461.5, 477.5, 493.5, 509.5, 525.5, 541.5, 557.5, 573.5, 589.5, 605.5, 621.5, 637.5, 653.5, 669.5, 685.5, 701.5, 717.5, 733.5, 749.5, 765.5, 781.5, 797.5, 813.5, 829.5, 845.5, 861.5, 877.5, 893.5, 909.5, 925.5, 941.5, 957.5, 973.5, 989.5, 1005.5, 1021.5, 1037.5, 1053.5, 1069.5, 1085.5, 1101.5, 1117.5, 1133.5, 1149.5, 1165.5, 1181.5, 1197.5, 1213.5, 1229.5, 1245.5, 1261.5, 1277.5, 1293.5, 1309.5, 1325.5, 1469.5, 1485.5, 1501.5, 1517.5, 1533.5, 1549.5, 1565.5, 1581.5, 1597.5, 1613.5, 1629.5, 1645.5, 1661.5, 1677.5, 1693.5, 1709.5, 1725.5, 1741.5, 1757.5, 1773.5, 1789.5, 1981.5, 1997.5, 2013.5]

# Closed intervals. None means no upper bound.
EXCLUDED_RANGES_NM = [(922.5, 989.0), (1085.5, 1197.5), (1334.0, 1500.0), (1750.0, None)]
INTERPOLATION_METHOD = "cubic_spline"  # "cubic_spline", "pchip", or "linear"
MAX_GAP_FACTOR = 3.0  # Split intervals when spacing exceeds this × median spacing.


def configuration():
    return dict(target_grid=list(TARGET_BANDS_NM), bad_ranges=[list(x) for x in EXCLUDED_RANGES_NM],
                interpolation=INTERPOLATION_METHOD, max_gap_factor=MAX_GAP_FACTOR,
                preset="native", resample=True, exclusions="", wavelength_min=None, wavelength_max=None)


def excluded(wavelengths, ranges):
    mask = np.zeros(len(wavelengths), dtype=bool)
    for low, high in ranges:
        mask |= (wavelengths >= low) & (wavelengths <= (np.inf if high is None else high))
    return mask


def resample_spectrum(wavelengths, values, target_bands=None, method=None,
                      excluded_ranges=None, max_gap_factor=MAX_GAP_FACTOR):
    """Return (target centers, values). Invalid output bands contain NaN.

    1. Validate increasing source/target centers.
    2. Split at missing values, excluded intervals, and large sampling gaps.
    3. Fit one interpolator per continuous valid segment.
    4. Evaluate only inside each segment. Never extrapolate or bridge gaps.

    CubicSpline uses natural boundary conditions. Two-point segments use linear
    interpolation; single samples only populate an exactly matching target band.
    No clipping or normalization: reflectance magnitude is preserved, including
    possible spline overshoot. PCHIP can be selected to reduce that overshoot.
    """
    w = np.asarray(wavelengths, float)
    v = np.asarray([np.nan if x is None else x for x in values], float)
    t = np.asarray(TARGET_BANDS_NM if target_bands is None else target_bands, float)
    method = INTERPOLATION_METHOD if method is None else method
    ranges = EXCLUDED_RANGES_NM if excluded_ranges is None else excluded_ranges
    if method not in ("cubic_spline", "pchip", "linear"):
        raise ValueError("Unknown interpolation method.")
    for centers in (w, t):
        if centers.ndim != 1 or len(centers) < 2 or not np.isfinite(centers).all() or np.any(np.diff(centers) <= 0):
            raise ValueError("Band centers must be finite and strictly increasing.")
    if len(w) != len(v): raise ValueError("Wavelength and value counts differ.")
    if not np.isfinite(max_gap_factor) or max_gap_factor <= 0: raise ValueError("Gap factor must be positive.")
    valid = np.isfinite(v) & ~excluded(w, ranges)
    spacing = np.median(np.diff(w))
    segments = []; segment = []
    for i in range(len(w)):
        blocked = False
        if segment:
            previous = w[segment[-1]]
            blocked = w[i]-previous > spacing*max_gap_factor or any(previous <= (np.inf if high is None else high) and w[i] >= low for low,high in ranges)
        if not valid[i] or blocked:
            if segment: segments.append(segment)
            segment = []
        if valid[i]: segment.append(i)
    if segment: segments.append(segment)
    out = np.full(len(t), np.nan)
    for indices in segments:
        x, y = w[indices], v[indices]
        inside = (t >= x[0]) & (t <= x[-1])
        if len(indices) == 1:
            out[np.isclose(t, x[0], rtol=0, atol=1e-6)] = y[0]
        elif method == "linear" or len(indices) == 2:
            out[inside] = np.interp(t[inside], x, y)
        elif method == "pchip":
            out[inside] = PchipInterpolator(x, y, extrapolate=False)(t[inside])
        else:
            out[inside] = CubicSpline(x, y, bc_type="natural", extrapolate=False)(t[inside])
    out[excluded(t, ranges)] = np.nan
    return t, out
