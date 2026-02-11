# Claude Code 활용 가이드 — Survey Stream 개선 워크플로우

## 전체 구조 요약

```
questvoyager/
├── CLAUDE.md                          ← 매 세션 자동 로드 (핵심 규칙만)
├── CLAUDE.local.md                    ← 개인 설정 (gitignore됨)
├── .claude/
│   ├── settings.local.json            ← 권한 설정 (기존)
│   └── commands/                      ← 커스텀 슬래시 커맨드
│       ├── next-task.md               ← /next-task: 다음 작업 시작
│       ├── verify.md                  ← /verify: 현재 작업 검증
│       └── review.md                  ← /review: 코드 리뷰
├── docs/
│   ├── roadmap.md                     ← 작업 목록 + 진행 추적 (체크박스)
│   └── tasks/
│       ├── task-01-pdf-unification.md ← 각 작업의 상세 스펙
│       ├── task-02-summary-type-dedup.md
│       └── ...
└── tests/                             ← 검증용 테스트 코드
```

---

## 왜 이렇게 구성하는가?

### CLAUDE.md를 최소로 유지하는 이유

CLAUDE.md는 **매 세션, 매 메시지마다** 컨텍스트 윈도우에 로드됩니다.
여기에 모든 작업 내용을 넣으면 토큰 낭비 + 핵심 규칙이 묻힙니다.

**CLAUDE.md에 넣는 것**: 프로젝트 구조, 코딩 규칙, 검증 절차
**docs/에 넣는 것**: 로드맵, 작업 스펙, 아키텍처 문서 → 필요할 때만 `@docs/파일명`으로 참조

### docs/tasks/ 작업 스펙의 구조

각 task 파일은 Claude Code가 **자율적으로 작업을 완수**할 수 있도록 설계됩니다:

```markdown
# TASK-NN: 제목

## Status: 🔴 Not Started | 🟡 In Progress | 🟢 Complete

## Problem         ← 왜 이 작업이 필요한지
## Goal            ← 달성해야 할 결과
## Files to Modify ← 영향받는 파일 목록
## Implementation Steps  ← 구체적 단계 (Claude Code가 따라감)
## Do NOT Change   ← 건드리면 안 되는 것 (부작용 방지)
## Verification Checklist  ← 완료 기준 (자동 검증)
## Smoke Test Script       ← 실행 가능한 테스트 코드
```

### 자기 검증이 중요한 이유

Claude Code는 작업을 "완료"라고 보고하면서도 실제로는 에러가 있을 수 있습니다.
Verification Checklist와 Smoke Test가 이를 방지합니다:

1. **import 체인 검증**: 하나의 파일 수정이 다른 파일의 import를 깨뜨릴 수 있음
2. **세션 상태 검증**: Streamlit은 세션 상태가 핵심이므로 타입 확인 필수
3. **회귀 방지**: 기존 DOCX 경로가 영향받지 않는지 확인

---

## 실전 사용법

### 1단계: 프로젝트에 파일 배치

제공된 파일들을 프로젝트 루트에 복사합니다:
```bash
# CLAUDE.md → 프로젝트 루트
# .claude/commands/ → 기존 .claude/ 폴더 안에
# docs/ → 프로젝트 루트에 새로 생성
```

### 2단계: 첫 세션 시작

Claude Code를 프로젝트 디렉토리에서 실행합니다:
```bash
cd C:/GitHub/questvoyager
claude
```

Claude Code가 CLAUDE.md를 자동으로 읽고 프로젝트 컨텍스트를 이해합니다.

### 3단계: 작업 실행

```
> /next-task
```

Claude Code가 다음을 자동으로 수행합니다:
1. `docs/roadmap.md`에서 첫 번째 미완료 작업 찾기
2. 해당 task 스펙 파일 읽기
3. 계획 설명 → 사용자 확인 요청
4. 구현 → 검증 → 결과 보고

### 4단계: 검증 재실행 (필요 시)

```
> /verify
```

작업 후 추가 변경이 있었거나, 검증을 다시 돌리고 싶을 때 사용합니다.

### 5단계: 코드 리뷰

```
> /review
```

커밋 전에 변경 사항을 CLAUDE.md 규칙 기준으로 리뷰합니다.

### 6단계: 세션 종료 & 이어하기

작업이 길어지면 컨텍스트 윈도우가 차기 전에:
```
> /clear
```
로 세션을 초기화한 후 `/next-task`로 이어서 작업합니다.
roadmap.md의 체크박스가 진행 상태를 기억하므로 이전 작업을 다시 하지 않습니다.

---

## 고급 팁

### Plan Mode 활용

복잡한 작업 전에 Plan Mode(Shift+Tab 2회)로 전환하면
Claude Code가 코드를 읽기만 하고 계획을 세웁니다.
계획을 확인한 후 Normal Mode로 돌아가서 실행.

### Extended Thinking

아키텍처 결정이 필요한 작업에서:
```
> think hard about the best approach for TASK-01
```
내부 추론 과정을 더 깊이 수행합니다.

### 새 작업 추가

`docs/roadmap.md`에 항목 추가 + `docs/tasks/`에 스펙 파일 생성.
Claude Code에게 직접 요청할 수도 있습니다:
```
> 새 작업을 만들어줘: Table Guide Builder에서 Banner 추천 근거를 표시하는 기능
```

### CLAUDE.md 업데이트

작업 중 새로운 규칙이 발견되면:
```
> # 새 규칙: Grid 문항의 하위 항목은 is_grid_child=True로 표시할 것
```
`#` 명령으로 CLAUDE.md에 즉시 추가됩니다 (Quick Memory).

---

## 파일별 역할 정리

| 파일 | 로드 시점 | 용도 | 수정 빈도 |
|------|----------|------|----------|
| `CLAUDE.md` | 매 세션 자동 | 핵심 규칙, 프로젝트 구조 | 드물게 |
| `CLAUDE.local.md` | 매 세션 자동 | 개인 환경 설정 (gitignore) | 드물게 |
| `docs/roadmap.md` | `/next-task` 시 | 작업 목록 + 진행 추적 | 매 작업 완료 시 |
| `docs/tasks/*.md` | `/next-task` 시 | 작업 상세 스펙 | 작업 시작 전 1회 |
| `.claude/commands/*.md` | 슬래시 명령 시 | 워크플로우 자동화 | 드물게 |
| `tests/*.py` | `/verify` 시 | 자동 검증 | 작업별 추가 |
