"""Native-band rectangular region means and sample variability."""
from pathlib import Path
import numpy as np
from engine import clean

def region_average(cube,bounds):
    r0,c0,r1,c1=[bounds[k] for k in ('row_start','column_start','row_end','column_end')]
    if any(type(v) is not int for v in (r0,c0,r1,c1)) or not (0<=r0<=r1<cube.nr and 0<=c0<=c1<cube.nc):
        raise ValueError('Region bounds must be integer pixels within the image.')
    total=(r1-r0+1)*(c1-c0+1)
    if total<2:raise ValueError('Choose a region containing at least two pixels.')
    means=np.full(cube.nb,np.nan);std=means.copy();counts=np.zeros(cube.nb,dtype=int)
    # Process one band at a time to avoid copying a large sub-cube.
    for b in range(cube.nb):
        if cube.masked[b]:continue
        raw=cube.data[b,r0:r1+1,c0:c1+1].astype(float)
        valid=np.isfinite(raw)
        if cube.nodata is not None:valid &= raw!=cube.nodata
        values=raw[valid]/cube.scale;values=values[np.isfinite(values)]
        counts[b]=len(values)
        if len(values):means[b]=values.mean()
        if len(values)>1:std[b]=values.std(ddof=1)
    if np.isfinite(means).sum()<3:raise ValueError('Region has fewer than three valid spectral bands.')
    nonzero=counts[counts>0]
    return dict(name=f'Region rows {r0}-{r1}, columns {c0}-{c1}',category='Region averages',
        source=f'{Path(cube.path).name} · rows {r0}–{r1}, columns {c0}–{c1} (inclusive, zero-based)',
        description=f'Mean of {total} selected pixels; valid count varies by band ({nonzero.min()}–{nonzero.max()}). Sample standard deviation describes spatial variability, not uncertainty in the mean. Header bad bands and no-data excluded.',
        wavelengths=cube.wl.tolist(),values=clean(means),standard_deviation=clean(std),valid_counts=counts.tolist(),pixel_count=total,bounds=bounds)
