from io import BytesIO
import unittest
from print_gcode_engine.scanner import scan


class ViewerStreamTests(unittest.TestCase):
    def test_first_deposition_bounds_include_both_endpoints(self):
        data=b'G90\nM83\nG1 X10 Y10\n; FEATURE: Outer wall\nG1 X20 Y20 E1\n'
        self.assertEqual(scan(BytesIO(data),len(data))['dimensions_mm'],['10','10','0'])

    def test_chunk_bounds_match_full_path_with_extreme_start(self):
        from print_gcode_engine.merge import merge_chunks
        first=b'G90\nM83\nG1 X-10 Y-10\n; FEATURE: Outer wall\nG1 X0 Y0 E1\n'
        second=b'G1 X10 Y10 E1\n'
        a=scan(BytesIO(first),len(first),include_internal=True)
        b=scan(BytesIO(second),len(second),initial_state=a['_scan_state'],include_internal=True)
        whole=scan(BytesIO(first+second),len(first+second))
        self.assertEqual(merge_chunks([a,b])['dimensions_mm'],whole['dimensions_mm'])
        self.assertEqual(whole['dimensions_mm'],['20','20','0'])

    def test_stationary_unretract_does_not_create_model_area(self):
        data=b'; filament_diameter = 1.75\nM83\n;LAYER_CHANGE\nG1 X1 Z.2 E1\nG1 E-.79999\n;LAYER_CHANGE\nG1 Z.3\nG1 E.8\n; FEATURE: Support\nG1 X2 E1\n'
        result=scan(BytesIO(data),len(data))
        self.assertEqual([row['z_mm'] for row in result['layer_volume_profile']['layers']],[.2])
        self.assertEqual(result['observed_layer_markers'],2)

    def test_full_circle_observer_has_geometry_and_positive_model_path(self):
        data=b'; filament_diameter = 1.75\nM83\n;LAYER_CHANGE\nG1 X10 Z.2 E1\nG2 I-10 J0 E1\n'
        events=[]
        result=scan(BytesIO(data),len(data),motion_callback=lambda *row:events.append(row[6]))
        self.assertEqual(len(events),2)
        self.assertAlmostEqual(events[-1]['geometry']['radius'],10)
        self.assertGreater(result['layer_volume_profile']['layers'][0]['volume_mm3'],4)


if __name__=='__main__':unittest.main()
