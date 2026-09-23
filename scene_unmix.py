"""Bounded scene batches using the same alignment and solver as pixel fitting."""
import numpy as np
from engine import aligned_inputs, prepare, apply_mask, vector, clean, fit


def unmix_batch(cube, candidates, settings, start, count, retry=True, ceiling=.1):
    total = cube.nr * cube.nc
    if type(start) is not int or type(count) is not int or not 0 <= start < total or not 1 <= count <= 128:
        raise ValueError('Choose a valid pixel offset and batch size (1–128).')
    if settings.get('mode', 'sparse') not in ('sparse', 'fractions'):
        raise ValueError('Unknown fitting mode.')
    strength = float(settings.get('strength', .001))
    if not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Sparsity strength must be between 0 and 1.')
    if retry and settings.get('mode', 'sparse') == 'sparse' and (not np.isfinite(ceiling) or not strength <= ceiling <= 1):
        raise ValueError('Retry ceiling must be between initial sparsity and 1.')
    # Align library columns once per batch, preserving the exact pixel-fit policy.
    template = dict(wavelengths=cube.wl.tolist(), values=clean(np.where(cube.masked, np.nan, 1.)))
    w, _, matrix, _ = aligned_inputs(template, candidates, settings)
    pixel_settings = dict(settings)
    if settings.get('fit_grid') == 'target':
        pixel_settings.update(target_grid=cube.wl.tolist(), resample=True)
    rows = []
    for index in range(start, min(total, start + count)):
        r, c = divmod(index, cube.nc)
        raw = cube.data[:, r, c].astype(float)
        values = raw / cube.scale
        values[cube.masked] = np.nan
        if cube.nodata is not None:
            values[raw == cube.nodata] = np.nan
        target = dict(wavelengths=cube.wl.tolist(), values=clean(values))
        y = apply_mask(w, vector(prepare(target, pixel_settings)), settings)
        valid = np.isfinite(y) & np.isfinite(matrix).all(axis=1)
        row = dict(row=r, column=c, status='invalid', coefficients=None, rmse=None,
                   relative_error=None, strength=None, attempts=0, used_bands=int(valid.sum()), message='')
        rows.append(row)
        if valid.sum() < max(3, len(candidates)) or np.linalg.norm(y[valid]) == 0 or np.any(np.linalg.norm(matrix[valid], axis=0) == 0):
            row['message'] = 'Insufficient shared bands or zero signal.'
            continue
        current = strength
        while True:
            row['attempts'] += 1
            row['strength'] = current if settings.get('mode', 'sparse') == 'sparse' else None
            try:
                result = fit(target, candidates, {**settings, 'strength': current},
                             aligned=(w, y, matrix, valid), diagnostics=False)
                row.update(status='retried' if row['attempts'] > 1 else 'ok',
                           coefficients=[e['value'] for e in result['coefficients']],
                           rmse=result['rmse'], relative_error=result['relative_error'], message='; '.join(result['warnings']))
                break
            except ValueError as error:
                if (retry and settings.get('mode', 'sparse') == 'sparse'
                        and str(error).startswith('Sparse solver did not converge') and current < ceiling):
                    current = min(ceiling, max(.001, current * 10))
                    continue
                row.update(status='failed', message=str(error))
                break
    return dict(pixels=rows, next=start + len(rows), total=total)
