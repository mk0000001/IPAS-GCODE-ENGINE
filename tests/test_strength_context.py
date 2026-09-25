import io
import unittest
from print_gcode_engine.scanner import scan


class StrengthContext(unittest.TestCase):
    def test_preserves_slicer_settings_without_claiming_measured_process(self):
        expected={'filament_flow_ratio':'1.0;1.1','extrusion_multiplier':'1.05',
                  'top_shell_layers':'4','bottom_shell_layers':'3','top_solid_layers':'5',
                  'bottom_solid_layers':'2','slow_down_layer_time':'8','min_layer_time':'10',
                  'fan_speed':'80','fan_speed_percent':'90'}
        payload=('G1 X0 Y0\n'+''.join('; '+k+' = '+v+'\n' for k,v in expected.items())).encode()
        result=scan(io.BytesIO(payload),len(payload))
        for key,value in expected.items():
            self.assertEqual(result['configuration'].get(key),value,key)


if __name__=='__main__':unittest.main()
