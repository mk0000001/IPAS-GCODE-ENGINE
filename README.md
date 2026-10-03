# Print G-code Engine

[한국어](#한국어) · [English](#english)

## 한국어

릴리스 **v0.28.0** · 코드 개정 28회(최초 등록 이후 업데이트 27회). [커밋 집계](VERSION_HISTORY.json).

엔진 패키지를 변경한 도달 가능한 비병합 커밋을 센다. 병합된 개발 이력은 포함하고 문서 전용·시험 전용·호스트 앱 변경과 자동 생성 `_version.py`는 제외한다. 개정 수는 기능 수나 정확도 검증 횟수가 아니다. 버전 규칙은 `0.<코드 개정 수>.<릴리스 메타데이터 수정>`이며 과거 결과에 버전이 기록되지 않았다면 미상으로 남긴다.

독립 실행형 G-code·슬라이스 3MF 분석기다. `print_gcode_engine.analyzer.analyze(path)`는 슬라이서 메타데이터, 활성 소재 사용량, 공정 통계와 경로 방향 정보를 반환한다. 대용량 순차 스트림과 ZIP 멤버 스트리밍을 지원하며 외부 G-code는 신뢰되지 않은 입력으로 취급한다. 강도와 가격은 별도 엔진이 결정한다.

### 분석 범위와 정확성

- H2C는 실행 대상 플레이트와 활성 필라멘트 XML을 사용한다. 미리보기 개수나 전체 설정 소재 수를 사용량으로 세지 않는다. 필라멘트 ID·노즐·물리 압출기를 구분하며 조건부 AMS 주석만으로 설치 장비를 확정하지 않는다.
- StealthChanger/Orca의 프린터 프로필과 Klipper 시작 주석을 인식한다. 활성 프로필만 나열된 경우 비연속 T 도구 ID를 해당 프로필 순서와 연결한다.
- 도구·좌표·압출·리트랙션 부채와 Decimal50 정밀도를 보존한다. 체크포인트 상태는 2/4/6분할의 전체 접두 스캔과 비교한다. 상대 이동·상대 압출은 반복 생략 대상이 아니다.
- 절대 좌표의 불필요한 중간 변환을 지연하고, 동일 조건의 연속 절대 G0/G1·일반 공백 구분 명령·직전 압출 문자열을 최적화한다. 축약 명령과 서브코드는 기존 정규식 경로를 유지한다. 정밀도 축소나 fast-math는 사용하지 않는다.
- 유량 배율, 상하단 셸, 최소 레이어 시간, 냉각 설정은 파일에 기록된 설정값이다. 실제 공극률·접합면적·국소 열이력 측정값이 아니다.
- `scan(..., motion_callback=callback)`은 분석기와 같은 모달 상태를 사용하는 시각화 이동을 전달한다. 콜백 이후 좌표를 보관하려면 복사해야 한다. 정지 상태의 리트랙션 복구는 모델 면적을 만들지 않는다.
- 선택적 `motion_context_callback`은 원본 이동마다 E 단위·명령 체적·온도·팬·속도·유량 배율·선폭·층높이와 불확실성을 불변 상태로 전달한다. 강도 배율이나 실측값이 아니다. [콜백 계약](docs/commanded-motion-context.md).

### 실행과 병렬 처리

```sh
python -m unittest discover -s tests
```

선택적 네이티브 빌드는 C 컴파일러가 있는 CPython에서 `Cython==3.1.3 setuptools==80.9.0 wheel==0.45.1`을 설치한 다음 `python build_native.py build_ext --inplace -j 2`로 실행한다. 대상 Python 버전·플랫폼이 바뀌면 다시 빌드해야 하며 `.py` 구현은 이식 가능한 대체 경로로 남는다.

기본은 직렬 처리다. `GCODE_PARALLEL_WORKERS=4`는 8 MiB 이상이며 제한된 샘플에서 아크가 충분한 파일의 병렬 처리를 활성화한다. 컴파일된 스캐너는 128 MiB 이상 조밀한 이동 파일도 대상으로 삼는다. 작은 선형 파일이나 레이어 마커가 부족한 파일은 직렬 처리한다. 3MF에는 해제한 G-code를 담을 수 있는 쓰기 가능한 `GCODE_SCRATCH_DIR`가 필요하며 임시 멤버는 이후 삭제한다. 실제 속도는 파일별로 측정해야 한다.

진행률은 약 250 ms 간격의 시간 기반 알림이다. 소비 측 콜백은 분석을 막지 않아야 한다. 잔여 시간에는 가중 표시 퍼센트 대신 `phase_bytes_processed`, `phase_total_bytes`, `eta_final_phase`를 사용하고 `eta_context`로 아카이브 멤버를 구분한다. 준비 단계나 마지막이 아닌 플레이트를 작업 전체 완료로 표시하지 않는다.

체크포인트는 레이어 경계를 찾을 때마다 완료된 구간을 즉시 worker에 전달한다. 파일 전체의 사전 스캔이 끝날 때까지 worker를 기다리게 하지 않는다. 32 MiB 이상 병렬 대상은 기본적으로 worker 수의 4배 구간(최대 32개)으로 나누되, 모달 상태와 결과 병합 순서는 보존한다. 진행 알림 큐와 worker 수를 제한하며 취소·소비자 오류는 실행 중인 자식에게 전달한다. `analysis_execution`의 `chunks`와 `pipelined`는 실행 방식에 관한 정보로, 품질 점수가 아니다.

관련 자료: [연구 근거](https://github.com/mk0000001/print-strength-engine/blob/master/docs/research-evidence.md), [시스템 검증 범위](https://github.com/mk0000001/print-strength-engine/blob/master/docs/system-validation.md).

v0.28의 선언 높이·Cura 보조 경로 수정과 네이티브 검증은 [릴리스 근거](docs/declared-road-domain-20261003.md)에 정리했습니다.

---

## English

Release: **v0.28.0** · 28 recorded code revisions (27 updates after initial import). [Commit ledger](VERSION_HISTORY.json).

Count includes reachable non-merge commits touching the engine package, including merged development history; excludes documentation-only, tests-only, host-app changes and generated _version.py. It counts commits, not individual features or validated accuracy. Version convention: 0.<code revision count>.<release metadata fix>. Past results without a recorded version remain unknown.


The checkpoint pass skips immediately repeated absolute G0/G1 motions with the same guard as the scanner, recognizes common whitespace-delimited motion commands without a regex, and caches the last exact extrusion literal. Unit multiplication and ordered Decimal arithmetic remain unchanged; the cache is bounded to one value. Compact commands and subcodes retain the regex path. Relative motion and extrusion are never skipped.

Strength-context parsing retains filament flow/extrusion multipliers, top/bottom shell counts, minimum-layer-time and fan settings from G-code or 3MF metadata. These are slicer settings; they do not measure local thermal return time, porosity or bonded contact area.

The modal checkpoint pass defers absolute XYZ and feed conversion until a chunk boundary or a relative-coordinate, origin-reset, or unit-change command needs numeric state. Superseded absolute positions are not repeatedly converted. Decimal50 state precision, relative movement, unit scaling, tool state and retraction debt remain exact; there is no reduced-precision fast path. Checkpoint states are regression-tested against complete prefix scans for 2/4/6 partitions.

`scan(..., motion_callback=callback)` optionally streams visual motions as `(layer_number, before_xyz, after_xyz, feature, tool, deposited_mm, arc)`. The callback shares the analyzer's modal coordinates and retraction accounting; copy coordinates if retaining them beyond the call. Arc geometry is included only for observers. Stationary unretraction does not create a model-layer area entry, including tiny residual extrusion before a support feature change.

Optional `motion_context_callback` preserves that callback and adds an immutable per-original-motion observation of E units, commanded volume, temperatures, fan, speed/flow overrides, declared dimensions and explicit interpretation gaps. It does not measure deposition or apply strength multipliers. See the [context contract](docs/commanded-motion-context.md).

Optional native build (CPython with a C compiler): install `Cython==3.1.3 setuptools==80.9.0 wheel==0.45.1`, then run `python build_native.py build_ext --inplace -j 2` from this repository. Scanner, process histograms, arc geometry and checkpoint passes compile ahead of time. The `.py` files remain the portable fallback. Decimal arithmetic and analysis rules are preserved; no fast-math flags or reduced-precision coordinates are used. Compiled extensions must be rebuilt for the target Python version and platform.

Adaptive parallel mode: set `GCODE_PARALLEL_WORKERS=4` to opt in for files of at least 8 MiB whose bounded sample contains substantial arc motion. A compiled scanner also enables parallel processing for dense motion files of at least 128 MiB. Smaller linear-heavy files retain the serial path. Sliced 3MF also requires a writable `GCODE_SCRATCH_DIR` with room for its uncompressed G-code; the temporary member is removed afterward. Files without sufficient layer markers fall back to serial scanning. Default is serial. Speed varies by workload; benchmark before enabling. Chunk results are combined with time-weighted histograms, modal checkpoints and ordered metadata. This is not an 80% CPU utilization guarantee.

The checkpoint pass submits each completed layer-aligned segment immediately, so workers can run before the entire prepass finishes. Eligible parallel files of at least 32 MiB default to four segments per worker, capped at 32 segments, while modal state and ordered result merging are retained. Worker count and progress queues are bounded; cancellation and consumer failures signal active children. The `chunks` and `pipelined` fields in `analysis_execution` describe execution, not analysis quality.

Progress is time-based (approximately 250 ms from the scanner/checkpoint loop), independent of crossing a byte threshold. Progress consumers should avoid blocking the analyzer; final completion always reports the full byte count.

Parallel and archive progress also expose `phase_bytes_processed`, `phase_total_bytes`, and `eta_final_phase` where needed. Use these for remaining-time estimates rather than the weighted display percentage. Preparation and nonfinal plates must not be presented as the end of the entire job; `eta_context` distinguishes archive members.

Standalone bounded-memory G-code and sliced-3MF analyzer. `print_gcode_engine.analyzer.analyze(path)` returns slicer metadata, active material usage, process metrics, and toolpath orientation. Supports large sequential streams and ZIP member streaming. External G-code remains untrusted for production.

StealthChanger/Orca tool profiles are recognized from `printer_settings_id` and Klipper start comments; sparse T tool IDs are mapped to profile ordinals when only active profiles are listed. This package does not make strength or pricing decisions.

H2C sliced-3MF analysis uses the selected executable plate and active filament XML records, rather than counting plate previews or all configured materials. Raw H2C headers retain multicolor mode settings. Filament IDs, nozzle records and physical extruders are distinct concepts; conditional AMS comments do not prove an installed AMS inventory.

Optional native Cython compilation and layer-aligned multiprocessing preserve modal state (including geometry width and height), tool/retraction state and ordered results. Parallelism is enabled selectively because checkpoint overhead can outweigh gains on smaller files. Trailing filament diameter settings are reconciled into deposited-volume profiles.

Run `python -m unittest discover -s tests`. `build_native.py` optionally compiles the scanner and related modules with Cython; the same suite can be run against the compiled package.

The v0.28 declared-height and Cura auxiliary-role fixes, including native release checks, are documented in [release evidence](docs/declared-road-domain-20261003.md).
