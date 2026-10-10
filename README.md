# 채권 Accrual 계산 프로그램

채권별 **경과이자(Accrued Interest)** 와 **할인/할증 상각(유효이자율법)** 을 일자 단위로 계산하는 Python 프로그램입니다.

## 문서

| 문서 | 내용 |
|---|---|
| [accrual-spec.md](accrual-spec.md) | 전체 요구사항 스펙 (v0.4) |
| [CLAUDE.md](CLAUDE.md) | Claude Code 작업 지침 (기술 제약, 구현 순서, 테스트 원칙) |

표기 규칙 (스펙 전반):
- `[확정]` — 확정된 요구사항
- `[가정]` — 임시 가정 (검토 필요)
- `[확인필요]` — 담당자 확정 전에는 구현 금지

## 지원 범위

- **채권 유형**: Fixed rate bond, Floating rate bond, MBS, ABS, TIPS
- **계산 대상**: 경과이자, 할인/할증 상각액 (유효이자율법. 단 Zero coupon은 정액법)
- **제외**: 세금(세전 기준), 환율 환산, 콜/풋 옵션부 채권, Floating 후행 복리·lookback (요구사항 미정, 구현 보류)

## 기술 제약

- Python 3.12+, 패키지/가상환경은 `uv`, 테스트는 `pytest`
- 날짜는 `datetime.date`만 사용
- 금액·이율 계산은 전부 `decimal.Decimal` (float 금지, 문자열/정수로 생성)
- 반올림은 `RoundingPolicy` 한 곳에서만 수행 (`ROUND_HALF_UP`, `Decimal.quantize`). 내장 `round()` 금지
- 값 객체는 `@dataclass(frozen=True)`, 계산 로직은 순수 함수로 입출력과 분리
- 모든 계산 로직은 단위 테스트와 함께 작성, 금액 비교는 `Decimal` 정확 일치

## 구현 순서

각 단계마다 테스트 통과 후 커밋합니다.

1. `RoundingPolicy`, `Money`
2. Day Count 구현체와 단위 테스트 (C30/360 제외)
3. 이표 스케줄 생성
4. Fixed rate 경과이자
5. EIR 솔버와 Fixed rate 상각, Zero coupon 정액 상각
6. Floating rate (금리 테이블 입력)
7. MBS/ABS (PROSPECTIVE 기본값)
8. TIPS (Index Ratio, 하한)
9. 입출력 계층(CSV 로더, 로딩 검증)과 배치 처리
10. 대량 샘플 비교 검증 (독립 계산 결과 대비)

> `[확인필요]` 항목은 임의로 가정하지 말고 질문합니다. 구현 중 새로 발견된 `[가정]`/`[확인필요]`도 같은 원칙을 따릅니다.

## 모듈 구조

```
accrual/                        (패키지, src 레이아웃)
 ├─ models/        # Bond 유형, AccrualPeriod, CashFlow, AccrualResult, Money
 ├─ daycount/      # DayCountConvention (ABC) + 규약 구현체 (전략 패턴)
 ├─ schedule/      # 이표 스케줄 생성
 ├─ accrual/       # 유형별 경과이자 계산
 ├─ amortization/  # 유효이자율법, Zero coupon 정액법, EIR 솔버 (Decimal)
 ├─ rounding.py    # RoundingPolicy
 └─ io/            # CSV 로더/라이터, 로딩 검증 (계산 로직과 분리)
tests/             # pytest, 패키지 구조와 동일
```

## 검증 원칙

- 기대값은 구현 코드로 만들지 않습니다. 엑셀, 기존 시스템, 회계팀 확인값 등 독립 출처만 사용하고 각 케이스에 출처를 기록합니다.
- 불변식: 구간 일별 경과이자 합 = 이표 이자, 만기 상각후원가 = 상환 원금, 일별 상각액 합 = 만기 상각후원가 − 취득 상각후원가 등 (스펙 12.4)
