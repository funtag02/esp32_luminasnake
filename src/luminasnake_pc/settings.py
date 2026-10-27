from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from platformdirs import user_config_dir

from .models import AudioSource, FpsPolicy, VisualMode


@dataclass(slots=True)
class VirtualStripSettings:
    enabled: bool = True
    mode: str = VisualMode.FULL.value
    length: int = 120

    def validate(self) -> None:
        self.mode = VisualMode(self.mode).value
        self.length = 60 if int(self.length) == 60 else 120


@dataclass(slots=True)
class Settings:
    audio_source: str = AudioSource.LOOPBACK
    audio_device_id: str = "default"
    serial_port: str = "auto"
    output_device_id: str = "default"
    visual_mode: str = VisualMode.FULL
    fps: int = 60
    fps_policy: str = FpsPolicy.LOCKED_60
    offset_ms: int = 0
    lookahead_ms: int = 150
    intensity: float = 1.0
    scroll_speed_pps: float = 30.0
    last_file: str = ""
    device_offsets_ms: dict[str, int] = field(default_factory=dict)
    virtual_strips: list[VirtualStripSettings] = field(default_factory=lambda: [
        VirtualStripSettings(mode=VisualMode.FULL),
        VirtualStripSettings(mode=VisualMode.BASS),
        VirtualStripSettings(mode=VisualMode.LOW_MID),
        VirtualStripSettings(mode=VisualMode.HIGH_MID),
        VirtualStripSettings(mode=VisualMode.HIGH),
    ])

    def validate(self) -> None:
        self.fps = min(120, max(30, int(self.fps)))
        self.fps_policy = FpsPolicy(self.fps_policy).value
        self.offset_ms = min(500, max(-500, int(self.offset_ms)))
        self.device_offsets_ms = {
            str(device): min(500, max(-500, int(offset)))
            for device, offset in self.device_offsets_ms.items()
        }
        self.lookahead_ms = min(500, max(20, int(self.lookahead_ms)))
        intensity = float(self.intensity)
        self.intensity = 1.0 if intensity <= 0.0 else min(2.0, max(0.1, intensity))
        self.scroll_speed_pps = min(120.0, max(1.0, float(self.scroll_speed_pps)))
        self.audio_source = AudioSource(self.audio_source).value
        self.visual_mode = VisualMode(self.visual_mode).value
        self.virtual_strips = [
            item if isinstance(item, VirtualStripSettings)
            else VirtualStripSettings(**item) if isinstance(item, dict)
            else VirtualStripSettings()
            for item in self.virtual_strips[:5]
        ]
        while len(self.virtual_strips) < 5:
            self.virtual_strips.append(VirtualStripSettings())
        for item in self.virtual_strips:
            item.validate()


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(user_config_dir("LuminaSnake", "LuminaSnake")) / "settings.json"

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            allowed = {item.name for item in fields(Settings)}
            settings = Settings(**{key: value for key, value in raw.items() if key in allowed})
            settings.validate()
            return settings
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return Settings()

    def save(self, settings: Settings) -> None:
        settings.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        temporary.replace(self.path)
