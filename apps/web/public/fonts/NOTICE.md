# Fonts (self-hosted)

- IBM Plex Sans и JetBrains Mono — **variable fonts** (един файл на подмножество
  за всички тегла; @font-face ползва range дескриптори `font-weight: 100 700` /
  `400 800`), подмножества: latin, latin-ext, cyrillic, cyrillic-ext.
- Източник: Google Fonts (fonts.google.com), изтеглени на 2026-10-25 за офлайн
  употреба (Docker без CDN). @font-face блоковете живеят в `apps/web/src/styles.css`.
- Лиценз: SIL Open Font License 1.1 — OFL-IBMPlexSans.txt / OFL-JetBrainsMono.txt.
