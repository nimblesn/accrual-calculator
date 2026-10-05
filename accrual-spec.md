# 채권 Accrual 계산 프로그램 스펙 (accrual-spec.md)

- 문서 상태: **v0.4** (v0.3의 13장 미결사항 1차 확정. Claude Code 입력용)
- 구현 언어: Python
- 표기 규칙: `[확정]` = 요구사항으로 확정된 사항, `[가정]` = 임시 가정(검토 필요), `[확인필요]` = 담당자 확정 전에는 구현 금지

---

## 0. v0.3 → v0.4 확정 로그

v0.3 13장의 미결 사항을 아래와 같이 확정했다. 각 항목의 상세 근거는 해당 장을 참고.

| # | 항목 | 결정 |
|---|---|---|
| 1 | Day Count 중복 코드 (순번 4, 5) | 순번 0(D30/360), 2(C30/360)와 동일 구현의 별칭(alias)으로 처리 [확정] |
| 2 | C30/360 정의 | 정의 미확인 — **구현하지 않음**, `UnsupportedDayCountError` 유지 [확정: 미구현 유지] |
| 3 | 30P/360 2월 말일 처리 | D30/360(Bond Basis)과 동일 규칙 적용 [확정] |
| 3 | ACT/ACT ISDA vs ICMA | **ICMA** 방식(`실제 경과일수 / (연 이표 횟수 × 해당 이표 구간 실제일수)`)을 기본으로 확정 [확정] |
| 4 | 반올림 모드 | `ROUND_HALF_UP` [확정] |
| 4 | 일별 금액 반올림 방식 | 스펙 4.3 제안 방식(누적값 반올림 후 차감) 그대로 확정 [확정] |
| 5 | JPY 외 소수 없는 통화(KRW 등) | 모두 일괄 소수 2자리로 반올림 [확정] |
| 6 | 휴일 조정(BDC) 적용 범위 | **(A) 확정**: 조정된 지급일을 현금흐름의 인식·할인 시점으로 사용한다. 경과이자(발생액)는 계약상 이표일 기준으로 끊고, 지급 전까지 미수 이자는 장부가에 포함한다. 주말은 영업일이 아닌 날로 본다 [확정] |
| 7 | Floating 후행 복리 (compounding in arrears) | **지원 필요로 범위 확장.** 상세 요구사항(적용 지수, lookback 기간, 복리 산출식)은 미정 — 별도 확정 전까지 미구현 [확인필요 유지, 범위 확장 승인] |
| 7 | Floating 관측 지연(lookback) | 후행 복리와 함께 범위 확장 승인. 상세 요구사항 미정 [확인필요 유지, 범위 확장 승인] |
| 7 | Floating 미확정 미래 리셋 구간 금리 | 직전 확정 금리를 유지하는 가정 확정 [확정] |
| 8 | MBS/ABS 현금흐름 추정 변경 처리 | **PROSPECTIVE**를 기본값으로 확정 (EIR 재산출, 장부가 유지) [확정] — v0.3의 CATCH_UP 가정을 대체 |
| 8 | MBS/ABS 지급 지연(payment delay) | 현금 수령일에만 영향, 경과이자 발생에는 영향 없음 — 가정 확정 [확정] |
| 9 | TIPS EIR 기준 | 실질(real) 기준으로 확정 [확정] |
| 9 | TIPS Index Ratio 소수 자리 | 소수 5자리로 확정 [확정] |
| 10 | 입출력 형식 | 1차는 CSV, 단 `io/` 계층을 DB·API로 교체 가능한 인터페이스로 설계 [확정] |
| 10 | 계산 규모 | 중대권: 수백~수만 종목 × 다년 규모. 배치 처리 전제로 설계 [확정] |
| 11 | K-IFRS 1109 정합성 확인 | 현재는 불필요 — 순수 기술 스펙으로 진행. 추후 회계팀 검토 별도 진행 [확정: 보류] |
| 12 | Zero coupon 정액 상각 일수 | 실제 일수(만기일 − 취득일) 기준으로 확정 [확정] |
| 13 | Python 버전 / 패키지 도구 | Python 3.12+, `uv` [확정] |
| 14 | 계산 시작일 기준 | 결제일(settlement_date) 기준 [확정] |
| 14 | 부분 매도 로트 차감 방식 | FIFO(선입선출) [확정] |
| 15 | 부분 상환 이력 / 이월 적용 | 스펙 10.6 `opening_balance.csv` 구조 그대로 확정 [확정] |
| 16 | 콜/풋 옵션부 채권 | **지원 필요로 범위 확장.** 옵션 행사 모델(콜/풋 스케줄 입력, 행사 판정 방식, 예상 만기 산정)은 별도 요구사항 확정 전까지 미구현 [확인필요 유지, 범위 확장 승인] |

**아직 상세 요구사항이 없어 구현 보류 중인 확장 과제 3건**: Floating 후행 복리, Floating lookback, 콜/풋 옵션부 채권. 이 세 가지는 14장 구현 순서에 포함되지 않으며, 별도로 요구사항을 확정한 뒤 스펙에 추가한다 (15장 참고).

---

## 1. 목적과 범위

### 1.1 목적
채권별 **경과이자(Accrued Interest)** 와 **할인/할증 상각(유효이자율법)** 을 일자 단위로 계산한다.

### 1.2 계산 대상 [확정]
1. 경과이자 (Accrued Interest)
2. 할인/할증 상각액 (유효이자율법, Effective Interest Method. 단 Zero coupon은 정액법)

### 1.3 지원 채권 유형 [확정]
Fixed rate bond / Floating rate bond / MBS / ABS / TIPS

### 1.4 범위 제외 [확정]
- 세금(원천징수 등) 반영 안 함. 모든 금액은 **세전** 기준
- 정액법 상각은 **Zero coupon 채권의 상각에만** 사용한다 (9.5 참조). 그 외 채권은 유효이자율법만 사용
- 기준통화 환산(환율 적용)은 지원하지 않음. 결과는 채권 통화 기준으로만 출력

### 1.5 범위 확장 승인 — 상세 요구사항 확정 전까지 미구현 [확인필요]

아래 3건은 "지원 필요"로 범위에는 포함되었으나, 구현에 필요한 상세 요구사항이 아직 없다. 요구사항이 확정되기 전까지는 구현하지 않으며, 15장에서 별도로 다룬다.

1. **콜/풋 옵션부 채권**: 옵션 스케줄 입력 형식, 행사 판정 방식(모델 기반 vs 외부 입력), 예상 만기 산정 방식 미정
2. **Floating rate bond 후행 복리** (compounding in arrears, 예: SOFR): 적용 대상 지수, 복리 산출식 미정
3. **Floating rate bond 관측 지연** (lookback): lookback 기간, 적용 대상 지수 미정

---

## 2. 용어

| 용어 | 정의 |
|---|---|
| Face / Par | 액면금액. MBS/ABS는 현재 잔액(Current Face = Original Face × Factor) |
| Clean Price | 경과이자를 제외한 가격 |
| Dirty Price | Clean Price + 경과이자 |
| Accrued Interest | 직전 이표일(또는 발행일)부터 계산일까지 발생한 이자 |
| EIR | 유효이자율 (Effective Interest Rate) |
| Amortized Cost | 상각후원가 = 취득원가 ± 누적 상각액 |
| DCF | Day Count Fraction (일수계산 비율) |

---

## 3. 기술 스택과 공통 제약

- Python 3.12 이상 [확정], 패키지/가상환경 관리 도구는 **uv** [확정], 테스트 pytest
- 타입 힌트 필수, 정적 검사(mypy 또는 pyright)를 포함한다 [가정]
- 날짜: `datetime.date` 만 사용 (시각이 포함된 `datetime` 사용 금지)
- **금액·이율 계산에 `float` 사용 금지. 전부 `decimal.Decimal`**
  - `Decimal`은 반드시 문자열 또는 정수로 생성한다 (`Decimal("0.05")`). `Decimal(0.05)`처럼 float로 생성하면 이진 오차가 유입되므로 금지
  - numpy, pandas, scipy 등 float 기반 연산을 계산 경로에 사용하지 않는다. 파일 입력 시에는 문자열로 읽어(`dtype=str`) `Decimal`로 변환한 뒤 계산한다
- 값 객체는 `@dataclass(frozen=True)`로 정의한다 (불변)
- 계산 로직은 순수 함수(입출력·DB 접근과 분리)
- 모든 계산 로직은 단위 테스트와 함께 작성

---

## 4. 정밀도와 반올림 규칙

### 4.1 반올림 [확정]

| 통화 | 소수 자릿수 | 방식 |
|---|---|---|
| JPY | 0 (소수점 없음) | 반올림 |
| 그 외 모든 통화 | 2 | 소수 3째 자리에서 반올림 (소수 2자리까지 표시) |

- 반올림 모드: `decimal.ROUND_HALF_UP` [확정] (음수는 0에서 먼 방향으로 올림됨)
- 반올림은 `RoundingPolicy` **한 곳에서만** 수행한다 (`Decimal.quantize` 사용). 다른 모듈에서 `quantize`를 직접 호출하지 않는다. 내장 `round()`는 `ROUND_HALF_EVEN`으로 동작하므로 사용 금지

### 4.2 중간 계산 정밀도 [가정]
- 중간 계산은 반올림하지 않고 `decimal.localcontext()`로 정밀도 34자리(`prec=34`) 이상을 설정하여 유지한다. 전역 컨텍스트(`getcontext()`)는 수정하지 않는다.
- **최종 출력 금액에만** 반올림을 적용한다.

### 4.3 일별 금액의 반올림 방식 [확정]
일별 금액을 각각 반올림해서 합산하면 기간 합계가 어긋난다. 따라서 다음 방식을 기본으로 한다.

```
누적 경과이자(t) = round( 정밀 누적값(t) )
일별 경과이자(t) = 누적 경과이자(t) - 누적 경과이자(t-1)
```

이 방식은 항상 `일별 합계 = 기간 누적값` 이 성립한다.

---

## 5. Day Count 규약

### 5.1 지원 목록 [확정]

제공된 목록의 순서를 순번으로 보존한다 (0부터 시작 가정, 실제 코드값은 확인필요). 원 목록의 `Not support` 2건(순번 8, 9)은 **지원 대상에서 제외**하며 해당 순번은 결번으로 둔다.

| 순번 | 코드 | 처리 |
|---|---|---|
| 0 | D30/360 | 지원 |
| 1 | 30E/360 | 지원 |
| 2 | C30/360 | **미구현** (정의 미확인. 확정 전까지 `UnsupportedDayCountError`) [확정: 미구현 유지] |
| 3 | 30P/360 | 지원 |
| 4 | D30/360 | 순번 0과 동일 구현의 별칭(alias) [확정] |
| 5 | C30/360 | 순번 2와 동일 취급 — 즉 이 역시 미구현 [확정] |
| 6 | NL/365 | 지원 |
| 7 | ACT/365 | 지원 |
| 10 | ACT/360 | 지원 |
| 11 | ACT/AFB | 지원 |
| 12 | ACT/TSY | 지원 |
| 13 | ACT/ACT | 지원. **ICMA** 방식 [확정] |
| 14 | ACT/366 | 지원 |

- 순번 4, 5는 각각 순번 0, 2와 동일한 구현으로 매핑하는 별칭(alias)으로 처리한다 [확정]. 순번 2(C30/360)와 그 별칭인 순번 5는 정의가 확인되기 전까지 미구현 상태를 유지하며, 두 코드 모두 `UnsupportedDayCountError`를 발생시킨다.
- 목록에 없는 코드(결번 포함)가 입력되면 계산을 시도하지 않고 `UnsupportedDayCountError` 예외를 발생시킨다.

### 5.2 규약별 정의

기호: 시작일 `Y1-M1-D1`, 종료일 `Y2-M2-D2`.
30/360 계열 공통식: `일수 = 360×(Y2-Y1) + 30×(M2-M1) + (D2-D1)`, `DCF = 일수 / 360`

| 코드 | 정의 (구현 기준) |
|---|---|
| D30/360 | 30/360 Bond Basis [가정]. D1=31이면 D1=30. D2=31이고 (조정 후) D1=30이면 D2=30 |
| 30E/360 | Eurobond Basis. D1=31이면 D1=30. D2=31이면 D2=30 |
| C30/360 | **미구현.** 원천 시스템 정의가 확인되기 전까지 구현하지 않음 [확정: 미구현 유지] |
| 30P/360 | 30/360 PSA (MBS 관행). D30/360(Bond Basis)과 동일한 규칙으로 구현 (2월 말일 처리 포함) [확정] |
| NL/365 | 실제 일수에서 2월 29일을 제외한 일수 / 365 |
| ACT/365 | 실제 일수 / 365 (Fixed) |
| ACT/360 | 실제 일수 / 360 |
| ACT/366 | 실제 일수 / 366 |
| ACT/AFB | 실제 일수 / 365. 단 계산 구간에 2월 29일이 포함되면 / 366. 1년을 초과하는 구간은 종료일 기준 역방향으로 정수 연수를 먼저 분리하고 나머지 구간에 같은 규칙 적용 |
| ACT/TSY | 미국 국채 관행. 이표 구간 기준 `실제 경과일수 / (이표 구간 실제일수 × 연 이표 횟수)`. 불규칙 구간(first/last stub)은 quasi-coupon period 사용 |
| ACT/ACT | **ACT/ACT ICMA** [확정]: `실제 경과일수 / (연 이표 횟수 × 해당 이표 구간 실제일수)`. 이표 구간은 호출자가 `period`로 전달 |

### 5.3 인터페이스 요구사항
ACT/ACT ICMA와 ACT/TSY는 이표 구간 정보가 필요하므로, 모든 구현체가 공유하는 일반 시그니처를 다음과 같이 한다. 그 외 규약은 `period` 인자를 사용하지 않는다.

```python
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal

class DayCountConvention(ABC):
    @abstractmethod
    def day_count(self, start: date, end: date) -> int: ...

    @abstractmethod
    def year_fraction(self, start: date, end: date, period: "AccrualPeriod") -> Decimal: ...
```

`AccrualPeriod` = (구간 시작일, 구간 종료일, 연 이표 횟수).

### 5.4 Day Count 검증용 예시 (손계산 가능)

| 시작일 | 종료일 | 규약 | 일수 |
|---|---|---|---|
| 2024-02-29 | 2024-03-31 | D30/360 | 32 |
| 2024-02-29 | 2024-03-31 | 30E/360 | 31 |
| 2024-02-29 | 2024-03-31 | ACT/360, ACT/365 | 31 |
| 2024-02-28 | 2024-03-01 | ACT/365 | 2 |
| 2024-02-28 | 2024-03-01 | NL/365 | 1 (2/29 제외) |

---

## 6. 채권 유형별 규칙

### 6.1 Fixed rate bond
- 쿠폰: 고정금리, 연 이표 횟수(freq) 1/2/4/12 및 만기일시(Zero coupon, 쿠폰 0) 지원 (Zero coupon의 상각은 9.5 참조)
- 경과이자: 8장 공식 적용

### 6.2 Floating rate bond
- 쿠폰 = `기준금리(Index) × Multiplier + Spread`, Cap/Floor 적용 가능
- 기준금리는 **외부 입력**(리셋일별 금리 테이블)으로 받는다. 프로그램이 금리를 조회/추정하지 않는다.
- 리셋 구간별로 해당 구간의 확정 금리를 사용한다. 미확정 미래 구간은 최근 확정 금리를 유지한다 [확정].
- 후행 복리(compounding in arrears, 예: SOFR)와 관측 지연(lookback)은 **지원 필요로 범위에는 포함되나, 상세 요구사항 확정 전까지 미구현** [확인필요, 범위 확장 승인 — 1.5, 15장 참고]

### 6.3 MBS
- 금액 기준 [확정]: security_master `original_face`는 **풀 전체** 발행 원금, trades `face_amount`는 **보유분**(결제 시점 잔액)이다.
- 로트 원금 = `face_amount / factor(결제일)` (factor(d) = d 이하 최신 Factor)
- 로트 현재 잔액 = `로트 원금 × Pool Factor`. Factor 변경일 이후 구간부터 새 잔액으로 경과이자 계산
- 경과이자 = 현재 잔액 × 쿠폰 × DCF (기본 Day Count: 30P/360 [가정])
- 지급 지연(payment delay) 일수는 **현금 수령일**에만 영향을 주며 경과이자 발생에는 영향을 주지 않는다 [확정]
- 조기상환 반영: 프로그램이 조기상환을 추정하지 않고, 외부에서 **예상 현금흐름(원금/이자)** 을 입력받는다.

### 6.4 ABS
- 6.3 MBS와 동일한 구조(잔액 기반, 외부 현금흐름 입력)를 사용한다.
- 상환 구조(Pass-through, Sequential 등)는 현금흐름 입력에 이미 반영되어 있다고 가정한다.

### 6.5 TIPS (물가연동국채)
- 이자·원금은 **물가연동 원금(Adjusted Principal) = Par × Index Ratio** 기준
- Reference CPI [확정]:
  - 매월 1일의 Ref CPI = (M-3)월 CPI-U (NSA)
  - 월중 임의일 Ref CPI = `RefCPI(M) + (d-1)/해당월일수 × (RefCPI(M+1) - RefCPI(M))`, 결과는 소수 여섯째 자리에서 4사5입하여 **소수 다섯째 자리까지 확정**하여 사용 [확정]
  - 여기서 `RefCPI(M)` = 결제월의 3개월 전 CPI, `RefCPI(M+1)` = 2개월 전 CPI
- Index Ratio = `Ref CPI(계산일) / Ref CPI(발행 기준일)`, 소수 5자리 [확정]
- 경과이자 = 실질(real) 쿠폰율 기반 이자 × Index Ratio 적용 원금 (Day Count 기본 ACT/TSY [가정]). EIR도 실질 기준으로 산출 [확정]
- 별도 산출: **인플레이션 보상 경과분** = `Par × (IndexRatio(t) - IndexRatio(t0))`
- 디플레이션 하한: 만기 상환액 = `max(조정 원금, Par)`
- 월별 CPI는 외부 입력으로 받는다.

---

## 7. 이표 스케줄 생성

- 입력: 발행일, 만기일, 최초 이표 시작일(Dated Date), 연 이표 횟수, 최초/최종 이표 구간 처리(short/long stub)
- 출력: 이표 구간 리스트 `(구간 시작일, 구간 종료일, 지급일)`
- 월말 기준(end-of-month) 적용 여부를 입력 플래그로 받는다 (예: 2/28 만기 채권의 8/31 이표 처리).
- 휴일 조정(Business Day Convention) [확정, (A)]:
  - 경과이자(발생액)는 **계약상 이표일(unadjusted)** 기준으로 계산하고 이표일에 0으로 리셋한다.
  - 이자 현금은 **조정된 지급일**에 수령한다. 할인(EIR, 예상 현금흐름 PV)과 이자수익 인식도 조정된 지급일 기준으로 한다.
  - 계약일과 지급일 사이에 발생한 쿠폰은 지급 전까지 미수이자로 장부가(Dirty)에 남는다.
  - 영업일 규칙(FOLLOWING, MODIFIED_FOLLOWING, PRECEDING)과 캘린더는 종목 마스터에서 지정하며, 주말은 영업일이 아니다.

---

## 8. 경과이자 계산

### 8.1 공식

```
Accrued Interest(t) = 현재 액면(잔액) × 쿠폰율 × YearFraction(직전 이표일, t)
```

- ACT/ACT·ACT/TSY 계열은 `쿠폰율 / freq × 경과일수 / 이표 구간일수`와 동일
- 이표일 당일: 경과이자 = 0 (해당 이표 지급 후 새 구간 시작)
- 발행일 당일: 경과이자 = 0

### 8.2 출력
- 일별 **누적 경과이자**와 **일별 발생분** (4.3 방식으로 산출)

---

## 9. 할인/할증 상각 (유효이자율법)

### 9.1 취득 원가 [가정]
```
Dirty 취득금액 = Clean Price × Face / 100 + 취득 부대비용 + 취득 시점 경과이자
```
취득 시점 경과이자는 미수이자(경과이자 계정)로 분리하며 상각후원가에서는 제외한다.

### 9.2 EIR 산출
미래 현금흐름 `CF_k` (이표 + 원금)에 대해, 이표 구간 단위 유효이자율 `i`를 다음 식으로 푼다.

```
Dirty 취득금액 = Σ CF_k / (1 + i)^(n_k)
n_1 = 취득일 이후 첫 이표까지 남은 구간 비율 (남은 DCF / 구간 DCF)
n_k = n_1 + (k - 1)
```

- 해는 수치해법(Newton-Raphson, 실패 시 이분법)으로 구한다. 허용오차 `1e-12` 이하 [가정]. `Decimal`로 직접 구현하며 `scipy.optimize` 등 float 기반 솔버는 사용하지 않는다.
- Zero coupon 채권은 EIR을 산출하지 않는다 (9.5 참조).
- 연환산 EIR = `(1 + i)^freq - 1` (참고 출력)

### 9.3 일별 상각후원가
```
Dirty AC(t) = Dirty AC(t0) × (1 + i)^Δf
Δf = 구간 내 경과 비율 (경과 DCF / 구간 DCF)
```

- 분수 지수 계산은 `Decimal` 연산(`**` 또는 `ln`/`exp`)으로 수행한다.
- 이표 지급일에는 `Dirty AC` 에서 이표 현금을 차감한다.
- **상각후원가(Clean) = Dirty AC - 경과이자**

### 9.4 일별 이자수익과 상각액 (Zero coupon은 9.5의 정액법 적용)
```
이자수익(t) = Dirty AC(t) - Dirty AC(t-1) + 해당일 수령 이표 현금
상각액(t)   = 이자수익(t) - 일별 경과이자(t)
```

- 할인 취득: 상각액 > 0 (장부가 증가) / 할증 취득: 상각액 < 0 (장부가 감소)
- 만기일 상각후원가는 반드시 상환 원금과 일치해야 한다. 잔여 오차는 **마지막 구간에서 조정**한다 (반올림 누적 오차 흡수).

### 9.5 유형별 특이사항
- **Fixed**: 취득 시점 1회 EIR 산출 후 고정
- **Floating**: 금리 리셋 시점마다 미래 현금흐름을 갱신해 EIR을 재산출한다. 이때 장부가는 유지(전진적 처리) [가정, 확인필요]
- **MBS/ABS**: 현금흐름 추정 변경 시 처리 방식은 설정값으로 두되, 기본값은 **`PROSPECTIVE`** (EIR 재산출, 장부가는 유지) [확정]. `CATCH_UP`(기존 EIR로 재계산한 장부가와의 차이를 즉시 손익 처리)은 설정값으로 계속 지원한다.
- **TIPS**: 실질(real) EIR을 산출하여 물가연동 원금에 적용한다 [확정]
- **Zero coupon** (쿠폰율 0인 Fixed): 유효이자율법을 적용하지 않고 **정액법**으로 상각한다.
  - 경과이자 = 0 (이표 이자 없음)
  - EIR 산출 없음 (`eir` 출력은 비움)
  - 일별 상각액 = `(상환 원금 - 취득 시점 상각후원가) / 총 일수`
  - 총 일수 = 만기일 - 취득일 (실제 일수, Day Count 규약 미적용) [확정]
  - 일별 금액은 4.3 방식(누적 후 반올림, 차이로 일별 산출)으로 구하고, 만기일에 상각후원가가 상환 원금과 일치하도록 마지막 일자에서 잔차를 조정한다
  - 이자수익 = 상각액 (경과이자가 0이므로)
  - 상각후원가(t) = 취득 시점 상각후원가 + 누적 상각액(t)

---

## 10. 입출력 명세 (데이터 사전)

### 10.0 형식과 규모 [확정]

- 1차 구현은 CSV 입출력으로 한정한다. 단 `io/` 계층(11장)은 로더/라이터를 교체 가능한 인터페이스로 설계하여, 추후 DB·API 연동으로 CSV를 대체할 수 있게 한다.
- 계산 규모는 **종목 수백~수만 건 × 다년(多年) 기간**을 전제로 한다. 단일 프로세스 배치 처리를 기본으로 설계하고, 종목 단위로 계산이 독립적이므로 추후 병렬화(멀티프로세스 등) 여지를 남긴다. 구체적 성능 목표(처리 시간 SLA 등)는 아직 없음 — 필요 시 별도 요건으로 추가.

### 10.1 입력 파일 개요

| 파일 | 내용 | 필요한 경우 |
|---|---|---|
| security_master.csv | 종목 마스터 (종목당 1행) | 항상 |
| trades.csv | 거래/로트 정보 | 항상 |
| opening_balance.csv | 시작 잔액 (이월) | 중간 시점부터 이어서 계산할 때 |
| floating_rate_index.csv | 기준금리 이력 | FLOATING |
| cpi_index.csv | 월별 CPI 지수 | TIPS |
| pool_factor.csv | Pool Factor 이력 | MBS/ABS |
| projected_cashflows.csv | 예상 현금흐름 | MBS/ABS (상각용) |
| holiday_calendar.csv | 휴일 캘린더 | 휴일 조정 적용 시 [확인필요] |
| daycount_code.csv | Day Count 코드 ↔ 명칭 매핑 | 항상 (5.1 결번 포함) |

계산 실행 파라미터(파일 아님): `calc_start_date`, `calc_end_date`, 입력 파일 경로

### 10.2 파일 포맷 공통 규칙 (CSV 사용은 10.0에서 확정. 아래 세부 규칙은 1차안)

| 항목 | 규칙 |
|---|---|
| 인코딩/구분자 | UTF-8 (BOM 없음), 콤마, 헤더 행 필수 |
| 날짜 | `YYYY-MM-DD` (ISO 8601) 고정 |
| 숫자 | 소수점 `.`, 천 단위 구분자 없음, 지수 표기(`1E-5`) 금지 |
| 이율 | 컬럼명에 단위 명시. `*_pct`는 퍼센트 값(3.125 = 3.125%)이며 내부에서 100으로 나눔 |
| 가격 | 액면 100 기준 |
| 금액 | 통화 단위 그대로 (JPY는 소수 없음) |
| enum | 허용값 고정, 대문자 (FIXED, BUY 등) |
| 빈 값 | 빈 문자열 = null. 0과 구분 |
| Y/N 플래그 | 대문자 `Y`/`N` |
| 파싱 | 모든 값을 문자열로 읽고 `Decimal`/`date`로 변환 (3장 규칙). float 경유 금지 |

### 10.3 security_master.csv

**공통 필드**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| security_id | str | 필수 | ISIN 또는 내부 종목코드 (PK) |
| bond_type | enum | 필수 | FIXED / FLOATING / MBS / ABS / TIPS |
| currency | str(3) | 필수 | ISO 4217. 반올림 규칙 결정 (4.1) |
| issue_date | date | 필수 | 발행일 |
| dated_date | date | 필수 | 이자 기산일 (발행일과 다를 수 있음) |
| maturity_date | date | 필수 | 만기일 |
| first_coupon_date | date | 조건부 | 최초 이표일. stub이 있을 때 필수, 비어 있으면 기산일 기준 정규 스케줄 |
| coupon_rate_pct | decimal | 필수 | 쿠폰율. Zero coupon은 0. FLOATING은 최초 쿠폰 또는 미사용 |
| coupon_freq | int | 필수 | 연 이표 횟수 (1/2/4/12). Zero coupon은 0 |
| day_count_code | enum | 필수 | 5.1 코드 (지원 목록에 있는 값만 허용) |
| eom_flag | Y/N | 필수 | 월말 기준 여부 |
| business_day_conv | enum | 선택 | 휴일 조정 방식 [확인필요] |
| redemption_price_pct | decimal | 필수 | 상환가격 (보통 100) |

**유형별 추가 필드**

| 유형 | 필드 |
|---|---|
| FLOATING | index_name, spread_pct, multiplier (기본 1), cap_pct (선택), floor_pct (선택), reset_freq, fixing_lag_days |
| MBS / ABS | original_face, pool_id, payment_delay_days |
| TIPS | cpi_index_name, base_ref_cpi (발행 기준일의 Ref CPI), deflation_floor_flag (Y/N) |

### 10.4 trades.csv

상각은 **취득 단위(로트)** 로 계산하므로 종목 정보만으로는 부족하다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| trade_id | str | 필수 | 거래 식별자 (PK) |
| lot_id | str | 필수 | 로트 식별자. SELL은 차감 대상 로트를 지정 |
| portfolio_id | str | 선택 | 계정/포트폴리오 |
| security_id | str | 필수 | 종목 FK |
| side | enum | 필수 | BUY / SELL |
| trade_date | date | 필수 | 거래일 |
| settlement_date | date | 필수 | 결제일 |
| face_amount | decimal | 필수 | 액면. MBS/ABS는 해당 시점 잔액 기준 |
| clean_price | decimal | 필수 | Clean Price (액면 100 기준) |
| accrued_interest_paid | decimal | 필수(BUY) | 실제 지급한 경과이자. 계산값 대조용 (10.8) |
| transaction_cost | decimal | 필수 | 취득 부대비용 (없으면 0) |

- 계산 시작일은 **결제일(settlement_date)** 기준 [확정]
- 부분 매도 시 로트 차감 방식: **FIFO(선입선출)** [확정]
- 부분 상환(원금 상환) 이력은 10.6 `opening_balance.csv` 구조로 반영한다 [확정]. MBS/ABS는 pool_factor.csv로 대체 가능

### 10.5 참조 데이터 파일

| 파일 | 필드 | 비고 |
|---|---|---|
| floating_rate_index.csv | index_name, reset_date, rate_pct | 계산 기간 내 모든 리셋일 필요 |
| cpi_index.csv | cpi_index_name, month (YYYY-MM), cpi_value | 6.5장 Ref CPI 산출용 (필요한 월은 계산 월 기준 M-3 ~ M-2) |
| pool_factor.csv | security_id, effective_date, factor | factor는 소수 8자리 등 원본 자릿수 그대로 |
| projected_cashflows.csv | security_id, version, effective_date, pay_date, principal, interest, basis_face(선택) | 취득 이후 현금흐름. `basis_face`는 해당 버전의 기준 보유 액면(effective_date 시점 잔액). 값이 있으면 로트 비율 = `잔여 로트 액면 × factor(effective_date) / factor(settlement_date) / basis_face`, 비어 있으면 기존대로 `잔여 로트 액면 / trade.face_amount` [확정: mbs-cashflow spec 6.3 (a)] |
| holiday_calendar.csv | calendar_id, date | |
| daycount_code.csv | code_no, code_name | 5.1 순번/코드 매핑 |

### 10.6 opening_balance.csv (이월 시)

| 필드 | 설명 |
|---|---|
| lot_id | 로트 식별자 |
| as_of_date | 잔액 기준일 |
| face | 액면(잔액) |
| amortized_cost | 상각후원가 (Clean) |
| cumulative_amortization | 누적 상각액 |
| accrued_interest | 누적 경과이자 |
| eir_periodic | 구간 단위 EIR (Zero coupon은 비움) |

- 이 파일이 있으면 `as_of_date` 다음 날부터 이어서 계산하고 취득 시점 계산(9.1~9.2)은 생략한다 [확정]
- 이월 후 계산 결과가 기존 시스템과 일치하는지가 기본 검증 항목이다.

### 10.7 샘플 (값은 설명용 가상 데이터)

```csv
# security_master.csv (공통 필드만 표시)
security_id,bond_type,currency,issue_date,dated_date,maturity_date,first_coupon_date,coupon_rate_pct,coupon_freq,day_count_code,eom_flag,redemption_price_pct
SAMPLE0001,FIXED,USD,2024-01-15,2024-01-15,2029-01-15,2024-07-15,4.250,2,30E/360,N,100
SAMPLE0002,FIXED,JPY,2024-03-01,2024-03-01,2027-03-01,,0,0,ACT/365,N,100
```

```csv
# trades.csv
trade_id,lot_id,portfolio_id,security_id,side,trade_date,settlement_date,face_amount,clean_price,accrued_interest_paid,transaction_cost
T0001,L0001,P01,SAMPLE0001,BUY,2024-02-20,2024-02-22,1000000,98.750,4368.06,0
```

### 10.8 로딩 단계 검증

계산 전에 입력 데이터를 검증하고, 오류가 있으면 **행 번호와 필드명을 포함한 오류 목록**을 출력한 뒤 계산을 중단한다.

1. 필수 필드 누락, enum 값 위반, 타입 변환 실패
2. 날짜 순서: 발행일 ≤ 기산일 ≤ 최초 이표일 ≤ 만기일, 거래일 ≤ 결제일
3. `day_count_code`가 지원 목록에 존재하는지 (결번 포함 거부)
4. 유형별 필수 필드와 외부 데이터 존재 여부 (FLOATING 금리 이력, TIPS CPI, MBS/ABS Factor/현금흐름)
5. 계산 기간 내 금리, CPI, Factor 누락일 여부
6. 키 중복(`security_id`, `trade_id`)과 FK 정합성(trades의 security_id가 마스터에 존재)
7. 통화별 자릿수 위반 (예: JPY 금액에 소수점 존재)
8. **취득 시점 `accrued_interest_paid` ↔ 프로그램 계산 경과이자 대조** (불일치 시 경고. Day Count/스케줄 설정 오류를 가장 먼저 발견하는 검증)

### 10.9 출력 (일별 행)

| 필드 | 설명 |
|---|---|
| lot_id, security_id, currency | 키와 통화 |
| date | 일자 |
| accrued_interest_cum | 누적 경과이자 |
| accrued_interest_daily | 일별 경과이자 |
| interest_income | 유효이자 기준 이자수익 (Zero coupon은 상각액과 동일) |
| amortization | 할인/할증 상각액 |
| amortized_cost | 상각후원가 (Clean) |
| eir | 적용 EIR (구간 단위/연환산). Zero coupon은 비움 |
| inflation_accrual | TIPS 전용 인플레이션 보상 경과분 |

출력 파일 형식도 10.2의 공통 규칙을 따른다. 계산 모듈은 입출력 형식에 의존하지 않도록 설계하고, CSV 로더/라이터는 `io/` 모듈로 분리한다.

---

## 11. 모듈 구조 (Python)

```
accrual/                        (패키지, src 레이아웃)
 ├─ models/
 │   ├─ bond.py                # FixedRateBond, FloatingRateBond, MbsBond, AbsBond, TipsBond
 │   ├─ period.py              # AccrualPeriod, CashFlow
 │   ├─ result.py              # AccrualResult
 │   └─ money.py               # Money (Decimal + 통화코드)
 ├─ daycount/
 │   ├─ base.py                # DayCountConvention (ABC)
 │   ├─ types.py               # DayCountType (Enum, 코드 매핑)
 │   └─ conventions.py         # Thirty360BondBasis, Thirty360E, ActActIcma, ActAfb, ActTsy, ...
 ├─ schedule/
 │   └─ coupon_schedule.py     # CouponScheduleGenerator
 ├─ accrual/
 │   └─ accrued_interest.py    # 유형별 경과이자 계산 (전략)
 ├─ amortization/
 │   ├─ effective_interest.py  # 유효이자율법 상각
 │   ├─ straight_line.py       # Zero coupon 정액법 상각
 │   └─ eir_solver.py          # Newton-Raphson + 이분법 fallback (Decimal)
 ├─ rounding.py                # RoundingPolicy
 └─ io/                        # CSV 로더/라이터, 로딩 검증 (loaders.py, validators.py). 계산 로직과 분리
tests/                          # pytest, 패키지 구조와 동일하게 구성
```

설계 원칙: Day Count와 채권 유형은 전략 패턴(ABC + Enum 레지스트리)으로 분리하여 신규 추가 시 기존 코드를 수정하지 않는다. 값 객체는 `@dataclass(frozen=True)`로 정의한다.

---

## 12. 검증 요건

### 12.1 테스트 데이터 원칙
- **기대값은 구현 코드로 만들지 않는다.** 엑셀, 기존 시스템, 회계팀 확인값 등 독립된 출처만 사용한다.
- 각 케이스에 출처를 기록한다.
- 테스트는 pytest로 작성하고, 금액 비교는 `Decimal` 정확 일치로 검증한다 (float 기반 `pytest.approx` 사용 금지).

### 12.2 테스트 케이스 템플릿

| ID | 채권유형 | 통화 | Day Count | 입력 요약 | 기대값(경과이자) | 기대값(상각액) | 출처 |
|---|---|---|---|---|---|---|---|
| T-001 | | | | | | | |

### 12.3 필수 경계 케이스
- 윤년(2/29 포함 구간), 2월 말일 시작/종료
- 이표일 당일, 발행일 당일, 만기일 당일
- 31일 시작/종료 (30/360 계열 차이 확인)
- 첫 이표(short/long stub), 마지막 이표 구간
- 월말 기준(EOM) 플래그 On/Off
- JPY (소수 0자리)와 USD 등 (소수 2자리) 반올림 비교
- 할인 취득, 할증 취득, 액면 취득(상각 0)
- Zero coupon 정액 상각 (총 일수로 나누어떨어지지 않는 경우, 만기일 잔차 조정)
- TIPS 디플레이션 하한, Floating 금리 리셋일 경계
- MBS Factor 변경일 경계

### 12.4 불변식 (자동 검증 대상)
1. 한 이표 구간의 일별 경과이자 합 = 해당 구간 이표 이자 (반올림 허용오차 이내)
2. 만기일 상각후원가 = 상환 원금
3. 전체 기간 이자수익 합 = 이표 현금 합계 + (상환 원금 - 취득 원가)
4. 일별 상각액 합 = 만기 상각후원가 - 취득 상각후원가
5. 이표일 직후 경과이자 = 0

---

## 13. 미결 사항 — v0.4에서 확정됨

v0.3의 16개 미결 사항은 모두 0장("v0.3 → v0.4 확정 로그")에 정리된 대로 결정되었다. 이 중 2건(C30/360 정의)은 "확인 전까지 미구현"으로 확정되었고, 3건(Floating 후행 복리/lookback, 콜·풋 옵션부 채권)은 "지원 필요"로 범위가 확장되었으나 상세 요구사항이 없어 구현을 보류한다 (15장 참고). 나머지는 모두 [확정]으로 전환되어 각 장에 반영되었다.

v0.3 13장에 나열되었던 **구조적 결정**(반올림, Day Count, 채권유형별 처리방식, 입출력 형식 등)은 모두 해결되었다. 다만 그 결정을 구현하는 과정에서 나오는 **세부 디테일** 수준의 `[가정]`/`[확인필요]`는 각 장에 남아있으며, 구현 단계에서 하나씩 질문해 확정한다. 주요 항목:
- 5.1 Day Count 코드의 **실제 전산 코드값** (순번만 정의됨, 시스템 연동 시 필요)
- 5.2 D30/360의 세부 Bond Basis 규칙 [가정]
- 6.3 MBS 기본 Day Count(30P/360) 가정
- 9.1 취득원가 공식, 9.2 EIR 솔버 허용오차(`1e-12`)
- 9.5 Floating EIR 재산출 시 장부가 처리(전진적) [가정, 확인필요]
- 10.2 CSV 파일 포맷의 세부 규칙, 10.3 `business_day_conv` 의 구체적 enum 값(Following 등), 10.5 `projected_cashflows.csv` 의 버전 구분 필요 여부
- 3장 정적 타입 검사(mypy/pyright) 도입 여부

---

## 14. 구현 순서 (Claude Code 작업 단위)

각 단계마다 테스트 통과 후 커밋한다. 괄호 안은 이번 범위에서 제외되는 부분(15장 참고).

1. `RoundingPolicy`, `Money`
2. Day Count 구현체와 단위 테스트 (5.4 예시 포함, C30/360 제외)
3. 이표 스케줄 생성
4. Fixed rate 경과이자
5. EIR 솔버와 Fixed rate 상각, Zero coupon 정액 상각
6. Floating rate (금리 테이블 입력 — 후행 복리/lookback 제외)
7. MBS/ABS (Factor, 예상 현금흐름, PROSPECTIVE 기본값)
8. TIPS (Index Ratio, 하한)
9. 입출력 계층(CSV 로더, 로딩 검증 10.8)과 배치 처리
10. 대량 샘플 비교 검증 (독립 계산 결과 대비)

> Claude Code 지시 원칙: 이 문서의 `[확인필요]` 항목은 임의로 가정하여 구현하지 말고 질문할 것.

---

## 15. 추후 확장 과제 (요구사항 확정 전까지 미구현)

다음 항목들은 "지원 필요"로 범위에는 포함되었으나, 구현 가능한 수준의 상세 요구사항이 아직 없다. 각 항목의 요구사항이 확정되면 별도 버전(v0.5 이상)으로 스펙에 추가한다. 이 문서의 1~14장 범위와 구현 순서(14장)에는 포함되지 않는다.

### 15.1 콜/풋 옵션부 채권
확정 필요 사항:
- 옵션 스케줄 입력 형식 (행사일, 행사가격 목록을 어떤 파일/필드로 받을지)
- 행사 판정 방식: 외부에서 "행사 여부/예상 만기"를 그대로 입력받는 방식 vs 모델 기반(옵션 가치 평가 후 판정) 방식
- 경과이자·상각 계산 시 만기를 어느 날짜로 간주할지 (콜/풋 가능일, 예상 행사일, 법적 만기일 등)

### 15.2 Floating rate bond 후행 복리 (compounding in arrears)
확정 필요 사항:
- 적용 대상 지수 (SOFR, ESTR 등 구체적으로 어떤 지수를 지원할지)
- 복리 산출식 (Compounded in Arrears vs Simple Average 등)
- 리셋 주기와 쿠폰 확정 시점의 관계

### 15.3 Floating rate bond 관측 지연 (lookback)
확정 필요 사항:
- lookback 기간 (며칠)
- 적용 대상 지수 및 15.2 후행 복리와의 결합 방식 (lookback 적용 후 복리 계산 등)
