# Unmixing performance investigation

Run `venv/bin/python benchmarks/profile_scene.py --case distinct` or
`venv/bin/python benchmarks/profile_scene.py --case similar` from the project
directory. The script creates a temporary 512 × 512 × 420 float32 ENVI cube
with 12 synthetic library spectra, solves 2,048 pixels, prints a CPU profile,
and deletes the generated files. `--pixels` controls the sample size and
`--profile` selects fast, balanced, or precise tolerance.

The scene-time projection is a linear estimate, not a full-scene measurement.
It excludes cube generation, disk checkpointing, browser transfers, and GPU
selection. Timings depend on hardware, batch size, and the actual spectra.

In the September 25 investigation, both cases used the configured 80-center
HELMET grid with 59 shared usable bands. Before optimization, the numerical
solver occupied over 99% of sampled batch time; spectral preparation took
approximately 0.02 seconds. The similar-material case reached a median of
14,438 iterations including retries, versus 1,938 for the other case.

The coordinate solver previously copied and scattered its active-pixel matrix
inside every material update. Keeping contiguous working arrays and compacting
only when pixels finish reduced measured sample times from 7.24 to 1.38 seconds
and from 25.39 to 4.97 seconds, respectively. These initial timings are
indicative, not controlled whole-scene benchmarks. A separate sequential
before/after check found identical coefficients, convergence flags, and
iteration counts for both ordinary and correlated 12-material systems.

The deliberately difficult similar-material case still had 519 of 2,048 pixels
fail convergence after retries. Faster execution does not resolve ambiguous
spectra or change the sparsity objective, tolerance, or iteration limits.
