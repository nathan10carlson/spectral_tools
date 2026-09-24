"""Export a selected rectangle without resampling its measured spectra."""
import csv
import io
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, PngImagePlugin

MAX_SPECTRAL_ROWS = 5_000_000


def rectangle(cube, bounds):
    values = [bounds[k] for k in ('row_start', 'column_start', 'row_end', 'column_end')]
    r0, c0, r1, c1 = values
    if any(type(v) is not int for v in values) or not (0 <= r0 <= r1 < cube.nr and 0 <= c0 <= c1 < cube.nc):
        raise ValueError('Select an integer rectangle inside the image.')
    count = (r1 - r0 + 1) * (c1 - c0 + 1)
    if count * cube.nb > MAX_SPECTRAL_ROWS:
        raise ValueError('This selection exceeds 5 million spectral samples. Export smaller rectangles.')
    return r0, c0, r1, c1, count


def safe_cell(value):
    if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def csv_member(archive, name):
    return io.TextIOWrapper(archive.open(name, 'w', force_zip64=True), encoding='utf-8', newline='')


def labeled_png(image, title, subtitle, maximum=None):
    # Keep the cropped raster at native resolution; captions occupy separate rows.
    measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    width = max(540, image.width, int(measure.textlength(title))+24, int(measure.textlength(subtitle))+24)
    result = Image.new('RGB', (width, image.height + 104), '#111923')
    result.paste(image, (0, 56))
    draw = ImageDraw.Draw(result)
    draw.text((12, 10), title, fill='#e4e9f3')
    draw.text((12, 30), subtitle, fill='#a5b1c2')
    if maximum is not None:
        y = image.height + 70
        for x in range(160):
            t = x / 159
            draw.line((34+x, y, 34+x, y+10), fill=tuple(round(a+b*t) for a,b in ((12,52),(20,183),(40,123))))
        draw.text((12, y), '0', fill='white')
        draw.text((202, y), f'{maximum:g}  |  gray = unavailable', fill='white')
    else:
        draw.text((12, image.height + 72), 'Native pixel crop; display RGB stretch, not measured spectra.', fill='#a5b1c2')
    output = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text('Description', title + '; ' + subtitle)
    info.add_text('Raster bounds', f'x=0,y=56,width={image.width},height={image.height}')
    result.save(output, format='PNG', pnginfo=info)
    return output.getvalue()


def export_rectangle(cube, rgb, payload):
    r0, c0, r1, c1, count = rectangle(cube, payload['bounds'])
    materials = payload['materials']
    pixels = payload['pixels']
    channel = payload['channel']
    maximum = float(payload['maximum'])
    if not materials or len(materials) > 100 or type(channel) is not int or not 0 <= channel < len(materials):
        raise ValueError('Choose a valid material channel.')
    if not np.isfinite(maximum) or maximum <= 0:
        raise ValueError('Display maximum must be positive and finite.')
    if len(pixels) != count:
        raise ValueError('Export requires one result record for every selected pixel.')
    width, height = c1-c0+1, r1-r0+1
    colors = np.full((height, width, 3), [81,87,99], dtype=np.uint8)
    for i, p in enumerate(pixels):
        r, c = r0 + i//width, c0 + i%width
        if (p.get('row'), p.get('column')) != (r, c):
            raise ValueError('Pixel results do not match the selected rectangle.')
        values = p.get('coefficients')
        if values is not None:
            a = np.asarray(values, dtype=float)
            if a.shape != (len(materials),) or not np.isfinite(a).all() or (a < 0).any():
                raise ValueError('Invalid abundance coefficients.')
            t = min(1., max(0., a[channel]/maximum))
            colors[i//width, i%width] = [round(12+52*t), round(20+183*t), round(40+123*t)]
    output = tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
            with csv_member(archive, 'abundances.csv') as stream:
                writer = csv.writer(stream)
                writer.writerow(['row','column','status','mode','sparsity_used','attempts','used_bands','rmse','relative_error','message'] + [safe_cell(e['name']+' ['+e['spectrum_id']+']') for e in materials])
                for p in pixels:
                    values = p.get('coefficients') or ['']*len(materials)
                    writer.writerow([safe_cell(v) for v in [p['row'],p['column'],p.get('status','unprocessed'),payload['settings'].get('mode','sparse'),p.get('strength'),p.get('attempts'),p.get('used_bands'),p.get('rmse'),p.get('relative_error'),p.get('message',''),*values]])
            with csv_member(archive, 'spectra.csv') as stream:
                writer = csv.writer(stream)
                writer.writerow(['row','column','band_index','wavelength_nm','raw_value','scaled_value','source_valid'])
                for r in range(r0, r1+1):
                    for c in range(c0, c1+1):
                        raw = cube.data[:,r,c].astype(float)
                        valid = np.isfinite(raw) & ~cube.masked
                        nodata = raw == cube.nodata if cube.nodata is not None else np.zeros(cube.nb,dtype=bool)
                        valid &= ~nodata
                        for b, value in enumerate(raw):
                            writer.writerow([r,c,b,float(cube.wl[b]),float(value) if np.isfinite(value) else '',float(value/cube.scale) if np.isfinite(value) and not nodata[b] else '',int(valid[b])])
            bounds_label = f'Rows {r0}-{r1}, columns {c0}-{c1} (zero-based, inclusive)'
            original = Image.open(io.BytesIO(rgb)).convert('RGB').crop((c0,r0,c1+1,r1+1))
            archive.writestr('original.png', labeled_png(original, 'Original image | '+payload.get('palette','false')+' color', bounds_label))
            archive.writestr('abundance.png', labeled_png(Image.fromarray(colors), 'Abundance | '+materials[channel]['name'], bounds_label, maximum))
            metadata = dict(format_version=1, exported_utc=datetime.now(timezone.utc).isoformat(),
                run_started_utc=payload.get('run_started_utc'), source_dimensions=dict(rows=cube.nr,columns=cube.nc,bands=cube.nb), dataset=Path(cube.path).name, dataset_version=payload['version'],
                bounds=payload['bounds'], coordinates='zero-based, inclusive', pixel_count=count,
                native_wavelengths_nm=cube.wl.tolist(), reflectance_scale=cube.scale,
                source_bad_band_indices=np.flatnonzero(cube.masked).tolist(),
                source_nodata=float(cube.nodata) if cube.nodata is not None and np.isfinite(cube.nodata) else None,
                settings=payload['settings'], processing=payload.get('processing',{}), retry=payload.get('retry',{}), materials=materials,
                display=dict(channel_id=materials[channel]['spectrum_id'], maximum=maximum, palette=payload.get('palette','false'),
                    png_raster_bounds=dict(x=0,y=56,width=width,height=height)),
                spectra_note='Native measurements, no interpolation. scaled_value = raw_value / reflectance_scale. Source bad-band values are retained with source_valid=0; no-data scaled values are blank. Analysis exclusions are recorded in settings and are not applied to this source export.',
                results_note='Coefficients are a snapshot of this run. Blank coefficients indicate invalid, failed, or unprocessed pixels.')
            archive.writestr('analysis.json', json.dumps(metadata, indent=2, allow_nan=False))
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise
