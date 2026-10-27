from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class StripPreviewWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(260)
        self.frames: tuple[np.ndarray, ...] = ()
        self.labels: tuple[str, ...] = ()

    def set_frames(self, frames: tuple[np.ndarray, ...], labels: tuple[str, ...]) -> None:
        self.frames = tuple(np.asarray(frame, dtype=np.uint8).copy() for frame in frames)
        self.labels = labels
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#0d1117"))
        if not self.frames:
            painter.setPen(QColor("#91a0ad"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Start audio to simulate five LED strips")
            return
        margin = 12.0
        label_width = 145.0
        available_width = max(1.0, self.width() - label_width - margin * 2)
        lane_height = max(34.0, (self.height() - margin * 2) / len(self.frames))
        for lane, frame in enumerate(self.frames):
            top = margin + lane * lane_height
            painter.setPen(QColor("#c5d0da"))
            label = self.labels[lane] if lane < len(self.labels) else f"Strip {lane + 1}"
            painter.drawText(QRectF(margin, top, label_width - 8, lane_height), Qt.AlignVCenter, label)
            pixel_width = available_width / max(1, len(frame))
            for index, rgb in enumerate(frame):
                color = QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]))
                painter.fillRect(
                    QRectF(margin + label_width + index * pixel_width,
                           top + 5, max(1.0, pixel_width + 0.2), lane_height - 10),
                    color,
                )
            painter.setPen(QPen(QColor("#34404c"), 1))
            painter.drawRect(QRectF(margin + label_width, top + 5,
                                    available_width, lane_height - 10))
