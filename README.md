# YaMusic

Yandex Music module for [Hikka](https://github.com/hikariatama/Hikka) userbot.

## Features

- **`.ynow`** — Now playing banner (1920x768 PIL image)
- **`.ytrack`** — Download current track as mp3
- **`.ybio`** — Auto-update Telegram bio with current track
- **`.yguide`** — Token guide
- **`.ydebug`** — Debug: raw Ynison + API data

## Install

```
.dlmod https://raw.githubusercontent.com/tema2637/music/refs/heads/main/YaMusic.py
```

Then configure token: `.cfg YaMusic`

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `token` | — | Yandex Music OAuth token |
| `font_bold` | Onest-Bold | URL for bold font (.ttf) |
| `font_regular` | Onest-Regular | URL for regular font (.ttf) |
| `title_size` | 80 | Title font size |
| `artist_size` | 55 | Artist font size |
| `text_color` | #FFFFFF | Text color |
| `bar_color` | #FFFFFF | Progress bar fill color |
| `bar_bg_color` | #A0A0A0 | Progress bar background |
| `blur_radius` | 14 | Background blur radius |
| `bg_brightness` | 0.3 | Background brightness (0.0-1.0) |
| `cover_radius` | 35 | Cover corner radius |

## How it works

- **Ynison WebSocket** — real-time playback progress (progress_ms, duration_ms, paused)
- **HTTP API** — track metadata (title, artist, cover, download link)
- **PIL** — banner generation: blurred cover background + cover art + text + progress bar
