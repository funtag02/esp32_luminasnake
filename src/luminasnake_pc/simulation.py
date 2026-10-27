from __future__ import annotations

import numpy as np

from .models import AnalysisFrame, VisualMode
from .renderer import SnakeRenderer
from .settings import VirtualStripSettings


class SimulationBank:
    def __init__(self, configurations: list[VirtualStripSettings]) -> None:
        self.renderers: list[SnakeRenderer] = []
        self.lengths: list[int] = []
        self.configure(configurations)

    def configure(self, configurations: list[VirtualStripSettings]) -> None:
        while len(self.renderers) < len(configurations):
            length = configurations[len(self.renderers)].length
            self.renderers.append(SnakeRenderer(leds=length))
            self.lengths.append(length)
        for index, configuration in enumerate(configurations):
            if self.lengths[index] != configuration.length:
                self.renderers[index] = SnakeRenderer(leds=configuration.length)
                self.lengths[index] = configuration.length

    def render(self, analysis: AnalysisFrame, configurations: list[VirtualStripSettings],
               intensity: float, scroll_speed_pps: float,
               elapsed_seconds: float, elapsed_ns: int | None = None) -> tuple[np.ndarray, ...]:
        self.configure(configurations)
        frames: list[np.ndarray] = []
        for renderer, configuration in zip(self.renderers, configurations, strict=True):
            if configuration.enabled:
                frames.append(renderer.render(
                    analysis,
                    VisualMode(configuration.mode),
                    intensity,
                    scroll_speed_pps,
                    elapsed_seconds,
                    elapsed_ns,
                )[0])
            else:
                renderer.frame.fill(0)
                frames.append(renderer.frame[0].copy())
        return tuple(frames)

    @staticmethod
    def physical_frame(virtual_frame: np.ndarray, strip_count: int,
                       leds_per_strip: int) -> np.ndarray:
        source = np.asarray(virtual_frame, dtype=np.uint8)
        if source.ndim != 2 or source.shape[1] != 3 or source.shape[0] == 0:
            raise ValueError("virtual frame must have shape (leds, 3)")
        indices = np.rint(np.linspace(0, len(source) - 1, leds_per_strip)).astype(int)
        strip = source[indices]
        return np.repeat(strip[np.newaxis, :, :], strip_count, axis=0)
