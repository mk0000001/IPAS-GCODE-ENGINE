"""Explicit ironing microheight is declared geometry, never a measured bead."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from print_gcode_engine.checkpoint import segment_checkpoints
from print_gcode_engine.scanner import scan


PREFIX = b'; filament_diameter = 1.75\nG90\nM83\n;TYPE:Outer wall\n;WIDTH:0.4\n;HEIGHT:0.2\nG0 Z0.2\nG1 X10 E1 F600\n'


class DeclaredMicroheightTests(unittest.TestCase):
    def collect(self, suffix):
        data = PREFIX + suffix
        rows = []
        result = scan(BytesIO(data), len(data), motion_context_callback=lambda *row: rows.append(row))
        return data, result, rows

    def test_explicit_ironing_microheight_keeps_command_context(self):
        for height in (.001, .0045, .0075, .019999, .02):
            with self.subTest(height=height):
                data, result, rows = self.collect(f';TYPE:Ironing\n;HEIGHT:{height}\nG1 X20 E0.001\n'.encode())
                context = rows[-1][-1]
                self.assertEqual(rows[-1][3], 'ironing')
                self.assertEqual(context['layer_height_mm'], height)
                self.assertEqual(context['line_width_mm'], .4)
                self.assertNotIn('INVALID_ROAD_DIMENSIONS', context['assessment_gaps'])
                self.assertGreater(context['commanded_volume_mm3'], 0)

    def test_raw_analysis_remains_equal_when_observer_is_disabled(self):
        data, observed, rows = self.collect(b';TYPE:Ironing\n;HEIGHT:0.0045\nG1 X20 E0.001\n')
        self.assertEqual(observed, scan(BytesIO(data), len(data)))
        self.assertNotIn('_scan_state', observed)

    def test_invalid_height_and_unsupported_width_do_not_reuse_previous_value(self):
        for field, value, key in [('HEIGHT','0','layer_height_mm'), ('HEIGHT','-0.0045','layer_height_mm'),
            ('HEIGHT','nan','layer_height_mm'), ('HEIGHT','0.0009','layer_height_mm'),
            ('HEIGHT','5.001','layer_height_mm'), ('WIDTH','0.0045','line_width_mm')]:
            with self.subTest(field=field,value=value):
                _, _, rows = self.collect(f';{field}:{value}\nG1 X20 E0.001\n'.encode())
                self.assertIsNone(rows[-1][-1][key])
                self.assertIn('INVALID_ROAD_DIMENSIONS', rows[-1][-1]['assessment_gaps'])

    def test_checkpoint_resume_preserves_explicit_microheight(self):
        data = PREFIX + b';TYPE:Ironing\n;HEIGHT:0.0045\nG1 X20 E0.001\n;LAYER_CHANGE\n' + b'; padding\n'*180 + b';LAYER_CHANGE\nG1 X30 E0.001\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'microheight.gcode'; path.write_bytes(data)
            for context_enabled in (False, True):
                with self.subTest(context=context_enabled):
                    chunks = segment_checkpoints(path, workers=2, motion_context=context_enabled)
                    self.assertIsNotNone(chunks)
                    self.assertGreater(len(chunks), 1)
                    start, end, state = chunks[1]
                    self.assertEqual(state['layer_height'], .0045)
                    rows = []
                    if context_enabled:
                        scan(BytesIO(data[start:end]), end-start, initial_state=state,
                             motion_context_callback=lambda *row: rows.append(row))
                        self.assertEqual(rows[-1][-1]['layer_height_mm'], .0045)

    def test_cura_prime_tower_is_consumption_without_model_geometry_or_process(self):
        data = PREFIX + b';TYPE:PRIME-TOWER\nG0 X100 Y100\nG1 X120 E10 F600\n'
        value = scan(BytesIO(data), len(data))
        baseline = scan(BytesIO(PREFIX), len(PREFIX))
        self.assertEqual(value['layer_volume_profile'], baseline['layer_volume_profile'])
        self.assertEqual(value['orientation'], baseline['orientation'])
        self.assertEqual(value['dimensions_mm'], baseline['dimensions_mm'])
        self.assertEqual(value['process_metrics'], baseline['process_metrics'])
        self.assertEqual(value['filament_mm'], ['11'])


if __name__ == '__main__': unittest.main()
