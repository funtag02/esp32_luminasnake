from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .models import AnalysisFrame
from .renderer import frequency_rgb

BAND_EDGES = np.array(
    [20, 60, 120, 250, 500, 1000, 2000, 3500, 6000, 10_000, 15_000, 20_000],
    dtype=float,
)


class SpectrumWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.analysis: AnalysisFrame | None = None

    def set_analysis(self, analysis: AnalysisFrame) -> None:
        self.analysis = analysis
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#10151b"))
        chart = self.rect().adjusted(12, 12, -12, -30)
        painter.setPen(QPen(QColor("#34404c"), 1))
        for fraction in (0.25, 0.5, 0.75, 1.0):
            y = chart.bottom() - chart.height() * fraction
            painter.drawLine(chart.left(), int(y), chart.right(), int(y))
        if self.analysis is None:
            painter.setPen(QColor("#91a0ad"))
            painter.drawText(chart, Qt.AlignCenter, "Start audio capture to display the spectrum")
            return

        bands = np.asarray(self.analysis.bands, dtype=float)
        count = min(len(bands), len(BAND_EDGES) - 1)
        gap = 3.0
        width = (chart.width() - gap * (count - 1)) / max(1, count)
        metrics = QFontMetrics(painter.font())
        for index in range(count):
            level = float(np.clip(bands[index], 0.0, 1.0))
            center_hz = float(np.sqrt(BAND_EDGES[index] * BAND_EDGES[index + 1]))
            rgb = frequency_rgb(center_hz).astype(int)
            color = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
            x = chart.left() + index * (width + gap)
            height = chart.height() * level
            painter.fillRect(QRectF(x, chart.bottom() - height, width, height), color)
            label = self._frequency_label(center_hz)
            label_width = metrics.horizontalAdvance(label)
            painter.setPen(QColor("#aab5bf"))
            painter.drawText(int(x + (width - label_width) / 2), self.height() - 9, label)

        dominant = float(np.clip(self.analysis.dominant_hz, BAND_EDGES[0], BAND_EDGES[-1]))
        position = np.log(dominant / BAND_EDGES[0]) / np.log(BAND_EDGES[-1] / BAND_EDGES[0])
        marker_x = chart.left() + chart.width() * position
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.drawLine(int(marker_x), chart.top(), int(marker_x), chart.bottom())

    @staticmethod
    def _frequency_label(frequency_hz: float) -> str:
        return f"{frequency_hz / 1000:.1f}k" if frequency_hz >= 1000 else f"{frequency_hz:.0f}"
