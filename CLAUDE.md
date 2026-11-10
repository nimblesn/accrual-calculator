# CLAUDE.md

이 프로젝트는 채권 Accrual(경과이자) / 상각 계산 프로그램을 Python으로 구현한 프로젝트입니다. 스펙 14장의 구현 순서 1~10단계가 모두 구현되어 있으며, 배치 CLI(`python -m accrual`)로 실행합니다. 신규 기능이나 수정은 아래 원칙을 따릅니다.

## 스펙 문서

- 전체 요구사항은 [accrual-spec.md](accrual-spec.md) (문서 상태: **v0.4**) 를 따릅니다.
- 표기 규칙: `[확정]` = 확정된 요구사항, `[가정]` = 임시 가정(검토 필요), `[확인필요]` = 담당자 확정 전에는 구현 금지.
- **`[확인필요]` 항목은 임의로 가정하여 구현하지 말고 반드시 사용자에게 질문할 것.** (스펙 14장 원칙)
- v0.3의 13장 미결사항 16건은 스펙 0장("v0.3 → v0.4 확정 로그")에 정리된 대로 모두 확정되었다. 이 중 **3건(콜/풋 옵션부 채권, Floating 후행 복리, Floating lookback)은 "지원 필요"로 범위는 확장되었지만 상세 요구사항이 없어 구현 보류 중**이며, 스펙 15장에 정리되어 있다. 이 3건은 구현하지 않는다.
- 구현 중 세부 디테일 수준에서 새로 발견되는 `[가정]`/`[확인필요]`(스펙 13장에 목록)는 임의로 가정하지 말고 질문할 것.

## 실행과 테스트

```
uv sync                                  # 의존성 설치 (dev: pytest)
uv run pytest                            # 전체 테스트 (tests/ 하위, 현재 205개)
uv run python -m accrual <input_dir> --calc-end YYYY-MM-DD --output <out.csv> \
    [--projection-change PROSPECTIVE|CATCH_UP] [--snapshot-dates YYYY-MM-DD,...]
```

- 입력은 `security_master.csv`, `trades.csv` 등 CSV 파일을 한 디렉터리에 둡니다. 전체 샘플 입력은 `samples/`에, `io/`에는 `security_master.csv`와 `trades.csv`만 있습니다.
- 출력 옆에 `cash_schedule.csv`가 함께 생성됩니다. `--snapshot-dates`를 주면 `snapshot.csv`도 생성됩니다.
- 입력 검증에 실패하면 출력 파일을 만들지 않고 오류를 보고합니다.

## 핵심 기술 제약 (스펙 3~4장 요약)

- Python 3.12+, 패키지/가상환경 관리는 `uv` [확정]. 테스트는 pytest.
- 날짜는 `datetime.date`만 사용 (`datetime` 금지).
- **금액·이율 계산에 `float` 금지 — 전부 `decimal.Decimal`.** `Decimal`은 문자열/정수로만 생성 (`Decimal("0.05")`, `Decimal(0.05)` 금지).
- numpy/pandas/scipy 등 float 기반 연산을 계산 경로에 사용하지 않음. 파일 입력은 문자열로 읽어 `Decimal`로 변환.
- 값 객체는 `@dataclass(frozen=True)` (불변). 계산 로직은 순수 함수로 입출력과 분리.
- 반올림은 `RoundingPolicy` 한 곳에서만 수행 (`Decimal.quantize`). 내장 `round()` 금지.
- 모든 계산 로직은 단위 테스트 동반.

## 모듈 구조

스펙 11장의 구조를 따르되, 실제 코드는 `src/` 레이아웃이며 배치와 처분 처리를 위한 모듈이 추가되어 있습니다.

```
src/accrual/
 ├─ __main__.py          # CLI 진입점 (python -m accrual)
 ├─ batch.py             # 배치 흐름: lot별 상각 실행, 처분 반영, CSV 출력, 스냅샷
 ├─ calendar.py          # 영업일 조정과 현금 지급일
 ├─ disposal.py          # 매도 시 FIFO 배분 (Allocation)
 ├─ rounding.py          # RoundingPolicy
 ├─ models/
 │   ├─ bond.py          # FixedRateBond, FloatingRateBond, PassThroughBond(MBS/ABS), TipsBond
 │   ├─ period.py        # AccrualPeriod, CashFlow, ProjectionVersion
 │   ├─ result.py        # AmortizationResult, AmortizationRow
 │   └─ money.py         # Money
 ├─ daycount/
 │   ├─ base.py          # DayCountConvention (ABC)
 │   ├─ types.py         # 규약 코드 → 구현체 레지스트리
 │   └─ conventions.py   # 규약별 구현체
 ├─ schedule/
 │   └─ coupon_schedule.py  # 이표 스케줄 생성
 ├─ accrual/
 │   ├─ accrued_interest.py # Fixed rate 경과이자, 일별 발생액
 │   ├─ floating.py         # Floating 금리 적용 경과이자
 │   ├─ pass_through.py     # MBS/ABS 경과이자 (풀팩터 반영)
 │   └─ tips.py             # TIPS 경과이자와 물가 보정
 ├─ amortization/
 │   ├─ effective_interest.py # 고정·변동 금리 유효이자율법
 │   ├─ eir_solver.py         # EIR 수치해 (Newton-Raphson, 이분법 fallback, Decimal)
 │   ├─ straight_line.py      # Zero coupon 정액법
 │   ├─ pass_through.py       # MBS/ABS 상각 (PROSPECTIVE / CATCH_UP)
 │   └─ tips.py               # TIPS 상각
 └─ io/
     ├─ loaders.py       # CSV 로더, 입력 객체 구성 (계산 로직과 분리)
     └─ parsing.py       # 문자열 → Decimal/date 변환, 검증 오류 타입
tests/                   # pytest, 패키지 구조와 동일 (accrual/, amortization/, batch/, io/ 등)
```

설계 원칙: Day Count와 채권 유형은 전략 패턴(ABC + 레지스트리)으로 분리하여 신규 추가 시 기존 코드를 수정하지 않는다.

## 구현 현황 (스펙 14장 기준)

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | `RoundingPolicy`, `Money` | 완료 |
| 2 | Day Count 구현체 + 단위 테스트 (5.4 예시, C30/360 제외) | 완료 |
| 3 | 이표 스케줄 생성 | 완료 |
| 4 | Fixed rate 경과이자 | 완료 |
| 5 | EIR 솔버 + Fixed rate 상각, Zero coupon 정액 상각 | 완료 |
| 6 | Floating rate (후행 복리/lookback 제외) | 완료 |
| 7 | MBS/ABS (PROSPECTIVE 기본값, CATCH_UP 선택) | 완료 |
| 8 | TIPS | 완료 |
| 9 | CSV 입출력, 로딩 검증(10.8), 배치 처리, 영업일·매도·이월 잔액 | 완료 |
| 10 | 대량 샘플 비교 검증 | 완료 (샘플 배치 테스트 포함) |

- 콜/풋 옵션부 채권, Floating 후행 복리, Floating lookback은 스펙 15장 확장 과제로 구현하지 않습니다.
- 새 기능을 추가할 때는 이 표를 함께 갱신합니다.

## 테스트 원칙 (스펙 12장)

- 기대값은 구현 코드로 만들지 않음 — 엑셀/기존 시스템/회계팀 확인값 등 독립 출처만 사용하고, 각 케이스에 출처를 기록.
- 금액 비교는 `Decimal` 정확 일치 (`pytest.approx` 금지).
- 불변식(스펙 12.4)은 자동 검증 대상이다: 구간 일별 경과이자 합 = 이표 이자, 만기 상각후원가 = 상환 원금, 일별 상각액 합 = 만기 상각후원가 − 취득 상각후원가.
