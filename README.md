# HELMET · Spectral Workbench

One local app for exploring hyperspectral scenes, organizing signatures, and testing mixture experiments. Includes a synthetic landscape, six illustrative material spectra, and a saved 65/35 meadow–soil mixture. These are demonstration data, not measured materials or sensor observations.

## Start

Keep this entire folder together. Python 3.10 or newer is recommended.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Open **http://127.0.0.1:8766**. On macOS, `Launch HELMET.command` uses the virtual environment automatically. No manual activation is needed. The launcher accepts either `.venv` or `venv`. The environment recreated on this computer uses its existing installed scientific packages via system-site-packages; the setup commands above create an independent environment on another computer. The environment folder is specific to this computer; recreate it with the commands above after moving the app to another location or computer. Stop it with Control+C in its terminal.

To use a different port or load your data at startup:

```sh
.venv/bin/python app.py --path "/full/path/to/scene.img" --port 8000
```

No Node, Streamlit, account, API key, or external web service is required. Assets are local and the server listens only on loopback.

## Your data

Use **Open dataset** in the top bar and enter the image's full local path. The matching `scene.hdr` or `scene.img.hdr` must be beside it. ENVI dimensions, interleave, byte order, header offset, wavelength centers, reflectance scale factor, bad-band list, and data-ignore values are read from the header. Real-valued BSQ, BIL, and BIP cubes are supported. Wavelengths must be increasing and specified for every band. A missing scale factor uses 1 with a visible notice; verify data calibration before fitting. The full cube is loaded into memory, so very large cubes depend on available RAM.

## Explore

- Scroll/pinch to zoom at the pointer, use Pan or Space + drag, draw a Region to zoom, or use Fit / 1:1.
- Enter a row/column or linear pixel index, then click **Preview reference pixel** (or press Enter). The fields synchronize and the scene centers on the selected pixel. Coordinates are zero-based; index = row × image width + column.
- Save a named spectrum with its category and description directly into the shared library.
- Choose the current pixel or a library spectrum and click **Set reference** to lock its spectrum. Then click **Find matches** to compute the map. Use **Compare another pixel** to select an optional teal comparison spectrum. The purple reference remains locked, and Find matches always uses it. **Change reference** explicitly reopens reference selection; setting a new reference clears the old map and comparison. Threshold, opacity, and display controls update the cached score map.
- Unmix with selected candidates using either **Sparse coefficients** (nonnegative L1 regression, not forced to sum to one) or **Fractions** (nonnegative coefficients summing to 100%). Fraction mode optionally prunes to a maximum material count and re-fits; this is a heuristic, not an exhaustive sparse subset search.
- Before fitting, review Wavelength coverage: target/analysis band counts, shared usable bands, and a wavelength strip showing target exclusions and unavailable candidate coverage. Expand Candidate coverage to see each source band count and overlap. Limited candidates are flagged, not silently removed. The preview and solver use the same alignment path. Reconstruction values are returned only on shared valid bands; unsupported bands remain blank.
- Inspect the reconstruction, RMSE, relative error, coefficient sum, bands used, and ambiguity warnings.

## Region averages

In Scene Explorer, choose **Region average** and drag a rectangle over the image. This is separate from **Zoom region**. The rectangle is clipped to the image and uses inclusive, zero-based pixel bounds. Choose at least two pixels.

The preview shows the mean and ±1 sample standard deviation at native band centers. Header bad bands, nonfinite measurements, and no-data values are excluded; valid pixel counts can differ by band and are shown in the expandable coverage list. A band with one valid pixel has a mean but no standard deviation. Variability describes the spatial spread, not uncertainty in the mean.

**Name and save average** saves the mean, standard deviation, source rectangle, and count summary in the library CSV. **Set as reference** locks the region mean for similarity mapping and draws its rectangle in purple. This does not automatically run Find matches. Existing analysis exclusions still apply when comparing or fitting the mean.

## Library

Search/filter materials, compare curves, inspect a wavelength heatmap, rank selected candidates by SAM or RMSE, edit names/categories/descriptions, archive/restore entries, or send a material to Explore or Experiment.

**Import materials** accepts multiple CSVs with a preview before saving:

- Two columns: wavelength, reflectance (text metadata/header rows are tolerated).
- Legacy HELMET wide libraries: `Material`, optional `Category` / `Description` / `ID`, then wavelength-named columns.
- HELMET running long-format libraries with `spectrum_id`, `band_center_nm`, `reflectance`, and `valid`.
- Exported pixel CSVs with `spectrum`, `band_center_nm`, `reflectance`, and `valid`.

Automatic units recognize micrometer-scale wavelength headers (less than 50) and convert them to nm. You can override with nm or µm. Both `custom_materials.csv` and `HELMET_materials.csv` can be selected together; filenames do not restrict recognition. Entirely blank rows are ignored. Source material IDs, names, categories, and descriptions are preserved. When the exact legacy 80-band HELMET grid is recognized, its 20 excluded bands are stored as invalid rather than used as real samples. The preview reports this before saving. Columns named `band_center_nm` always use nm. Missing or nonfinite values remain invalid. Import preserves original sampling; it does not silently force materials onto an 80-band grid. Manual names/categories work offline; the old internal AI naming service is not called by this app.

The running CSV is `data/spectral_library.csv`. It retains names, categories, descriptions, source, timestamps, archival status, band indices, band centers in nm, reflectance, and validity flags. Source details for saved pixels include row and column. Invalid reflectance is blank with valid=0. Writes are atomic and serialized within one server. Do not run multiple servers against the same writable library.

`Download library CSV` exports active materials. Archived records remain in the on-disk CSV for restoration. To select another persistent library, use `--library "/full/path/to/library.csv"`. A new library starts with the six synthetic examples.

**When upgrading, preserve your existing `data/spectral_library.csv`.** Do not replace it with the demo copy from a fresh download.

## Experiment

Select materials, set fractions totaling 100%, optionally add reproducible Gaussian reflectance noise, and generate a mixture. Recover fractions to compare known and estimated compositions. Save the mixture to Library or export endmembers, known fractions, mixture, clean mixture, and reconstruction to CSV. Changing fractions or noise clears stale results. The noise model is illustrative, not the missing original calibrated noise model.

## Material Explorer and library organization

**Materials** opens Material Explorer. Its purple Reference spectrum card shows the selected name, category, coverage, and valid-band count. Target category narrows the reference dropdown; Search for matches in independently filters match candidates. Choose an inspected pixel, saved spectrum, or generated mixture, optionally restrict the search category, and find ranked matches. The Top 5 matches panel has color-coded toggles that overlay several spectra and their residuals at once. The target stays visible. The ranked table has synchronized Show checkboxes; clicking a material name reveals its curve and brings the chart into view. Self-matches are excluded by ID. All candidates in a ranking use the same valid-band intersection; a candidate with limited coverage can reduce that intersection.

Abundance fitting remains in Scene Explorer’s Unmix panel. Material Explorer focuses on visual comparisons. Similarity scores are not confidence estimates.

Use **Group by** in the Library toolbar to group cards by category or show a flat list. **Manage library** contains Create category, Review duplicates, and Review archived. Checking spectra reveals a selection bar with Average selected, Assign category, and Clear selection. Average requires at least two selections. Category headings have a small actions menu for selecting the group or reviewing its duplicates. Each spectrum keeps its own name.

**Review archived** supports bulk restore and permanent deletion. Deletion lists the chosen names and requires typing DELETE. Active spectra cannot be deleted through this action. Archived entries can be edited before restoration if a name conflicts with an active spectrum.

**Average selected** computes an equal-weight mean only where every selected spectrum has a valid interpolated value. The preview shows ±1 sample standard deviation, not uncertainty in the mean. Name and save the average to retain its contributor IDs/names and per-band standard deviation in the running CSV. Originals remain separate.

**Review duplicates** scans checked spectra (or the filtered library when fewer than two are checked). Set a cosine threshold and optional RMSE limit, then keep both or archive one. Archival is reversible. Reviews are capped at 500 spectra and use pairwise shared valid bands.

Drag horizontally on the Material Explorer chart or enter **From / To** values to choose an inclusive wavelength range. **Reset** restores full coverage. Changing analysis settings clears previous results and scene maps. **Save preset** persists target centers, interpolation method, exclusions, range, search category, and ranking metric beside the library in `spectral_library.settings.json`. Reusing a preset name updates it.

## Resampling and valid bands

Edit **resampling.py** to change `TARGET_BANDS_NM`, `EXCLUDED_RANGES_NM`, `INTERPOLATION_METHOD`, or `MAX_GAP_FACTOR`, then restart the server and refresh the browser. Defaults use the legacy 80-band HELMET grid in nanometers, with its 20 excluded bands. Saved presets retain their own configuration snapshots.

Natural cubic splines are the default. The settings dialog also offers PCHIP and linear interpolation. Each continuous valid segment is interpolated separately: missing values, excluded intervals, and large wavelength gaps split segments. There is no extrapolation. Two-point segments use linear interpolation. Cubic splines may overshoot; values are not clipped. This is band-center interpolation, not sensor-response convolution.

Library ranking, averages, and mixtures use the configured target grid and source validity masks. Scene Unmix defaults to automatic alignment on the target’s native band centers; its Alignment grid control can instead select the configured HELMET grid. Manual exclusions are inclusive nm ranges, for example `1350:1450,1800:1950`. The legacy exclusions are 922.5–989, 1085.5–1197.5, 1334–1500, and ≥1750 nm. Change them for other instruments as needed.

Whole-scene similarity maps evaluate on the cube's native band centers for efficiency, interpolating the reference to those centers and applying the same exclusions/range. Their scores can differ from Material Explorer scores on the configured grid. Original library measurements are never overwritten by comparison settings.

A high cosine score is not material-identification confidence. Fraction constraints do not guarantee physically correct abundances: candidates, calibration, illumination, nonlinear mixtures, and omitted materials matter. Synthetic samples should not be used as a measured reference library for real data.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The 23 tests cover resampling configuration, gap boundaries, shared-band averages and provenance round-tripping, ranking, duplicate detection, saved presets, and known mixture recovery in both fitting modes, bad bands, additional exclusions, gap-safe interpolation, CSV persistence/edit/archive, legacy imports, repeatable noise, comparison, cube indexing, and cosine self-matching. Browser checks cover navigation, saving a mixture, scene fitting, reference matching, and zoom. Real-data accuracy and large-cube performance still need validation on your datasets.

The supplied earlier folders remain unchanged; this is a separate, consolidated application.
# spectral_tools
