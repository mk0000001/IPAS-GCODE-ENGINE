from decimal import localcontext
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from print_gcode_engine.checkpoint import segment_checkpoints
from print_gcode_engine.scanner import scan


class CheckpointStates(unittest.TestCase):
    def test_every_checkpoint_matches_full_scanner_with_modal_changes(self):
        rows=['; filament_diameter = 1.75,1.75','G21','G90','M83']
        for layer in range(100):
            rows.extend([';LAYER_CHANGE',f'; LINE_WIDTH: {0.4 + (layer % 3) * 0.1}',
                         f';HEIGHT:{0.1 + (layer % 2) * 0.1}',
                         ';WIDTH:nan','; LAYER_HEIGHT: 99',
                         f'G1 X{layer}.12345678901234567890123456789012345678901234567890123456789 Y2 Z{layer*.2} F1200 E1',
                         'G1 X50 Y4','G92 X10 Y-3','G91','G1 X.5 Y-.25 E-.8','G20','G1 Y.25 F60 E.01','G21',
                         'G90','G1 X40 Y10 E.6','M82','G92 E0','G1 X41 E-.4','G1 X42 E.1','G1 X43 E.4',
                         'T1','G92 E2','G1 Y11 E2.3','T0','M83','G18','G90.1','G17','G91.1','M104 S220','M140 S60',
                         '; FEATURE: Outer wall','G1 X44 E1','G1 Y12 F1800'])
        data=('\n'.join(rows)+'\n').encode()
        with tempfile.TemporaryDirectory() as directory,localcontext() as ctx:
            ctx.prec=50;path=Path(directory)/'fixture.bin';path.write_bytes(data)
            for workers in (2,4,6):
                for start,end,state in segment_checkpoints(path,workers)[1:]:
                    expected=scan(BytesIO(data[:start]),start,include_internal=True)['_scan_state']
                    for key,value in state.items():self.assertEqual(value,expected[key],(workers,start,key))

    def test_resumed_scan_preserves_and_updates_outline_dimensions(self):
        prefix=b'; LINE_WIDTH: 0.6\n; LAYER_HEIGHT: 0.3\nM83\nG1 X1 E1\n'
        state=scan(BytesIO(prefix),len(prefix),include_internal=True)['_scan_state']
        self.assertEqual((state['line_width'],state['layer_height']),(.6,.3))
        events=[]
        suffix=b'G1 X2 E1\n;WIDTH:inf\n;HEIGHT:-1\n;WIDTH:0.5\nG1 X3 E1\n'
        resumed=scan(BytesIO(suffix),len(suffix),initial_state=state,include_internal=True,
                     motion_callback=lambda *args:events.append(args))['_scan_state']
        self.assertEqual((resumed['line_width'],resumed['layer_height']),(.5,.3))
        self.assertEqual(len(events),2)
        self.assertTrue(all(len(event)==7 for event in events))


if __name__=='__main__':unittest.main()
