import tempfile
import unittest
from pathlib import Path
from print_gcode_engine.analyzer import analyze


class StrengthSettings(unittest.TestCase):
    def test_explicit_deposited_width_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'width.gcode'
            path.write_text('; nozzle_diameter = 0.4\n; outer_wall_line_width = 0.8\n'
                            '; sparse_infill_density = 0\n; wall_loops = 0\nG90\nM83\nG1 X1 Y1 Z0.2 E1\n')
            result=analyze(path)['configuration']
            self.assertEqual(float(result['outer_wall_line_width']),.8)
            self.assertEqual(float(result['sparse_infill_density']),0.)
            self.assertEqual(float(result['wall_loops']),0.)


if __name__=='__main__':unittest.main()
