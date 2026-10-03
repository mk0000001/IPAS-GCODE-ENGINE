"""Optional immutable commanded-process observations, never sensor measurements.

Conventional M200/M220/M221 semantics are retained separately from the legacy
raw-E analysis. Logical material tools never establish physical heater identity.
"""
from copy import deepcopy
from math import isfinite, pi
import re
from types import MappingProxyType

VERSION = 'GCODE_COMMANDED_PROCESS_CONTEXT_V1'
PARAMETERS = re.compile(r'([A-Z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:E[+-]?\d+)?|NAN|[+-]?INF(?:INITY)?)')
INDEXED_TOOL = re.compile(r'(?<![A-Z])T')


def finite(value, low, high):
    if isinstance(value, bool): return None
    try: value = float(value)
    except (TypeError, ValueError, OverflowError): return None
    return value if isfinite(value) and low <= value <= high else None


def indexed_temperature(command):
    """Presence of a heater T target, not a logical-material mapping."""
    return INDEXED_TOOL.search(command) is not None


class MotionContext:
    def __init__(self, snapshot=None):
        self.speed = 100.; self.saved_speed = None
        self.flows = {}; self.diameters = {}; self.volumetric = False
        self.nozzle = self.bed = self.chamber = None
        self.indexed_nozzles = {}; self.fans = {}; self.nozzle_mapping_unknown = False
        self.uncertain_recovery = set(); self.gaps = set(); self.invalid_dimensions = set()
        if snapshot:
            self.speed = finite(snapshot['speed'],0,1000); self.saved_speed = finite(snapshot['saved_speed'],0,1000)
            self.flows = {int(k):finite(v,0,1000) for k,v in snapshot['flows'].items()}
            self.diameters = {int(k):finite(v,.01,10) for k,v in snapshot['diameters'].items()}
            self.volumetric = snapshot['volumetric'] if isinstance(snapshot['volumetric'],bool) else None
            self.nozzle = finite(snapshot['nozzle'],0,600)
            self.bed = finite(snapshot['bed'],0,300); self.chamber = finite(snapshot['chamber'],0,300)
            self.indexed_nozzles = {int(k):finite(v,0,600) for k,v in snapshot['indexed_nozzles'].items()}
            self.fans = {int(k):finite(v,0,255) for k,v in snapshot['fans'].items()}
            self.nozzle_mapping_unknown = snapshot['nozzle_mapping_unknown']
            self.uncertain_recovery = set(snapshot['uncertain_recovery'])
            self.gaps = set(snapshot['gaps']); self.invalid_dimensions = set(snapshot['invalid_dimensions'])

    def snapshot(self):
        return deepcopy({'speed':self.speed, 'saved_speed':self.saved_speed, 'flows':self.flows,
            'diameters':self.diameters, 'volumetric':self.volumetric, 'nozzle':self.nozzle,
            'bed':self.bed, 'chamber':self.chamber, 'indexed_nozzles':self.indexed_nozzles,
            'fans':self.fans, 'nozzle_mapping_unknown':self.nozzle_mapping_unknown,
            'uncertain_recovery':sorted(self.uncertain_recovery), 'gaps':sorted(self.gaps),
            'invalid_dimensions':sorted(self.invalid_dimensions)})

    def tool_changed(self):
        self.nozzle = None; self.nozzle_mapping_unknown = True

    def dimension(self, name, value):
        valid = finite(value, .001 if name == 'height' else .02, 5)
        if valid is None: self.invalid_dimensions.add(name)
        else: self.invalid_dimensions.discard(name)
        return valid

    def macro(self):
        self.gaps.add('FIRMWARE_MACRO_UNRESOLVED')
        # A named firmware macro may change E origin, tool, units, retraction,
        # overrides and heaters. Later explicit commands restore their own
        # observations, but cannot establish the hidden extrusion history.
        self.speed = self.saved_speed = None
        self.flows.clear(); self.diameters.clear(); self.volumetric = None
        self.nozzle = self.bed = self.chamber = None
        self.indexed_nozzles.clear(); self.fans.clear()

    def command(self, code, command, tool, retract, scale=1):
        if code not in ('M104','M109','M140','M190','M141','M191','M200','M220','M221','M106','M107','G10','G11','M149'):
            return
        args = command[len(code):]
        fields = dict(PARAMETERS.findall(args))
        target = tool
        targeted = indexed_temperature(command)
        if targeted:
            value = finite(fields.get('T'), 0, 254)
            target = int(value) if value is not None and value.is_integer() else None
        if code in ('M104','M109','M140','M190','M141','M191'):
            value = fields.get('S', fields.get('R'))
            nozzle_variant = code in ('M104','M109') and any(key in fields for key in ('I','B','F'))
            if value is None and not nozzle_variant: return
            value = finite(value, 0, 600 if code in ('M104','M109') else 300)
            if code in ('M104','M109'):
                if nozzle_variant:
                    value = None; self.gaps.add('NOZZLE_COMMAND_VARIANT_UNRESOLVED')
                else:self.gaps.discard('NOZZLE_COMMAND_VARIANT_UNRESOLVED')
                if targeted:
                    if target is not None: self.indexed_nozzles[target] = value
                    self.nozzle_mapping_unknown = True
                else:
                    self.nozzle = value; self.nozzle_mapping_unknown = False
            elif code in ('M140','M190'): self.bed = value
            else: self.chamber = value
        elif code == 'M221':
            if 'S' not in args: return
            if target is None: self.gaps.add('FLOW_TOOL_TARGET_UNRESOLVED'); return
            value = finite(fields.get('S'), 0, 1000)
            if value != self.flows.get(target, 100.) and retract.get(target, 0) > 0:
                self.uncertain_recovery.add(target)
            self.flows[target] = value
        elif code == 'M200':
            if target is None: self.volumetric = None; return
            before = self.volumetric
            diameter = None
            if 'D' in args:
                diameter = finite(fields.get('D'), 0, 10)
                if diameter is None: self.volumetric = None
                elif diameter == 0: self.volumetric = False
                else:
                    self.diameters[target] = finite(diameter*float(scale),.01,10)
                    self.volumetric = True if self.diameters[target] is not None else None
            # Marlin's D0 disables volumetric E even when S1 is also supplied.
            if 'S' in args and not ('D' in args and diameter == 0):
                enabled = finite(fields.get('S'), 0, 1)
                self.volumetric = bool(enabled) if enabled in (0, 1) else None
            if self.volumetric != before:
                self.uncertain_recovery.update(key for key,debt in retract.items() if debt > 0)
        elif code == 'M220':
            # Back up the pre-command factor before S/R alter it.
            if 'B' in args: self.saved_speed = self.speed
            if 'S' in args: self.speed = finite(fields.get('S'), 0, 1000)
            if 'R' in args: self.speed = self.saved_speed
        elif code in ('M106','M107'):
            if code == 'M106' and any(key in fields for key in ('I','T')):
                self.gaps.add('FAN_COMMAND_VARIANT_UNRESOLVED'); self.fans[0] = None; return
            fan = finite(fields.get('P', 0), 0, 255)
            if fan is None or not fan.is_integer():
                self.gaps.add('FAN_TARGET_UNRESOLVED'); return
            self.fans[int(fan)] = 0. if code == 'M107' else finite(fields.get('S', 255), 0, 255)
            if fan == 0:self.gaps.discard('FAN_COMMAND_VARIANT_UNRESOLVED')
        elif code in ('G10','G11'):
            self.gaps.add('FIRMWARE_RETRACTION_UNRESOLVED')
        elif code == 'M149':
            if 'C' in args: self.gaps.discard('TEMPERATURE_UNIT_UNSUPPORTED')
            else:
                self.gaps.add('TEMPERATURE_UNIT_UNSUPPORTED')
                self.nozzle = self.bed = self.chamber = None

    def recovered(self, tool, retract):
        if retract.get(tool, 0) <= 0: self.uncertain_recovery.discard(tool)

    def observe(self, deposited, tool, feed, diameters, width, height, scale=1):
        gaps = set(self.gaps)
        width=finite(width,.02,5);height=finite(height,.001,5)
        if width is None or height is None:gaps.add('DECLARED_ROAD_DIMENSIONS_UNKNOWN')
        default_flow = None if gaps.intersection(('INITIAL_MOTION_CONTEXT_UNAVAILABLE','FIRMWARE_MACRO_UNRESOLVED')) else 100.
        flow = finite(self.flows.get(tool, default_flow), 0, 1000)
        speed_override = finite(self.speed, 0, 1000)
        feed = finite(feed, 0, 1e9)
        speed = feed/60*speed_override/100 if feed is not None and speed_override is not None else None
        if speed is None or speed <= 0: speed = None; gaps.add('COMMANDED_SPEED_UNKNOWN')
        if flow is None: gaps.add('FLOW_OVERRIDE_UNKNOWN')
        unit = 'UNKNOWN' if self.volumetric is None else 'VOLUME_MM3' if self.volumetric else 'FILAMENT_LENGTH_MM'
        diameter = self.diameters.get(tool)
        if diameter is None and 0 <= tool < len(diameters): diameter = finite(diameters[tool], .01, 10)
        raw = finite(deposited, 0, 1e100)
        if raw is not None and self.volumetric: raw *= float(scale)**2
        volume = None
        if unit == 'UNKNOWN': gaps.add('EXTRUSION_UNIT_UNKNOWN')
        elif raw == 0: volume = 0.
        elif raw is not None and flow is not None:
            if self.volumetric: volume = raw*flow/100
            elif diameter is not None: volume = raw*pi*(diameter/2)**2*flow/100
        if unit == 'FILAMENT_LENGTH_MM' and diameter is None and raw:
            gaps.add('FILAMENT_DIAMETER_UNKNOWN')
        if tool in self.uncertain_recovery:
            gaps.add('RETRACTION_CONTEXT_CHANGED'); volume = None
        if 'FIRMWARE_RETRACTION_UNRESOLVED' in gaps: volume = None
        if 'FIRMWARE_MACRO_UNRESOLVED' in gaps: volume = None
        if 'FLOW_TOOL_TARGET_UNRESOLVED' in gaps:volume = None
        if volume is not None and not isfinite(volume): volume = None; gaps.add('COMMAND_VOLUME_NONFINITE')
        if self.nozzle_mapping_unknown: gaps.add('NOZZLE_TOOL_HEATER_MAPPING_UNVERIFIED')
        if self.invalid_dimensions: gaps.add('INVALID_ROAD_DIMENSIONS')
        if 0 in self.fans and self.fans[0] is None:gaps.add('PART_COOLING_FAN_COMMAND_INVALID')
        return MappingProxyType({'version':VERSION, 'feedrate_mm_min':feed,
            'commanded_speed_mm_s':speed, 'speed_override_percent':speed_override,
            'filament_diameter_mm':diameter, 'extrusion_unit':unit, 'raw_deposited_e':raw,
            'commanded_volume_mm3':volume,
            'volume_basis':'POST_EXPLICIT_RETRACTION_RECOVERY_E_WITH_RUNTIME_FLOW_OVERRIDE' if volume is not None else 'UNRESOLVED_COMMANDED_VOLUME',
            'nozzle_setpoint_c':None if 'TEMPERATURE_UNIT_UNSUPPORTED' in gaps else self.nozzle,
            'bed_setpoint_c':None if 'TEMPERATURE_UNIT_UNSUPPORTED' in gaps else self.bed,
            'chamber_setpoint_c':None if 'TEMPERATURE_UNIT_UNSUPPORTED' in gaps else self.chamber,
            'part_cooling_fan_pwm':self.fans.get(0), 'flow_override_percent':flow,
            'line_width_mm':width, 'layer_height_mm':height, 'assessment_gaps':tuple(sorted(gaps))})
