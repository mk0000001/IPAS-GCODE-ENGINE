"""Streaming must expose completed ranges before reading later modal state."""
from decimal import localcontext
from io import BytesIO
from pathlib import Path
import math
import tempfile
import time
import unittest
from unittest.mock import patch

from print_gcode_engine.checkpoint import segment_checkpoints
from print_gcode_engine.scanner import scan
from print_gcode_engine.parallel import analyze_parallel_file
import print_gcode_engine.parallel as parallel


def fixture(layers=96):
    rows=['; filament_type = PLA;ABS', '; filament_diameter = 1.75,1.75', 'G90', 'M83']
    for layer in range(layers):
        rows.extend([';LAYER_CHANGE', f';HEIGHT:{.1+(layer%2)*.1}', ';WIDTH:0.6',
                     f'G1 X{layer}.125 Y2 Z{layer*.2} E1 F1200',
                     'G92 X0 E0', 'G91', 'G1 X.5 Y-.25 E-.8', 'G20',
                     'G1 X.25 E.01', 'G21', 'G90', 'G1 X40 E.6',
                     'M82', 'G92 E0', 'G1 E-.4', 'G1 X41 E.2',
                     'T1', 'G92 E2', 'G1 Y11 E2.3', 'T0', 'M83',
                     'G18', 'G90.1', 'G17', 'G91.1', 'M104 S220',
                     'M140 S60', '; FEATURE: Outer wall', 'G1 X44 E1 F1800'])
    return ('\n'.join(rows)+'\n').encode()


class StreamedCheckpoints(unittest.TestCase):
    def assert_numeric_parity(self,actual,expected,path='result'):
        # Parallel regrouping already differs from serial by ~1e-11 in raw
        # unrounded process totals. Decimal strings, identifiers and all shapes
        # remain exact; permit only floating-point summation noise for floats.
        if isinstance(expected,float) and path in (
                'result.process_metrics.deposition_length_mm',
                'result.process_metrics.nominal_deposition_seconds'):
            self.assertTrue(math.isclose(actual,expected,rel_tol=1e-12,abs_tol=1e-10),
                            (path,actual,expected))
        elif isinstance(expected,dict):
            self.assertEqual(actual.keys(),expected.keys(),path)
            for key in expected:self.assert_numeric_parity(actual[key],expected[key],path+'.'+key)
        elif isinstance(expected,list):
            self.assertEqual(len(actual),len(expected),path)
            for index,(a,b) in enumerate(zip(actual,expected)):
                self.assert_numeric_parity(a,b,f'{path}[{index}]')
        else:self.assertEqual(actual,expected,path)

    def test_ranges_arrive_before_a_later_invalid_line(self):
        data=fixture()+b'\x00invalid\n'+fixture()
        emitted=[]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'late-invalid.gcode';path.write_bytes(data)
            try:
                with self.assertRaisesRegex(ValueError,'BINARY_GCODE_NOT_SUPPORTED'):
                    segment_checkpoints(path,4,parts=16,on_segment=emitted.append)
            except TypeError as error:
                self.fail(f'Streaming callback is not implemented: {error}')
        self.assertGreater(len(emitted),0)
        self.assertLess(emitted[-1][1],data.index(b'\x00'))

    def test_streamed_ranges_are_contiguous_and_preserve_full_modal_state(self):
        data=fixture();emitted=[]
        with tempfile.TemporaryDirectory() as directory,localcontext() as context:
            context.prec=50
            path=Path(directory)/'modal.gcode';path.write_bytes(data)
            try:
                segments=segment_checkpoints(path,4,parts=16,on_segment=emitted.append)
            except TypeError as error:
                self.fail(f'Streaming callback is not implemented: {error}')
            self.assertEqual(emitted,segments)
            self.assertEqual(len(segments),16)
            self.assertEqual(segments[0][0],0)
            self.assertEqual(segments[-1][1],len(data))
            for previous,current in zip(segments,segments[1:]):
                self.assertEqual(previous[1],current[0])
            for start,end,state in segments[1:]:
                expected=scan(BytesIO(data[:start]),start,include_internal=True)['_scan_state']
                for key,value in state.items():self.assertEqual(value,expected[key],(start,key))

    def test_callback_failure_stops_the_producer(self):
        calls=[]
        def stop(segment):
            calls.append(segment)
            raise RuntimeError('ANALYSIS_CANCELLED')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cancel.gcode';path.write_bytes(fixture())
            try:
                with self.assertRaisesRegex(RuntimeError,'ANALYSIS_CANCELLED'):
                    segment_checkpoints(path,4,on_segment=stop)
            except TypeError as error:
                self.fail(f'Streaming callback is not implemented: {error}')
        self.assertEqual(len(calls),1)

    def test_pipeline_preserves_serial_results_and_monotonic_progress(self):
        data=fixture();updates=[]
        with tempfile.TemporaryDirectory() as directory,localcontext() as context:
            context.prec=50
            path=Path(directory)/'runtime.gcode';path.write_bytes(data)
            expected=scan(BytesIO(data),len(data))
            actual=analyze_parallel_file(path,progress=updates.append,workers=2,parts=8)
        actual.pop('analysis_execution')
        self.assert_numeric_parity(actual,expected)
        positions=[row['bytes_processed'] for row in updates]
        self.assertEqual(positions,sorted(positions))
        self.assertEqual(positions[-1],len(data))

    def test_consumer_failure_cancels_submitted_children(self):
        def fail_after_submit(value):
            if value.get('submitted_chunks',0)>0:raise RuntimeError('CONSUMER_FAILED')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'consumer-failed.gcode';path.write_bytes(fixture())
            with self.assertRaisesRegex(RuntimeError,'CONSUMER_FAILED'):
                analyze_parallel_file(path,progress=fail_after_submit,workers=2,parts=8)

    def test_worker_can_finish_while_later_checkpoints_are_still_pending(self):
        # Pause only the real producer's IO cadence; use actual spawn workers and
        # scans. A deferred-submit implementation cannot complete this first range.
        completed_during_prepass=[]
        original=segment_checkpoints
        def observed(path,workers,**kwargs):
            submit=kwargs['on_segment'];notify=kwargs['progress'];first=True
            def slow_producer(segment):
                nonlocal first
                submit(segment)
                if first:
                    first=False;deadline=time.monotonic()+10
                    while not completed_during_prepass and time.monotonic()<deadline:
                        notify({'bytes_processed':segment[1],'total_bytes':path.stat().st_size,'lines':0})
                        time.sleep(.01)
                    self.assertTrue(completed_during_prepass,'No chunk completed before producer resumed')
            kwargs['on_segment']=slow_producer
            return original(path,workers,**kwargs)
        def progress(value):
            if value.get('phase')=='CHECKPOINT' and value.get('completed_chunks',0):
                completed_during_prepass.append(value['completed_chunks'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'overlap.gcode';path.write_bytes(fixture())
            with patch.object(parallel,'segment_checkpoints',side_effect=observed):
                result=analyze_parallel_file(path,workers=2,parts=8,progress=progress)
        self.assertEqual(result['observed_layer_markers'],96)
        self.assertTrue(completed_during_prepass)

    def test_validation_failure_after_submission_is_not_suppressed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad-tail.gcode';path.write_bytes(fixture()+b'\x00bad\n'+fixture())
            with self.assertRaisesRegex(ValueError,'BINARY_GCODE_NOT_SUPPORTED'):
                analyze_parallel_file(path,workers=2,parts=8)


if __name__=='__main__':unittest.main()
