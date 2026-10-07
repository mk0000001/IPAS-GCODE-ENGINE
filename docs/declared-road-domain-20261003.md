# Declared road dimensions and Cura auxiliary roles

## 한국어

기존 G-code 코퍼스의 완료된 부분을 원본 SHA와 전체 바이트로 재검사해, 명시된 0.0045–0.0157995 mm 높이가 공정 문맥의 0.02 mm 하한에서 손실되는 사례를 확인했습니다. 별도의 12개 실제 원본 재현은 ironing 경로의 0.0045/0.0075 mm 높이에서 같은 문제를 확인했습니다. 이는 슬라이서 선언값이며 실제 비드나 층접합 측정값이 아닙니다. 전체 코퍼스 검증 완료를 뜻하지 않습니다.

문맥·순차 스캔·체크포인트는 높이 0.001–5 mm, 폭 0.02–5 mm를 일관되게 보존합니다. 0·음수·비유한 수와 범위 밖의 선언은 유효한 이전 치수처럼 취급하지 않습니다. 선택적 문맥 없이 반환하는 기본 분석은 높이 변경으로 강도 배율을 얻지 않습니다.

[Cura의 공식 feature 표기](https://github.com/Ultimaker/Cura/blob/main/plugins/GCodeReader/FlavorParser.py)에 있는 정확한 `PRIME-TOWER`는 기존 `prime tower`와 같이 모델 경로 집계에서 제외합니다. 필라멘트 소비량과 원본 모션 콜백은 유지합니다. 유사한 임의 문자열을 일괄 치환하지 않습니다.

공개 Python 시험 70개가 통과했습니다. 새 회귀 시험 5개는 양의 미세 높이 문맥, 비정상 치수, 기본 분석과 observer 분석의 일치, 체크포인트 재개와 prime-tower 제외를 확인합니다. 네이티브 바이너리는 변경된 소스로 다시 빌드해야 합니다. 과거 raw 캐시는 선택 원본의 전체 바이트·SHA와 영향받는 feature 표기를 감사한 뒤에만 재사용할 수 있습니다.

릴리스 **v0.28.0**의 같은 70개 시험은 새 Windows 네이티브 빌드와 실제 운영 Linux 이미지의 네이티브 모듈에서도 통과했습니다. 운영 호스트 `0.5.18-corpus-thin-road`와 강도 `0.22.0`은 네 개 서비스의 이미지·소스 해시·버전·네이티브 로딩을 확인했습니다. 원본 자료의 전체 계산 여부는 [통합 검증 기록](https://github.com/mk0000001/IPAS-STRENGTH-ENGINE/blob/master/docs/full-corpus-validation-20261003.md)의 별도 대조 결과로 판단합니다. 소프트웨어 시험은 실제 파단하중 검증이 아닙니다.

## English

A completed subset of the source corpus exposed explicit heights of 0.0045–0.0157995 mm lost at the previous 0.02 mm context floor. Twelve separately replayed real sources reproduced that loss for declared ironing heights of 0.0045/0.0075 mm. These are slicer declarations, not measured bead or weld dimensions. This finding does not establish completion of the whole corpus.

Context, sequential fallback and checkpoint fallback retain heights in 0.001–5 mm and widths in 0.02–5 mm. Zero, negative, non-finite and out-of-domain declarations remain invalid. Default analysis without an observer does not acquire any strength multiplier.

The exact Cura `PRIME-TOWER` alias is excluded from model deposition accounting alongside `prime tower`. Filament consumption and source motion callbacks remain available. No blanket normalization of similar feature names is applied.

All 70 public Python tests passed. Five new regressions cover positive thin declarations, invalid dimensions, observer/default result parity, resumed checkpoints and auxiliary-tower exclusion. Native extensions require rebuilding. Reusing older raw results requires whole-stream byte/SHA verification and source-feature impact checks.

The same 70 tests for release **v0.28.0** passed on the rebuilt Windows native modules and the actual production Linux image. Host `0.5.18-corpus-thin-road` and strength `0.22.0` were checked across four services for image, source hashes, version and native loading. Whole-corpus calculation coverage is reconciled separately in the [integrated validation record](https://github.com/mk0000001/IPAS-STRENGTH-ENGINE/blob/master/docs/full-corpus-validation-20261003.md). These software tests do not validate physical failure loads.
