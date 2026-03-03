# meta developer: @dsware
# requires: aiohttp Pillow

__version__ = (1, 0, 0)

import asyncio
import io
import json
import logging
import random
import string
import textwrap
import typing

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

import telethon

from .. import loader, utils

logger = logging.getLogger(__name__)

GUIDE_URL = "https://yandex-music.rtfd.io/en/main/token.html"
API_URL = "https://track.mipoh.ru"

DEFAULT_FONT_BOLD = (
    "https://raw.githubusercontent.com/kamekuro/assets/master/fonts/Onest-Bold.ttf"
)
DEFAULT_FONT_REGULAR = (
    "https://raw.githubusercontent.com/kamekuro/assets/master/fonts/Onest-Regular.ttf"
)


@loader.tds
class YaMusicMod(loader.Module):
    """Yandex Music — now playing banner, track download & autobio"""

    strings = {
        "name": "YaMusic",
        "no_token": (
            "<emoji document_id=5019523782004441717>❌</emoji>"
            " <b>Токен не установлен.</b> Используй <code>.yguide</code>"
        ),
        "no_playing": (
            "<emoji document_id=5197226421788904367>🎧</emoji>"
            " <b>Сейчас ничего не играет.</b>"
        ),
        "loading": (
            "<emoji document_id=5451732530048802485>⏳</emoji>"
            " <b>Загрузка...</b>"
        ),
        "autobio_on": (
            "<emoji document_id=5368324170671202286>👍</emoji>"
            " <b>Автобио включено.</b>"
        ),
        "autobio_off": (
            "<emoji document_id=5368324170671202286>👍</emoji>"
            " <b>Автобио выключено.</b>"
        ),
        "guide": (
            "<emoji document_id=5188311512791393083>🔎</emoji>"
            f' <b><a href="{GUIDE_URL}">Гайд по получению токена'
            " Яндекс Музыки</a></b>"
        ),
        "no_download": (
            "<emoji document_id=5019523782004441717>❌</emoji>"
            " <b>Не удалось скачать трек.</b>"
        ),
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "token",
                None,
                lambda: "OAuth-токен Яндекс Музыки",
                validator=loader.validators.Hidden(),
            ),
            # ── Bio ──
            loader.ConfigValue(
                "autobio_text",
                "{artist} — {title}",
                lambda: "Шаблон bio ({artist}, {title})",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "no_playing_bio",
                "",
                lambda: "Bio когда ничего не играет (пусто = не менять)",
                validator=loader.validators.String(),
            ),
            # ── Fonts ──
            loader.ConfigValue(
                "font_bold",
                DEFAULT_FONT_BOLD,
                lambda: "URL шрифта Bold (ttf)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "font_regular",
                DEFAULT_FONT_REGULAR,
                lambda: "URL шрифта Regular (ttf)",
                validator=loader.validators.String(),
            ),
            # ── Font sizes ──
            loader.ConfigValue(
                "title_size",
                80,
                lambda: "Размер шрифта названия трека",
                validator=loader.validators.Integer(minimum=20, maximum=200),
            ),
            loader.ConfigValue(
                "artist_size",
                55,
                lambda: "Размер шрифта артиста",
                validator=loader.validators.Integer(minimum=15, maximum=150),
            ),
            loader.ConfigValue(
                "time_size",
                36,
                lambda: "Размер шрифта таймеров",
                validator=loader.validators.Integer(minimum=10, maximum=100),
            ),
            # ── Colors ──
            loader.ConfigValue(
                "text_color",
                "#FFFFFF",
                lambda: "Цвет текста (title, artist, таймеры)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "bar_color",
                "#FFFFFF",
                lambda: "Цвет заполненной части прогресс бара",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "bar_bg_color",
                "#A0A0A0",
                lambda: "Цвет фона прогресс бара",
                validator=loader.validators.String(),
            ),
            # ── Banner look ──
            loader.ConfigValue(
                "blur_radius",
                14,
                lambda: "Радиус размытия фона",
                validator=loader.validators.Integer(minimum=0, maximum=50),
            ),
            loader.ConfigValue(
                "bg_brightness",
                0.3,
                lambda: "Яркость фона (0.0–1.0)",
                validator=loader.validators.Float(minimum=0.0, maximum=1.0),
            ),
            loader.ConfigValue(
                "cover_radius",
                35,
                lambda: "Радиус скругления обложки",
                validator=loader.validators.Integer(minimum=0, maximum=200),
            ),
        )
        self._font_cache: typing.Dict[str, bytes] = {}
        self._premium: bool = False

    async def client_ready(self, client, db):
        self._client = client
        me = await client.get_me()
        self._premium = getattr(me, "premium", False) or False
        if self.get("autobio", False):
            self.autobio_loop.start()

    # ──────────────────── Ynison WebSocket ────────────────────

    async def _get_ynison(self) -> dict:
        """Connect to Ynison WebSocket, return full player state."""
        device_id = "".join(random.choices(string.ascii_lowercase, k=16))
        ws_proto = {
            "Ynison-Device-Id": device_id,
            "Ynison-Device-Info": json.dumps({"app_name": "Chrome", "type": 1}),
        }

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "wss://ynison.music.yandex.ru/redirector"
                ".YnisonRedirectService/GetRedirectToYnison",
                headers={
                    "Sec-WebSocket-Protocol": (
                        f"Bearer, v2, {json.dumps(ws_proto)}"
                    ),
                    "Origin": "http://music.yandex.ru",
                    "Authorization": f"OAuth {self.config['token']}",
                },
            ) as ws:
                resp = await ws.receive()
                data = json.loads(resp.data)

        ws_proto["Ynison-Redirect-Ticket"] = data["redirect_ticket"]

        payload = {
            "update_full_state": {
                "player_state": {
                    "player_queue": {
                        "current_playable_index": -1,
                        "entity_id": "",
                        "entity_type": "VARIOUS",
                        "playable_list": [],
                        "options": {"repeat_mode": "NONE"},
                        "entity_context": "BASED_ON_ENTITY_BY_DEFAULT",
                        "version": {
                            "device_id": device_id,
                            "version": 9021243204784341000,
                            "timestamp_ms": 0,
                        },
                        "from_optional": "",
                    },
                    "status": {
                        "duration_ms": 0,
                        "paused": True,
                        "playback_speed": 1,
                        "progress_ms": 0,
                        "version": {
                            "device_id": device_id,
                            "version": 8321822175199937000,
                            "timestamp_ms": 0,
                        },
                    },
                },
                "device": {
                    "capabilities": {
                        "can_be_player": True,
                        "can_be_remote_controller": False,
                        "volume_granularity": 16,
                    },
                    "info": {
                        "device_id": device_id,
                        "type": "WEB",
                        "title": "Chrome Browser",
                        "app_name": "Chrome",
                    },
                    "volume_info": {"volume": 0},
                    "is_shadow": True,
                },
                "is_currently_active": False,
            },
            "rid": "ac281c26-a047-4419-ad00-e4fbfda1cba3",
            "player_action_timestamp_ms": 0,
            "activity_interception_type": "DO_NOT_INTERCEPT_BY_DEFAULT",
        }

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                f"wss://{data['host']}/ynison_state"
                ".YnisonStateService/PutYnisonState",
                headers={
                    "Sec-WebSocket-Protocol": (
                        f"Bearer, v2, {json.dumps(ws_proto)}"
                    ),
                    "Origin": "http://music.yandex.ru",
                    "Authorization": f"OAuth {self.config['token']}",
                },
            ) as ws:
                await ws.send_str(json.dumps(payload))
                # First response may be echo of our state,
                # second is the actual player state from server
                ynison = {}
                for _ in range(3):
                    try:
                        resp = await asyncio.wait_for(ws.receive(), timeout=5)
                    except asyncio.TimeoutError:
                        break
                    if resp.type != aiohttp.WSMsgType.TEXT:
                        break
                    candidate = json.loads(resp.data)
                    ynison = candidate
                    # Check if we got real progress data
                    status = (
                        candidate.get("player_state", {})
                        .get("status", {})
                    )
                    if int(status.get("progress_ms", 0)) > 0:
                        break
                return ynison

    # ──────────────────── HTTP API (metadata + download) ────────────────────

    async def _api_get_track(self) -> typing.Optional[dict]:
        """Get track metadata + download_link via track.mipoh.ru."""
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "ya-token": self.config["token"],
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{API_URL}/get_current_track_beta",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                    ssl=False,
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
        except Exception as e:
            logger.error("HTTP API error: %s", e)
            return None

    # ──────────────────── Combined: now playing ────────────────────

    async def _get_now_playing(self) -> typing.Optional[dict]:
        """
        Hybrid approach:
        - Ynison WS → progress_ms, duration_ms, paused, track_id
        - HTTP API  → title, artist, img, download_link
        """
        if not self.config["token"]:
            return None

        # 1. Ynison for progress
        try:
            ynison = await self._get_ynison()
        except Exception as e:
            logger.error("Ynison error: %s", e)
            return None

        queue = ynison.get("player_state", {}).get("player_queue", {})
        playable_list = queue.get("playable_list", [])
        if not playable_list:
            return None

        idx = queue.get("current_playable_index", -1)
        if idx < 0 or idx >= len(playable_list):
            return None

        raw = playable_list[idx]
        if raw.get("playable_type") == "LOCAL_TRACK":
            return None

        status = ynison["player_state"]["status"]
        progress_ms = int(status.get("progress_ms", 0))
        duration_ms = int(status.get("duration_ms", 0))
        paused = status.get("paused", False)
        track_id = raw.get("playable_id", "")

        # 2. HTTP API for metadata
        api_data = await self._api_get_track()
        if not api_data or "track" not in api_data:
            # Fallback: use only Ynison (no metadata)
            return {
                "paused": paused,
                "track_id": track_id,
                "title": track_id,
                "artists": [],
                "img": None,
                "duration_ms": duration_ms,
                "progress_ms": progress_ms,
                "duration_s": duration_ms // 1000,
                "download_url": None,
            }

        t = api_data["track"]

        raw_artist = t.get("artist", "")
        if isinstance(raw_artist, str):
            artists = [x.strip() for x in raw_artist.split(",") if x.strip()]
        elif isinstance(raw_artist, list):
            artists = raw_artist
        else:
            artists = []

        # duration from API (seconds) as fallback
        api_duration_s = int(t.get("duration", 0))
        if duration_ms == 0 and api_duration_s > 0:
            duration_ms = api_duration_s * 1000

        return {
            "paused": paused,
            "track_id": t.get("track_id", track_id),
            "title": t.get("title", "Unknown"),
            "artists": artists,
            "img": t.get("img"),
            "duration_ms": duration_ms,
            "progress_ms": progress_ms,
            "duration_s": duration_ms // 1000,
            "download_url": t.get("download_link"),
        }

    # ──────────────────── Fonts ────────────────────

    async def _load_font(self, url: str) -> bytes:
        if url not in self._font_cache:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    self._font_cache[url] = await resp.read()
        return self._font_cache[url]

    # ──────────────────── Banner ────────────────────

    async def _make_banner(self, now: dict) -> io.BytesIO:
        W, H = 1920, 768
        cover_size = H - 250  # 518

        # Config values
        text_color = self.config["text_color"]
        bar_color = self.config["bar_color"]
        bar_bg_color = self.config["bar_bg_color"]
        blur_radius = self.config["blur_radius"]
        brightness = self.config["bg_brightness"]
        corner_radius = self.config["cover_radius"]

        # Download cover
        cover_url = now.get("img") or ""
        if cover_url and not cover_url.startswith("http"):
            cover_url = f"https://{cover_url}"

        async with aiohttp.ClientSession() as session:
            async with session.get(cover_url) as resp:
                cover_bytes = await resp.read()

        # Load fonts
        bold_bytes = await self._load_font(self.config["font_bold"])
        title_font = ImageFont.truetype(
            io.BytesIO(bold_bytes), self.config["title_size"]
        )
        artist_font = ImageFont.truetype(
            io.BytesIO(bold_bytes), self.config["artist_size"]
        )
        time_font = ImageFont.truetype(
            io.BytesIO(bold_bytes), self.config["time_size"]
        )

        # Background: blurred darkened cover
        cover_img = Image.open(io.BytesIO(cover_bytes)).convert("RGBA")
        bg = (
            cover_img.resize((W, W))
            .crop((0, (W - H) // 2, W, (W - H) // 2 + H))
            .filter(ImageFilter.GaussianBlur(radius=blur_radius))
        )
        banner = ImageEnhance.Brightness(bg).enhance(brightness)
        draw = ImageDraw.Draw(banner)

        # Cover with rounded corners
        cov = cover_img.resize((cover_size, cover_size))
        mask = Image.new("L", cov.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, cov.size[0], cov.size[1]), radius=corner_radius, fill=255
        )
        cov.putalpha(mask)
        cov = cov.crop(cov.getbbox())
        banner.paste(cov, (75, 75), mask)

        # Text area
        space = (643, 75, 1870, 593)

        title_lines = textwrap.wrap(now["title"], width=23)
        if len(title_lines) > 2:
            title_lines = title_lines[:2]
            title_lines[-1] = title_lines[-1][:-1] + "…"

        artist_str = ", ".join(now["artists"])
        artist_lines = textwrap.wrap(artist_str, width=23)
        if len(artist_lines) > 1:
            artist_lines = artist_lines[:1]
            artist_lines[-1] = artist_lines[-1][:-1] + "…"

        lines = title_lines + artist_lines

        def measure(text, font):
            bbox = draw.textbbox((0, 0), text, font=font)
            return bbox[2] - bbox[0], bbox[3] - bbox[1]

        lines_sizes = [
            measure(line, artist_font if i == len(lines) - 1 else title_font)
            for i, line in enumerate(lines)
        ]
        total_h = sum(h for _, h in lines_sizes)
        spacing = self.config["title_size"] + 10
        y = space[1] + (space[3] - space[1] - total_h) / 2

        for i, line in enumerate(lines):
            w, _ = lines_sizes[i]
            font = artist_font if i == len(lines) - 1 else title_font
            x = space[0] + (space[2] - space[0] - w) / 2
            draw.text((x, y), line, font=font, fill=text_color)
            y += spacing

        # Progress bar + timers
        duration = now["duration_ms"] or 1
        progress = now["progress_ms"]

        cur = f"{progress // 1000 // 60:02}:{progress // 1000 % 60:02}"
        total = f"{duration // 1000 // 60:02}:{duration // 1000 % 60:02}"
        draw.text((75, 650), cur, font=time_font, fill=text_color)
        draw.text((1745, 650), total, font=time_font, fill=text_color)

        bar_left, bar_right, bar_y = 75, 1845, 700
        draw.rounded_rectangle(
            [bar_left, bar_y, bar_right, bar_y + 15], radius=7, fill=bar_bg_color
        )
        fill_w = int((bar_right - bar_left) * min(progress / duration, 1.0))
        if fill_w > 0:
            draw.rounded_rectangle(
                [bar_left, bar_y, bar_left + fill_w, bar_y + 15],
                radius=7,
                fill=bar_color,
            )

        out = io.BytesIO()
        banner.save(out, format="PNG")
        out.seek(0)
        out.name = "ynow.png"
        return out

    # ──────────────────── Track download ────────────────────

    async def _download_track(self, now: dict) -> typing.Optional[io.BytesIO]:
        url = now.get("download_url")
        if not url:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=60)
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.read()
        except Exception as e:
            logger.error("Download error: %s", e)
            return None

        buf = io.BytesIO(data)
        buf.name = "track.mp3"
        return buf

    # ──────────────────── Commands ────────────────────

    @loader.command(ru_doc="Баннер текущего трека", alias="yn")
    async def ynowcmd(self, message: telethon.tl.types.Message):
        """Now playing banner"""
        if not self.config["token"]:
            return await utils.answer(message, self.strings["no_token"])

        await utils.answer(message, self.strings["loading"])
        now = await self._get_now_playing()

        if not now:
            return await utils.answer(message, self.strings["no_playing"])

        banner = await self._make_banner(now)
        text = (
            f"<emoji document_id=5431376038628171216>🎵</emoji>"
            f" <b>{', '.join(now['artists'])} — {now['title']}</b>"
        )
        await utils.answer(message=message, response=text, file=banner)

    @loader.command(ru_doc="Скачать текущий трек", alias="yt")
    async def ytrackcmd(self, message: telethon.tl.types.Message):
        """Download current track as mp3"""
        if not self.config["token"]:
            return await utils.answer(message, self.strings["no_token"])

        await utils.answer(message, self.strings["loading"])
        now = await self._get_now_playing()

        if not now:
            return await utils.answer(message, self.strings["no_playing"])

        audio = await self._download_track(now)
        if not audio:
            return await utils.answer(message, self.strings["no_download"])

        text = (
            f"<emoji document_id=5431376038628171216>🎵</emoji>"
            f" <b>{', '.join(now['artists'])} — {now['title']}</b>"
        )
        await utils.answer(
            message=message,
            response=text,
            file=audio,
            attributes=[
                telethon.tl.types.DocumentAttributeAudio(
                    duration=now["duration_s"],
                    title=now["title"],
                    performer=", ".join(now["artists"]),
                )
            ],
        )

    @loader.command(ru_doc="Вкл/выкл автобио", alias="yb")
    async def ybiocmd(self, message: telethon.tl.types.Message):
        """Toggle autobio"""
        if not self.config["token"]:
            return await utils.answer(message, self.strings["no_token"])

        bio = not self.get("autobio", False)
        self.set("autobio", bio)

        if bio:
            self.autobio_loop.start()
            await utils.answer(message, self.strings["autobio_on"])
        else:
            self.autobio_loop.stop()
            if self.config["no_playing_bio"]:
                try:
                    me = await self._client.get_me()
                    limit = 140 if getattr(me, "premium", False) else 70
                    await self._client(
                        telethon.functions.account.UpdateProfileRequest(
                            about=self.config["no_playing_bio"][:limit]
                        )
                    )
                except Exception:
                    pass
            await utils.answer(message, self.strings["autobio_off"])

    @loader.command(ru_doc="Гайд по получению токена", alias="yg")
    async def yguidecmd(self, message: telethon.tl.types.Message):
        """Token guide"""
        await utils.answer(message, self.strings["guide"])

    @loader.command(ru_doc="Отладка — сырые данные Ynison + API")
    async def ydebugcmd(self, message: telethon.tl.types.Message):
        """Debug: raw Ynison + API response"""
        if not self.config["token"]:
            return await utils.answer(message, self.strings["no_token"])

        await utils.answer(message, self.strings["loading"])

        lines = []

        # Ynison
        try:
            ynison = await self._get_ynison()
            status = ynison.get("player_state", {}).get("status", {})
            queue = ynison.get("player_state", {}).get("player_queue", {})
            plist = queue.get("playable_list", [])
            idx = queue.get("current_playable_index", -1)
            cur_track = plist[idx] if 0 <= idx < len(plist) else None

            lines.append("<b>── Ynison ──</b>")
            lines.append(f"progress_ms: <code>{status.get('progress_ms')}</code>")
            lines.append(f"duration_ms: <code>{status.get('duration_ms')}</code>")
            lines.append(f"paused: <code>{status.get('paused')}</code>")
            lines.append(f"playable_list len: <code>{len(plist)}</code>")
            lines.append(f"current_index: <code>{idx}</code>")
            if cur_track:
                lines.append(
                    f"playable_id: <code>{cur_track.get('playable_id')}</code>"
                )
                lines.append(
                    f"playable_type: <code>{cur_track.get('playable_type')}</code>"
                )
        except Exception as e:
            lines.append(f"<b>Ynison error:</b> <code>{e}</code>")

        # HTTP API
        try:
            api = await self._api_get_track()
            if api and "track" in api:
                t = api["track"]
                lines.append("\n<b>── HTTP API ──</b>")
                lines.append(f"progress_ms: <code>{api.get('progress_ms')}</code>")
                lines.append(f"duration: <code>{t.get('duration')}</code>")
                lines.append(f"title: <code>{t.get('title')}</code>")
                lines.append(f"artist: <code>{t.get('artist')}</code>")
                lines.append(f"track_id: <code>{t.get('track_id')}</code>")
                lines.append(
                    f"download_link: <code>"
                    f"{'yes' if t.get('download_link') else 'no'}</code>"
                )
                lines.append(f"img: <code>{'yes' if t.get('img') else 'no'}</code>")
            else:
                lines.append("\n<b>HTTP API:</b> no track data")
        except Exception as e:
            lines.append(f"\n<b>API error:</b> <code>{e}</code>")

        await utils.answer(message, "\n".join(lines))

    # ──────────────────── Autobio loop ────────────────────

    @loader.loop(30)
    async def autobio_loop(self):
        if not self.config["token"]:
            self.autobio_loop.stop()
            self.set("autobio", False)
            return

        try:
            now = await self._get_now_playing()
        except Exception:
            return

        if now and not now.get("paused", False):
            text = self.config["autobio_text"].format(
                artist=", ".join(now["artists"]),
                title=now["title"],
            )
        else:
            text = self.config["no_playing_bio"]
            if not text:
                return

        try:
            me = await self._client.get_me()
            limit = 140 if getattr(me, "premium", False) else 70
            await self._client(
                telethon.functions.account.UpdateProfileRequest(
                    about=text[:limit]
                )
            )
        except telethon.errors.rpcerrorlist.FloodWaitError as e:
            logger.info("Autobio flood wait: %ds", max(e.seconds, 60))
            await asyncio.sleep(max(e.seconds, 60))
        except Exception as e:
            logger.error("Autobio error: %s", e)
