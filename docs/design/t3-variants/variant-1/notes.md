# Т3 — Вариант 1 „Минимални обвивки над CSS" — СКИЦА (неизпълнен)

Дата: 2026-10-25. Статус: **оркестраторска скица** — прегледът за В1 умря 3× от
„Network connection failed" (провайдърът прекъсваше; виж decision.md). Пълна
реализация липсва; записано е достатъчно, за да се прецени вариантът при
съчетанието и да се довърши при нужда.

## Стратегия

Всеки компонент е тънка типизирана обвивка над CSS класове (модел: `Brand.tsx`):
нула React context, нули портали, нулев focus trap. Състоянието живее у
консуматора; библиотеката само рендерира семантични класове от styles.css.

## API (проектирано)

| Компонент/Hook | Пропсове | Бележка |
|---|---|---|
| `MetricCard` | `label, value, tone?, context?, icon?` | `.card` + `.metric-*`; tone оцветява value |
| `StatusChip` | `tone, children, icon?, flat?` | tone→токен; винаги цвят + текст/икона |
| `Panel` | `title, filters?, actions?, fullscreen?` | върху клас `.panel`; ⛶ = fixed inset 0 |
| `Modal` | `open, onClose, title, children, wide?` | backdrop + Esc; без focus trap |
| `Drawer` | `open, onClose, title, children` | дясна плочка 480px; мобилно 100% |
| `useToasts()` | → `{toasts, push, dismiss}` | стек макс 5, авто-dismiss 6s |
| `ToastStack` | `toasts, onDismiss` | aria-live="polite" |
| `useLivePulse()` | → `{state, pulse, onData}` | decay 1.5s; пулс САМО от onData |
| `LiveIndicator` | `state, pulse, label?` | live/idle/reconnect |

## Контраст (същите числа като В2 — палитрата е обща от Т1)

Статус-текст върху 8% tint върху `--bg-surface`: success 7.89 · warning 8.84 ·
danger 5.48 · info 6.33 · accent 8.10:1; muted върху panel 6.40:1 — всички AA.

## Защо би бил рискован сам

Т6 (топбар LIVE) и Т14 (Toast при действия в Explorer) искат Toast достъпен от
дълбоко вложени деца без prop-drilling → без context всеки консуматор носи свой
стек; Modal без focus trap губи Tab в фона (днес вече се случва, но новата
платформа не бива да го увековечава). Силната страна — миграцията на 18-те
страници става на ediyor по един компонент — се запазва и във В2 чрез прости
пропсове, затова В1 не спечели съчетанието.

## Довършване (ако се наложи)

1–2 ч: реализация по таблицата + ui.css подблоци „Т3" в секции 4.2/4.3/4.5/4.7/4.8.
