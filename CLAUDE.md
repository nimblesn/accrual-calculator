# CLAUDE.md

이 프로젝트는 채권 Accrual(경과이자) / 상각 계산 프로그램을 Python으로 구현하는 신규 프로젝트입니다. 아직 코드는 없으며, 구현에 들어가기 전 스펙 문서만 존재하는 단계입니다.

## 스펙 문서

- 전체 요구사항은 [accrual-spec.md](accrual-spec.md) (문서 상태: **v0.4**) 를 따릅니다.
- 표기 규칙: `[확정]` = 확정된 요구사항, `[가정]` = 임시 가정(검토 필요), `[확인필요]` = 담당자 확정 전에는 구현 금지.
- **`[확인필요]` 항목은 임의로 가정하여 구현하지 말고 반드시 사용자에게 질문할 것.** (스펙 14장 원칙)
- v0.3의 13장 미결사항 16건은 스펙 0장("v0.3 → v0.4 확정 로그")에 정리된 대로 모두 확정되었다. 이 중 **3건(콜/풋 옵션부 채권, Floating 후행 복리, Floating lookback)은 "지원 필요"로 범위는 확장되었지만 상세 요구사항이 없어 구현 보류 중**이며, 스펙 15장에 정리되어 있다. 이 3건은 14장 구현 순서에 포함하지 않는다.
- 구현 중 세부 디테일 수준에서 새로 발견되는 `[가정]`/`[확인필요]`(스펙 13장에 목록)는 임의로 가정하지 말고 질문할 것.

## 핵심 기술 제약 (스펙 3~4장 요약)

- Python 3.12+, 패키지/가상환경 관리는 `uv` [확정]. 테스트는 pytest.
- 날짜는 `datetime.date`만 사용 (`datetime` 금지).
- **금액·이율 계산에 `float` 금지 — 전부 `decimal.Decimal`.** `Decimal`은 문자열/정수로만 생성 (`Decimal("0.05")`, `Decimal(0.05)` 금지).
- numpy/pandas/scipy 등 float 기반 연산을 계산 경로에 사용하지 않음. 파일 입력은 문자열로 읽어 `Decimal`로 변환.
- 값 객체는 `@dataclass(frozen=True)` (불변). 계산 로직은 순수 함수로 입출력과 분리.
- 반올림은 `RoundingPolicy` 한 곳에서만 수행 (`Decimal.quantize`). 내장 `round()` 금지.
- 모든 계산 로직은 단위 테스트 동반.

## 모듈 구조 (스펙 11장)

```
accrual/
 ├─ models/      # Bond, AccrualPeriod, CashFlow, Money
 ├─ daycount/    # DayCountConvention (ABC) 전략 패턴
 ├─ schedule/    # 이표 스케줄 생성
 ├─ accrual/     # 유형별 경과이자 계산
 ├─ amortization/# 유효이자율법 / 정액법 상각, EIR 솔버
 ├─ rounding.py  # RoundingPolicy
 └─ io/          # CSV 로더/라이터, 로딩 검증 (계산 로직과 분리)
tests/
```

## 구현 순서 (스펙 14장)

각 단계마다 테스트 통과 후 커밋:
1. `RoundingPolicy`, `Money`
2. Day Count 구현체 + 단위 테스트 (스펙 5.4 예시)
3. 이표 스케줄 생성
4. Fixed rate 경과이자
5. EIR 솔버 + Fixed rate 상각, Zero coupon 정액 상각
6. Floating rate (후행 복리/lookback **제외** — 스펙 15장 확장 과제)
7. MBS/ABS (현금흐름 추정 변경 시 기본값 PROSPECTIVE)
8. TIPS
9. 입출력 계층(CSV, DB/API로 교체 가능한 인터페이스로 설계) + 로딩 검증
10. 대량 샘플 비교 검증

콜/풋 옵션부 채권은 이번 구현 순서에 포함되지 않는다 (스펙 15.1, 요구사항 미정).

## 테스트 원칙 (스펙 12장)

- 기대값은 구현 코드로 만들지 않음 — 엑셀/기존 시스템/회계팀 확인값 등 독립 출처만 사용하고, 각 케이스에 출처를 기록.
- 금액 비교는 `Decimal` 정확 일치 (`pytest.approx` 금지).
