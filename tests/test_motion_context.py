from decimal import Decimal
from io import BytesIO
from pathlib import Path
import math
import tempfile
import unittest

from print_gcode_engine.scanner import scan
from print_gcode_engine.checkpoint import segment_checkpoints


PREFIX = '; filament_diameter = 1.75\nM83\n;TYPE:Outer wall\n;WIDTH:0.4\n;HEIGHT:0.2\nG1 Z0.2\n'


def collect(text, **kwargs):
    rows = []
    data = text.encode()
    result = scan(BytesIO(data), len(data), motion_context_callback=lambda *row: rows.append(row), **kwargs)
    return result, rows


class MotionContextTests(unittest.TestCase):
    def test_existing_callback_contract_and_context_disabled_output_are_preserved(self):
        text = PREFIX + 'M104 S220\nG1 X10 E1 F600\n'
        raw = text.encode(); legacy = []
        baseline = scan(BytesIO(raw), len(raw), motion_callback=lambda *row: legacy.append(row))
        actual, rows = collect(text, motion_callback=lambda *row: self.assertEqual(len(row), 7))
        self.assertEqual(actual, baseline)
        self.assertEqual(len(rows), len(legacy))
        self.assertEqual(rows[-1][5], Decimal(1))
        context = rows[-1][-1]
        self.assertEqual(context['commanded_speed_mm_s'], 10)
        self.assertAlmostEqual(context['commanded_volume_mm3'], 2.4052818754)
        self.assertEqual(context['line_width_mm'], .4)
        self.assertEqual(context['layer_height_mm'], .2)
        with self.assertRaises(TypeError): context['flow_override_percent'] = 50

    def test_slicer_ratio_is_not_a_second_volume_multiplier(self):
        _, rows = collect(PREFIX + '; filament_flow_ratio = 1.03\nM221 S50\nG1 X10 E1 F600\n')
        context = rows[-1][-1]
        self.assertEqual(context['raw_deposited_e'], 1)
        self.assertEqual(context['flow_override_percent'], 50)
        self.assertAlmostEqual(context['commanded_volume_mm3'], 1.2026409377)

    def test_m221_target_does_not_change_other_tool_flow(self):
        _, rows = collect(PREFIX + 'M221 T1 S50\nG1 X10 E1 F600\nT1\nG1 X20 E1\n')
        self.assertEqual([row[-1]['flow_override_percent'] for row in rows[-2:]], [100, 50])

    def test_volumetric_mode_and_disable_use_different_e_units(self):
        _, rows = collect(PREFIX + 'M200 S1 D1.75\nG1 X10 E1 F600\nM200 S0\nG1 X20 E1\nM200 D0\nG1 X30 E1\n')
        values = [row[-1] for row in rows[-3:]]
        self.assertEqual(values[0]['extrusion_unit'], 'VOLUME_MM3')
        self.assertEqual(values[0]['commanded_volume_mm3'], 1)
        self.assertEqual(values[1]['extrusion_unit'], 'FILAMENT_LENGTH_MM')
        self.assertAlmostEqual(values[1]['commanded_volume_mm3'], 2.4052818754)
        self.assertAlmostEqual(values[2]['commanded_volume_mm3'], 2.4052818754)

    def test_unknown_diameter_never_invents_filament_volume(self):
        _, rows = collect(PREFIX.replace('; filament_diameter = 1.75\n', '') + 'G1 X10 E1 F600\n')
        self.assertIsNone(rows[-1][-1]['commanded_volume_mm3'])
        self.assertIn('FILAMENT_DIAMETER_UNKNOWN', rows[-1][-1]['assessment_gaps'])

    def test_indexed_nozzle_is_not_a_logical_tool_mapping(self):
        result, rows = collect(PREFIX + 'M104 S220\nM104 T1 S280\nG1 X10 E1 F600\nT1\nG1 X20 E1\nM109 S240\nG1 X30 E1\n')
        self.assertEqual([row[-1]['nozzle_setpoint_c'] for row in rows[-3:]], [220, None, 240])
        self.assertIn('NOZZLE_TOOL_HEATER_MAPPING_UNVERIFIED', rows[-2][-1]['assessment_gaps'])
        self.assertEqual(result['process_metrics']['deposition_nozzle_setpoint_c']['max'], 240)

    def test_standby_nozzle_does_not_pollute_default_deposition_temperature(self):
        raw = (PREFIX + 'M104 S220\nM104 T1 S280\nG1 X10 E1 F600\n').encode()
        result = scan(BytesIO(raw), len(raw))
        self.assertEqual(result['process_metrics']['deposition_nozzle_setpoint_c']['last'], 220)
        self.assertEqual(result['process_metrics']['nozzle_setpoint_c']['max'], 280)

    def test_tool_change_clears_unmapped_nozzle(self):
        raw = (PREFIX + 'M104 S220\nT1\nG1 X10 E1 F600\n').encode()
        result = scan(BytesIO(raw), len(raw))
        self.assertIsNone(result['process_metrics']['deposition_nozzle_setpoint_c']['last'])

    def test_speed_backup_restore_and_fan_ids(self):
        _, rows = collect(PREFIX + 'M140 S60\nM141 S45\nM106 S128\nM220 S50\nM220 B\nG1 X10 E1 F600\nM220 S25\nM106 P1 S255\nG1 X20 E1\nM220 R\nM107\nG1 X30 E1\n')
        contexts = [row[-1] for row in rows[-3:]]
        self.assertEqual([c['commanded_speed_mm_s'] for c in contexts], [5, 2.5, 5])
        self.assertEqual([c['part_cooling_fan_pwm'] for c in contexts], [128, 128, 0])
        self.assertEqual(contexts[0]['bed_setpoint_c'], 60)
        self.assertEqual(contexts[0]['chamber_setpoint_c'], 45)
        self.assertEqual(contexts[0]['feedrate_mm_min'], 600)

    def test_recovery_is_not_deposition(self):
        _, rows = collect(PREFIX + 'G1 E-1\nG1 X10 E1 F600\nG1 X20 E2\n')
        self.assertEqual([row[-1]['raw_deposited_e'] for row in rows[-2:]], [0, 2])
        self.assertEqual(rows[-2][-1]['commanded_volume_mm3'], 0)
        self.assertAlmostEqual(rows[-1][-1]['commanded_volume_mm3'], 4.8105637508)

    def test_override_change_with_retract_debt_withholds_effective_volume(self):
        _, rows = collect(PREFIX + 'G1 E-1\nM221 S50\nG1 X10 E2 F600\nG1 X20 E1\n')
        self.assertIsNone(rows[-2][-1]['commanded_volume_mm3'])
        self.assertIn('RETRACTION_CONTEXT_CHANGED', rows[-2][-1]['assessment_gaps'])
        self.assertAlmostEqual(rows[-1][-1]['commanded_volume_mm3'], 1.2026409377)

    def test_unit_change_with_retract_debt_withholds_volume(self):
        _, rows = collect(PREFIX + 'G1 E-1\nM200 D1.75\nG1 X10 E2 F600\n')
        self.assertIsNone(rows[-1][-1]['commanded_volume_mm3'])
        self.assertIn('RETRACTION_CONTEXT_CHANGED', rows[-1][-1]['assessment_gaps'])

    def test_context_only_observer_gets_one_analytic_arc(self):
        _, rows = collect(PREFIX + 'G1 X10\nG2 X10 Y0 I-10 J0 E1 F600\n')
        arc_rows = [row for row in rows if row[6] is not None]
        self.assertEqual(len(arc_rows), 1)
        self.assertIn('geometry', arc_rows[0][6])
        self.assertAlmostEqual(arc_rows[0][6]['length'], 20*math.pi)
        self.assertAlmostEqual(arc_rows[0][-1]['commanded_volume_mm3'], 2.4052818754)

    def test_invalid_dimensions_do_not_reuse_previous_declaration(self):
        _, rows = collect(PREFIX + ';WIDTH:nan\nG1 X10 E1 F600\n')
        self.assertIsNone(rows[-1][-1]['line_width_mm'])
        self.assertIn('INVALID_ROAD_DIMENSIONS', rows[-1][-1]['assessment_gaps'])

    def test_invalid_overrides_modes_and_fans_are_not_silently_accepted(self):
        for command, key in [('M221 SNaN', 'commanded_volume_mm3'), ('M220 S-1', 'commanded_speed_mm_s'),
                             ('M200 S2', 'commanded_volume_mm3'), ('M106 S256', 'part_cooling_fan_pwm')]:
            with self.subTest(command=command):
                _, rows = collect(PREFIX + command + '\nG1 X10 E1 F600\n')
                self.assertIsNone(rows[-1][-1][key])
                self.assertTrue(rows[-1][-1]['assessment_gaps'])

    def test_checkpoint_restores_all_optional_context_state(self):
        text = PREFIX + ''.join(f';LAYER:{i}\n' + ('M104 S220\nM140 S60\nM141 S45\nM220 S50\nM220 B\nM221 S75\nM106 S128\nM200 D1.75\n' if i == 0 else '')
                               + f'G1 X{i+1} E1 F600\n' + '; padding ' + 'x'*100 + '\n' for i in range(16))
        _, expected = collect(text)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'tiny.gcode';path.write_text(text)
            chunks = segment_checkpoints(path, 4, motion_context=True)
            self.assertIsNotNone(chunks)
            raw = path.read_bytes();actual = []
            for start, end, state in chunks:
                _, rows = collect(raw[start:end].decode(), initial_state=state)
                actual.extend(rows)
        self.assertEqual([dict(row[-1]) for row in actual], [dict(row[-1]) for row in expected])

    def test_unknown_final_temperature_survives_process_merge(self):
        from print_gcode_engine.process import ProcessMetrics
        before = (PREFIX + 'M104 S220\nG1 X10 E1 F600\n').encode()
        after = b'T1\nG1 X20 E1\n'
        first = scan(BytesIO(before), len(before), include_internal=True)
        second = scan(BytesIO(after), len(after), include_internal=True, initial_state=first['_scan_state'])
        merged = ProcessMetrics()
        for row in (first, second): merged.merge(row['_scan_state']['process_snapshot'])
        self.assertIsNone(merged.result()['nozzle_setpoint_c']['last'])
        self.assertIsNone(merged.result()['deposition_nozzle_setpoint_c']['last'])
        self.assertEqual(merged.result(), scan(BytesIO(before+after), len(before+after))['process_metrics'])

    def test_resume_without_context_snapshot_withholds_unknown_prior_modes(self):
        before = (PREFIX + 'M221 S50\nM200 D1.75\n').encode()
        first = scan(BytesIO(before), len(before), include_internal=True)
        _, rows = collect('G1 X10 E1 F600\n', initial_state=first['_scan_state'])
        self.assertIsNone(rows[-1][-1]['commanded_volume_mm3'])
        self.assertIn('INITIAL_MOTION_CONTEXT_UNAVAILABLE', rows[-1][-1]['assessment_gaps'])

    def test_invalid_indexed_flow_does_not_produce_exact_volume(self):
        _, rows = collect(PREFIX + 'M221 T-1 S50\nG1 X10 E1 F600\n')
        self.assertIsNone(rows[-1][-1]['commanded_volume_mm3'])
        self.assertIn('FLOW_TOOL_TARGET_UNRESOLVED', rows[-1][-1]['assessment_gaps'])

    def test_temperature_preset_and_autotemp_do_not_claim_exact_active_setpoint(self):
        for command in ('M104 S220 I1', 'M104 S220 B250 F0.1'):
            with self.subTest(command=command):
                _, rows = collect(PREFIX + command + '\nG1 X10 E1 F600\n')
                self.assertIsNone(rows[-1][-1]['nozzle_setpoint_c'])
                self.assertTrue(rows[-1][-1]['assessment_gaps'])

    def test_secondary_fan_selector_does_not_assume_full_part_cooling(self):
        _, rows = collect(PREFIX + 'M106 T1\nG1 X10 E1 F600\n')
        self.assertIsNone(rows[-1][-1]['part_cooling_fan_pwm'])
        self.assertIn('FAN_COMMAND_VARIANT_UNRESOLVED', rows[-1][-1]['assessment_gaps'])

    def test_context_restore_rejects_boolean_and_nonfinite_numeric_facts(self):
        before, _ = collect(PREFIX + 'M104 S220\nM140 S60\nM141 S45\nM106 S128\n', include_internal=True)
        state = before['_scan_state']
        context_state = state['motion_context']
        context_state.update(nozzle=True, bed=float('nan'), chamber=float('inf'), speed=True, fans={0:True}, flows={0:True})
        _, rows = collect('G1 X10 E1 F600\n', initial_state=state)
        observed = rows[-1][-1]
        for key in ('nozzle_setpoint_c','bed_setpoint_c','chamber_setpoint_c','commanded_speed_mm_s',
                    'part_cooling_fan_pwm','flow_override_percent','commanded_volume_mm3'):
            self.assertIsNone(observed[key], key)

    def test_uncertain_recovery_state_survives_chunk_boundary(self):
        before, _ = collect(PREFIX + 'G1 E-1\nM221 S50\n', include_internal=True)
        _, rows = collect('G1 X10 E2 F600\nG1 X20 E1\n', initial_state=before['_scan_state'])
        self.assertIsNone(rows[0][-1]['commanded_volume_mm3'])
        self.assertIn('RETRACTION_CONTEXT_CHANGED', rows[0][-1]['assessment_gaps'])
        self.assertAlmostEqual(rows[1][-1]['commanded_volume_mm3'], 1.2026409377)

    def test_inch_volumetric_e_is_normalized_to_cubic_mm(self):
        _, rows = collect(PREFIX + 'M200 D1.75\nG20\nG1 X1 E1 F60\n')
        self.assertAlmostEqual(rows[-1][-1]['raw_deposited_e'], 16387.064)
        self.assertAlmostEqual(rows[-1][-1]['commanded_volume_mm3'], 16387.064)

    def test_runtime_diameter_is_retained_when_volumetric_mode_is_disabled(self):
        _, rows = collect(PREFIX + 'M200 D2.85 S0\nG1 X10 E1 F600\nM200 D0\nG1 X20 E1\n')
        for row in rows[-2:]:
            self.assertEqual(row[-1]['filament_diameter_mm'], 2.85)
            self.assertAlmostEqual(row[-1]['commanded_volume_mm3'], 6.3793965822)

    def test_m200_zero_diameter_disables_volumetric_even_with_s1(self):
        _, rows = collect(PREFIX + 'M200 D1.75\nM200 D0 S1\nG1 X10 E1 F600\n')
        context = rows[-1][-1]
        self.assertEqual(context['extrusion_unit'], 'FILAMENT_LENGTH_MM')
        self.assertAlmostEqual(context['commanded_volume_mm3'], 2.4052818754)

    def test_unresolved_macro_invalidates_prior_commanded_process_facts(self):
        established = 'M104 S220\nM140 S60\nM141 S35\nM106 S128\nM220 S75\nM221 S90\n'
        for macro in ('PRINT_START', 'START_PRINT', 'START_PRINT BED_TEMP=60',
                      'SET_GCODE_VARIABLE MACRO=PRINT_START VARIABLE=flow VALUE=2', 'CUSTOM_PRINT_MACRO'):
            with self.subTest(macro=macro):
                _, rows = collect(PREFIX + established + macro + '\nG1 X10 E1 F600\n')
                context = rows[-1][-1]
                for field in ('commanded_volume_mm3', 'commanded_speed_mm_s', 'speed_override_percent',
                              'flow_override_percent', 'nozzle_setpoint_c', 'bed_setpoint_c',
                              'chamber_setpoint_c', 'part_cooling_fan_pwm'):
                    self.assertIsNone(context[field], field)
                self.assertEqual(context['extrusion_unit'], 'UNKNOWN')
                self.assertIn('FIRMWARE_MACRO_UNRESOLVED', context['assessment_gaps'])

    def test_explicit_commands_restore_facts_but_not_macro_hidden_extrusion_state(self):
        _, rows = collect(PREFIX + 'PRINT_START\nM200 D1.75 S0\nM221 S100\nM220 S50\nM104 S230\n'
                          'M140 S65\nM141 S40\nM106 S96\nG1 X10 E1 F600\n')
        context = rows[-1][-1]
        self.assertEqual(context['commanded_speed_mm_s'], 5)
        self.assertEqual(context['nozzle_setpoint_c'], 230)
        self.assertEqual(context['bed_setpoint_c'], 65)
        self.assertEqual(context['part_cooling_fan_pwm'], 96)
        self.assertIsNone(context['commanded_volume_mm3'])
        self.assertIn('FIRMWARE_MACRO_UNRESOLVED', context['assessment_gaps'])

    def test_macro_volume_gap_survives_optional_checkpoint(self):
        text = PREFIX + 'PRINT_START\n' + ''.join(f';LAYER:{i}\nG1 X{i+1} E1 F600\n'
                                               + '; padding ' + 'x'*100 + '\n' for i in range(16))
        _, expected = collect(text)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'macro.gcode';path.write_text(text)
            chunks = segment_checkpoints(path, 4, motion_context=True)
            self.assertIsNotNone(chunks)
            raw = path.read_bytes();actual = []
            for start, end, state in chunks:
                _, rows = collect(raw[start:end].decode(), initial_state=state)
                actual.extend(rows)
        self.assertEqual([dict(row[-1]) for row in actual], [dict(row[-1]) for row in expected])
        for row in actual[-16:]:
            self.assertIsNone(row[-1]['commanded_volume_mm3'])
            self.assertIn('FIRMWARE_MACRO_UNRESOLVED', row[-1]['assessment_gaps'])


if __name__ == '__main__': unittest.main()
