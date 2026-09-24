from decimal import Decimal, localcontext
from io import BytesIO
import unittest

from print_gcode_engine.scanner import scan


class RetractionAccountingTests(unittest.TestCase):
    def test_zero_partial_and_full_recovery_across_tools_units_and_modes(self):
        data = b'''G90
M83
G1 X1 E1
G1 X2 E-.8
G1 X3 E.3
G1 X4 E.7
T1
G1 X5 E.5
G1 X6 E-.5
G1 X7 E.5
M82
G92 E10
G1 X8 E10.25
T0
M83
G1 X9 E.05
G20
G1 X1 E.01
G21
'''
        observed = []
        with localcontext() as ctx:
            ctx.prec = 50
            result = scan(BytesIO(data), len(data), include_internal=True,
                          motion_callback=lambda *args: observed.append(args[5]))
        self.assertEqual(result['filament_mm'], ['1.504', '0.75'])
        self.assertEqual(observed, [Decimal(value) for value in
                                   ('1', '0', '0', '.2', '.5', '0', '0', '.25', '.05', '.254')])
        self.assertTrue(all(value == 0 for value in result['_scan_state']['retract'].values()))

    def test_high_precision_extrusion_keeps_decimal_context_rounding(self):
        amount = '0.12345678901234567890123456789012345678901234567890123456789'
        data = f'M83\nG1 X1 E{amount}\nG1 X2 E-{amount}\nG1 X3 E{amount}\nG1 X4 E{amount}\n'.encode()
        observed = []
        with localcontext() as ctx:
            ctx.prec = 50
            rounded = Decimal(amount) * Decimal(1)
            expected = rounded + rounded
            result = scan(BytesIO(data), len(data), include_internal=True,
                          motion_callback=lambda *args: observed.append(args[5]))
        self.assertEqual(Decimal(result['filament_mm'][0]), expected)
        self.assertEqual(observed, [rounded, Decimal(0), Decimal(0), rounded])


if __name__ == '__main__':
    unittest.main()
