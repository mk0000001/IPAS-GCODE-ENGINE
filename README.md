# Print G-code Engine

Standalone bounded-memory G-code and sliced-3MF analyzer. `print_gcode_engine.analyzer.analyze(path)` returns slicer metadata, active material usage, process metrics, and toolpath orientation. Supports large sequential streams and ZIP member streaming. External G-code remains untrusted for production.

StealthChanger/Orca tool profiles are recognized from `printer_settings_id` and Klipper start comments; sparse T tool IDs are mapped to profile ordinals when only active profiles are listed. This package does not make strength or pricing decisions.

H2C sliced-3MF analysis uses the selected executable plate and active filament XML records, rather than counting plate previews or all configured materials. Raw H2C headers retain multicolor mode settings. Filament IDs, nozzle records and physical extruders are distinct concepts; conditional AMS comments do not prove an installed AMS inventory.

Optional native Cython compilation and layer-aligned multiprocessing preserve modal state (including geometry width and height), tool/retraction state and ordered results. Parallelism is enabled selectively because checkpoint overhead can outweigh gains on smaller files. Trailing filament diameter settings are reconciled into deposited-volume profiles.

Run `python -m unittest discover -s tests`. `build_native.py` optionally compiles the scanner and related modules with Cython; the same suite can be run against the compiled package.
