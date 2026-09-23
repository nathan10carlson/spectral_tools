"""ENVI header parsing and cube access for HELMET."""
import os
import re
import numpy as np

ENV_DTYPE = {
    "1": "u1", "2": "i2", "3": "i4", "4": "f4",
    "5": "f8", "9": "c8", "12": "u2", "13": "u4", "14": "u8",
}


def _envi_dtype(datatype, byteorder):
    code = ENV_DTYPE[str(int(datatype))]
    bo = "<" if int(byteorder) == 0 else ">"
    return np.dtype(bo + code)


def _parse_floats(token):
    """Parse a number list that may be brace/comma separated and multi-line."""
    token = token.strip().strip("{}").strip()
    if not token:
        return None
    parts = [p.strip() for p in re.split(r"[,\s]+", token) if p.strip()]
    out = []
    for p in parts:
        if p.lower().startswith("file"):  # '{file list}' -> not literal values
            return None
        try:
            out.append(float(p))
        except ValueError:
            return None
    return out if out else None


def parse_envi_header(path):
    """Parse an ENVI .hdr sidecar -> dict (numpy dtype, layout, dims, wl...)."""
    if not os.path.exists(path) or not os.access(path, os.R_OK):
        return None
    with open(path, "r", errors="replace") as fh:
        raw = fh.read()
    raw = "\n".join(line.split(";")[0] for line in raw.splitlines())
    fields = {}
    for key, val in re.findall(r"([A-Za-z][A-Za-z0-9 _-]*)\s*=\s*(\{[^}]*\}|[^\n]*)", raw):
        fields[key.strip().lower()] = val.strip()
    hdr = {}
    try:
        hdr["dtype"] = _envi_dtype(
            fields.get("data type", fields.get("datatype", "2")),
            fields.get("byte order", fields.get("byteorder", "0")),
        )
    except (KeyError, ValueError):
        hdr["dtype"] = np.dtype("<u2")
    hdr["interleave"] = fields.get("interleave", "bsq").strip().lower()
    if hdr["interleave"] not in ("bsq", "bil", "bip"):
        hdr["interleave"] = "bsq"
    try:
        hdr["bands"] = int(fields.get("bands", "0"))
    except ValueError:
        hdr["bands"] = 0
    try:
        hdr["lines"] = int(fields.get("lines", "0"))
    except ValueError:
        hdr["lines"] = 0
    try:
        hdr["samples"] = int(fields.get("samples", "0"))
    except ValueError:
        hdr["samples"] = 0
    # wavelength list (per-band center wavelengths, in `wavelength unit`)
    wl = _parse_floats(fields.get("wavelength", ""))
    unit = fields.get("wavelength unit", fields.get("wavelength units", "")).strip().lower()
    if wl is not None:
        # Values are often supplied in micrometres (e.g. 0.38); convert to nm.
        if unit not in ("nm", "nanometer", "nanometers") and max(wl) < 50.0:
            wl = [w * 1000.0 for w in wl]
            unit = "nm (auto from um)"
        hdr["wavelength"] = wl
    hdr["wavelength_unit"] = unit if unit else "nm"
    # scale factor -> DN / scale = reflectance (some QUAC headers use this exact key)
    scale = None
    for sk in ("reflectance scale factor", "scale factor", "scale"):
        v = fields.get(sk)
        if v is not None and v.strip():
            try:
                scale = float(v)
                break
            except ValueError:
                continue
    hdr["scale"] = scale
    hdr["nodata"] = float(fields["data ignore value"]) if "data ignore value" in fields else None
    hdr["offset"] = int(fields.get("header offset", "0"))
    # bad band list (bbl): 1 = good, 0 = bad band to mask.
    bbl = _parse_floats(fields.get("bbl", ""))
    hdr["bbl"] = [int(b) for b in bbl] if bbl is not None else None
    hdr["byteorder"] = fields.get("byte order", fields.get("byteorder", "0"))
    return hdr


def detect_envi_header(img_path):
    """Return path to the .hdr sidecar of `img_path`, or None."""
    if img_path.lower().endswith(".img"):
        hdr = img_path[:-4] + ".hdr"
        if os.path.exists(hdr):
            return hdr
    return None


def nearest_bands(wl, targets):
    """Band indices whose wavelength is closest to each target (nm)."""
    wl = np.asarray(wl, dtype=float)
    return [int(np.argmin(np.abs(wl - t))) for t in targets]


# --------------------------------------------------------------------------- #
HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 8000

# Default target file in this workspace.
PATH_DEFAULT = 'sample_path.img'
# --------------------------------------------------------------------------- #
class Cube:
    """Load and index a raw binary hyperspectral cube."""

    def __init__(self, path, nb, nr, nc, dtype, layout, scale, wl0, wl1,
                 wavelengths=None, bbl=None, wavelength_unit="nm", nodata=None, offset=0):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        total = nb * nr * nc
        raw = np.fromfile(path, dtype=dtype, count=total, offset=offset)
        self.nodata = nodata
        if np.iscomplexobj(raw):
            raise ValueError("Complex-valued cubes are not supported")
        if raw.size != total:
            raise ValueError(
                f"File too small for shape ({nb},{nr}{',',nc}){dtype}: "
                f"got {raw.size} pixels, need {total}"
            )
        self.path = path
        self.nb, self.nr, self.nc = int(nb), int(nr), int(nc)
        self.dtype = np.dtype(dtype)
        self.layout = layout
        self.scale = float(scale)
        if not np.isfinite(self.scale) or self.scale <= 0:
            raise ValueError("Scale must be positive and finite")
        self.wavelength_unit = wavelength_unit

        # Wavelength per band: exact list from header if available, else linear grid.
        if wavelengths is not None and len(wavelengths) == self.nb:
            self.wl = np.asarray(wavelengths, dtype=float)
        else:
            self.wl = np.linspace(float(wl0), float(wl1), self.nb)

        # Reshape according to layout, then transpose to (bands, rows, cols).
        if layout == "bsq":
            cube = raw.reshape(self.nb, self.nr, self.nc)
        elif layout == "bip":
            cube = raw.reshape(self.nr, self.nc, self.nb).transpose(2, 0, 1)
        elif layout == "bil":
            cube = raw.reshape(self.nr, self.nb, self.nc).transpose(1, 0, 2)
        else:
            raise ValueError(f"unknown layout: {layout}")
        self.data = cube  # uint16

        # Masked bands: all-zero (dead water-vapor bands) and/or bbl == 0 (bad).
        band_max = self.data.max(axis=(1, 2))
        self.masked = band_max == 0
        if bbl is not None and len(bbl) == self.nb:
            self.masked = self.masked | (np.asarray(bbl) == 0)

    # -- pixel / band access -------------------------------------------------
    def pixel_spectrum(self, r, c, reflectance=True):
        """Return (wl, values) for pixel (r, c)."""
        spec = self.data[:, int(r), int(c)].astype(np.float64)
        if reflectance:
            spec = spec / self.scale
        return spec

    def band_array(self, b):
        return self.data[int(b)]

    def stretch(self, band, lo=2.0, hi=98.0):
        """Percentile-stretch a single band to 0-255 (uint8)."""
        arr = self.data[band].astype(np.float64)
        if arr.max() == 0:
            return np.zeros((self.nr, self.nc), dtype=np.uint8)
        lo_v = np.percentile(arr, lo)
        hi_v = np.percentile(arr, hi)
        arr = (arr - lo_v) / (hi_v - lo_v + 1e-9)
        arr = np.clip(arr, 0, 1) * 255.0
        return arr.astype(np.uint8)

    def rgb_image(self, bands):
        """Build an (nr,nc,3) uint8 RGB image, stretched per-channel."""
        chans = [self.stretch(bands[k]) for k in range(3)]
        return np.stack(chans, axis=-1)

    def meta(self, rgb, true_color):
        return {
            "path": self.path,
            "shape": [self.nb, self.nr, self.nc],
            "dtype": str(self.dtype),
            "layout": self.layout,
            "scale": self.scale,
            "wavelength_unit": self.wavelength_unit,
            "wavelength_grid": [round(float(self.wl[0])), round(float(self.wl[-1]))],
            "n_masked_bands": int(self.masked.sum()),
            "rgb_false": {"bands": list(rgb), "wl_nm": [round(float(self.wl[b])) for b in rgb]},
            "rgb_true": {"bands": list(true_color), "wl_nm": [round(float(self.wl[b])) for b in true_color]},
            "masked_band_ranges": _masked_ranges(self.masked),
        }


def _masked_ranges(mask):
    ranges = []
    idxs = np.where(mask)[0]
    if len(idxs) == 0:
        return ranges
    s = e = idxs[0]
    for v in idxs[1:]:
        if v == e + 1:
            e = v
        else:
            ranges.append([int(s), int(e)])
            s = e = v
    ranges.append([int(s), int(e)])
    return ranges


