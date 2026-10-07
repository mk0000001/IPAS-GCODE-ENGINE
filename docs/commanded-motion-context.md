# Commanded motion context

## 한국어

선택적 `motion_context_callback`은 원본 모션당 한 번 명령 상태를 전달하며 기존 7인자 모션 콜백은 유지합니다. M200/M220/M221, 명시적 리트랙션 회복, 온도·팬과 치수를 별도 상태로 보존합니다. 체적/필라멘트 길이와 슬라이서 설정 유량을 구별해 유량을 중복 적용하지 않습니다. 불명 매크로·히터 매핑은 실측값처럼 확정하지 않으며 M200 D0은 S1보다 우선합니다.

명령 온도·속도는 실제 접합 온도·가속을 포함한 실속도가 아닙니다. 체적이 확인되지 않으면 `None`으로 남깁니다. 곡선은 원본 한 번의 콜백으로 전달하며 순차/체크포인트 상태를 유지합니다. 기본 스캔에서는 선택적 수집을 하지 않으므로 새 문맥 생성 비용을 발생시키지 않습니다.

2026-10-03 릴리스 **v0.27.0**: 코드 소스 `5e7df32eb7870a7947efcf3f20dc42b35edd7133`. 실제 배포 이미지에서 네이티브 스캐너를 사용한 공개 시험 65개 모두 통과했습니다. 강도 v0.19.0과 통합 앱 v0.5.14-process-context에 연결해 4개 운영 서비스의 이미지·소스·버전을 확인했습니다. [통합 검증 및 실증 한계](https://github.com/mk0000001/IPAS-STRENGTH-ENGINE/blob/master/docs/process-aware-weakness-validation-20261003.md).

## English

`scan(..., motion_context_callback=callback)` optionally emits one observed context for each original motion with a valid path. Pure stationary E/retraction moves update modal state but do not emit a path. It works alongside the unchanged seven-argument `motion_callback`.

```python
def observe(layer, before, after, feature, tool, deposited, arc, context):
    # Consume coordinates now, or copy them when retaining beyond this callback.
    # context itself is an immutable mapping; assessment_gaps is an immutable tuple.
    print(context['commanded_volume_mm3'])
```

Arcs provide analytic length and geometry even when only the context observer is supplied. An arc receives one context, before host chording. Allocate its volume once across chord/crop segments; do not attach the entire arc volume to each chord. Stationary retract/recovery and pure E prime never create a product road.

The optional helper is instantiated only for context observers. Default scanning retains its raw-E, raw-feedrate analysis and existing results; context volume does not silently replace legacy `filament_mm`, layer volume or global flow metrics. No temperature, fan, flow or contact strength multiplier is applied.

| Key | Meaning |
| --- | --- |
| version | `GCODE_COMMANDED_PROCESS_CONTEXT_V1` |
| feedrate_mm_min | Modal F normalized to mm/min; zero/missing does not establish moving speed |
| commanded_speed_mm_s | Nominal F/60 with observed M220 factor; excludes acceleration, planner limits and waits |
| speed_override_percent | Conventional M220 S factor; B backs up and R restores |
| filament_diameter_mm | Last usable targeted M200 D, otherwise the active tool's configured diameter; no invented 1.75 mm default |
| extrusion_unit | `FILAMENT_LENGTH_MM`, `VOLUME_MM3`, or `UNKNOWN` |
| raw_deposited_e | Legacy positive E after explicit negative-E recovery, normalized to the named E unit; never a sensor measurement |
| commanded_volume_mm3 | E volume with runtime M221 once, or null when unresolved |
| volume_basis | `POST_EXPLICIT_RETRACTION_RECOVERY_E_WITH_RUNTIME_FLOW_OVERRIDE` or `UNRESOLVED_COMMANDED_VOLUME` |
| nozzle_setpoint_c | Last unindexed active nozzle command, subject to tool/heater mapping gaps |
| bed_setpoint_c, chamber_setpoint_c | Observed M140/M190 and M141/M191 commands; configuration and macro parameters remain separate |
| part_cooling_fan_pwm | Conventional default/index-0 M106/M107 PWM (0-255); other fan ids do not overwrite it |
| flow_override_percent | Conventional targeted M221 S, initially 100 within the modeled file state |
| line_width_mm, layer_height_mm | Valid modal declarations, not measured bead geometry |
| assessment_gaps | Immutable reasons preventing a complete interpretation |

M200 supports D/S/T. Positive D enables volumetric mode unless S0 overrides it; D0/S0 disable mode while retaining a prior usable diameter. D0 also takes precedence over a simultaneous S1. The mode is global, while diameters retain their extruder targets. Cubic inch E is normalized to cubic mm. M221 percentages retain extruder targets. These conventional command semantics describe commanded observations, not guaranteed firmware execution.

Slicer `filament_flow_ratio` and `extrusion_multiplier` are already represented by generated E and are never multiplied into context volume again. Runtime M221 is separate. If a flow override or extrusion unit changes while explicit retraction debt remains, volume is null through the affected recovery motion. Later motions can regain known command-volume context once that debt is cleared. Firmware G10/G11 retraction is explicitly unresolved.

No numeric equality between logical T/material ids and physical M104/M109 heater ids is assumed. An indexed heater command is retained in the helper checkpoint but does not overwrite the last unindexed active command. It adds `NOZZLE_TOOL_HEATER_MAPPING_UNVERIFIED`. A logical tool change clears active nozzle context until a new unindexed command. Preset/autotemperature variants, unsupported temperature units and firmware macros carry gaps rather than inferred local values. Conventional fan index 0 is the documented observation basis; a separate printer mapping is needed to verify physical fan role.

Unrecognized named firmware commands, including `START_PRINT`, `PRINT_START` and `SET_*`, invalidate prior override, extrusion-mode, fan and thermal observations. Later supported commands establish their own new facts. `FIRMWARE_MACRO_UNRESOLVED` continues to withhold command volume because partial resets cannot recover a hidden E origin, tool change or retraction history. An unknown thermal field alone does not withhold volume.

The default process metrics now preserve all nozzle min/max command values while excluding targeted heater commands from the active unindexed deposition temperature. Unknown active/deposition last values remain unknown across chunk merging. A historical min/max range is not a current tool's verified thermal state.

For layer-aligned context scans call `segment_checkpoints(..., motion_context=True)`, then pass each returned state to `scan(..., initial_state=state, motion_context_callback=callback)`. This stores the optional command state including M220 backup, E mode, target diameters, flow overrides, fans, heater commands, and unresolved recovery. Resuming a legacy checkpoint without that state adds `INITIAL_MOTION_CONTEXT_UNAVAILABLE` and withholds unknown mode/flow/speed assumptions.

Diameter comments that appear only after motion are not retroactively treated as observed earlier in time. A host may seed same-source verified configuration before scanning or resolve a bounded aggregate after finalization, with its provenance retained. No extra source scan is performed by this API.

Focused synthetic regressions cover compatibility, immutability, unindexed/indexed temperature separation, unknown last preservation, M200/M220/M221 semantics, fan ids/variants, invalid values, explicit recovery, uncertain recovery, optional checkpoint parity and full-circle arcs. Run `python -m unittest discover -s tests`.

Release **v0.27.0**, 2026-10-03, source `5e7df32eb7870a7947efcf3f20dc42b35edd7133`: all 65 public tests passed with the production native scanner. Integration with strength v0.19.0 and host v0.5.14-process-context was deployed and source/image/version identity checked across four services. See the [integration receipts and empirical limits](https://github.com/mk0000001/IPAS-STRENGTH-ENGINE/blob/master/docs/process-aware-weakness-validation-20261003.md).
