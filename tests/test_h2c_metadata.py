import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from print_gcode_engine.analyzer import analyze
from print_gcode_engine.scanner import scan


class H2CMetadataTests(unittest.TestCase):
    def test_raw_gcode_retains_multicolor_settings(self):
        for setting in ('filament_map_mode = Auto For Flush', 'single_extruder_multi_material = 1'):
            with self.subTest(setting=setting):
                data = ('; printer_model = Bambu Lab H2C\n; ' + setting + '\n'
                        '; filament_is_mixed = 0,1\n'
                        '; filament_type = PLA,PLA\nT1\nM83\nG1 X1 E1\n').encode()
                result = scan(io.BytesIO(data), len(data))
                self.assertEqual(result['multicolor_system'], 'VORTEK')
                self.assertTrue(result['full_spectrum_detected'])

    def test_plate_15_uses_only_its_own_filament_metadata(self):
        # Reduced fixture preserves the supplied archive's sparse filament IDs.
        masses = [(1, '88.11'), (2, '13.72'), (3, '6.42'),
                  (4, '8.13'), (7, '13.19'), (8, '10.57')]
        filament = ''.join(f'<filament id="{i}" type="PLA" used_g="{mass}" '
                           f'color="#{i:06x}" used_for_object="true"/>' for i, mass in masses)
        xml = ('<config><plate><metadata key="index" value="1"/>'
               '<metadata key="prediction" value="99"/>'
               '<filament id="1" type="PETG" used_g="999"/></plate>'
               '<plate><metadata key="index" value="15"/>'
               '<metadata key="prediction" value="55697"/>' + filament + '</plate></config>')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'plate.3mf'
            with ZipFile(path, 'w') as archive:
                archive.writestr('Metadata/plate_15.gcode', '; total estimated time: 15h 28m 17s\n')
                archive.writestr('Metadata/slice_info.config', xml)
                archive.writestr('Metadata/project_settings.config', json.dumps({
                    'printer_model': 'Bambu Lab H2C', 'nozzle_diameter': ['0.4', '0.4'],
                    'physical_extruder_map': ['1', '0'], 'filament_map_mode': 'Auto For Flush',
                    'filament_flow_ratio':['1.0','1.1'],'slow_down_layer_time':'8','top_shell_layers':'4',
                    'has_filament_switcher': '1'}))
            result = analyze(path)
        self.assertEqual(result['duration_seconds'], 55697)
        self.assertEqual(result['grams'], '140.14')
        self.assertEqual(result['tool_ids'], [0, 1, 2, 3, 6, 7])
        self.assertEqual(result['normal_output_color_count'], 6)
        self.assertEqual(result['printer'], 'H2C')
        self.assertEqual(result['multicolor_system'], 'VORTEK')
        self.assertEqual(result['configuration']['physical_extruder_map'], ['1', '0'])
        self.assertEqual(result['configuration']['filament_flow_ratio'], ['1.0','1.1'])
        self.assertEqual(result['configuration']['slow_down_layer_time'], '8')
        self.assertEqual(result['configuration']['top_shell_layers'], '4')


if __name__ == '__main__':
    unittest.main()
