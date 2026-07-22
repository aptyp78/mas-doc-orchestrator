"""Format Detector Agent — определяет формат входного материала и стратегию обработки.

Агент решает:
1. Какой формат у входного материала (PDF, PPTX, DOCX, PNG, JPG, HTML, ...)
2. Нужна ли конвертация
3. В какой формат конвертировать (не всегда PDF)
4. Как передать в pipeline

Стратегии:
- "direct" — напрямую в pipeline (PDF, изображения)
- "convert_to_pdf" — конвертация в PDF (PPTX, DOCX, HTML)
- "convert_to_images" — конвертация в изображения (редко)

Для изображений (PNG/JPG) работает напрямую без конвертации в PDF,
т.к. изображения — это уже примитивы L0.
"""

from __future__ import annotations

import mimetypes
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


class FormatDetectorAgent:
    """Агент определения формата входного материала."""
    
    # Поддерживаемые форматы и их стратегии
    FORMAT_STRATEGIES = {
        # Нативные форматы pipeline (без конвертации)
        ".pdf": "direct",
        ".png": "direct",
        ".jpg": "direct",
        ".jpeg": "direct",
        
        # Форматы, требующие конвертации в PDF
        ".pptx": "convert_to_pdf",
        ".ppt": "convert_to_pdf",
        ".docx": "convert_to_pdf",
        ".doc": "convert_to_pdf",
        ".html": "convert_to_pdf",
        ".htm": "convert_to_pdf",
        ".md": "convert_to_pdf",
        ".rtf": "convert_to_pdf",
        ".txt": "convert_to_pdf",
        
        # Форматы, требующие конвертации в изображения (редко)
        ".svg": "convert_to_images",
    }
    
    def __init__(self, temp_dir: str = "/tmp/format_detector"):
        """Инициализация агента.
        
        Args:
            temp_dir: временная директория для конвертированных файлов
        """
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
    
    def detect(self, file_path: str) -> dict:
        """Определяет формат и стратегию обработки.
        
        Args:
            file_path: путь к входному файлу
        
        Returns:
            dict с format, mime_type, strategy, needs_conversion
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Определение формата по расширению
        ext = file_path.suffix.lower()
        format_name = ext.lstrip(".")
        
        # Определение MIME-type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        
        # Определение стратегии
        strategy = self.FORMAT_STRATEGIES.get(ext, "convert_to_pdf")
        
        # Нужна ли конвертация
        needs_conversion = strategy != "direct"
        
        return {
            "format": format_name,
            "extension": ext,
            "mime_type": mime_type,
            "strategy": strategy,
            "needs_conversion": needs_conversion,
            "original_path": str(file_path),
        }
    
    def process(self, file_path: str) -> str:
        """Обрабатывает файл и возвращает путь к готовому материалу.
        
        Args:
            file_path: путь к входному файлу
        
        Returns:
            Путь к файлу, готовому для pipeline (PDF или изображение)
        """
        detection = self.detect(file_path)
        
        if not detection["needs_conversion"]:
            # Прямая передача в pipeline
            print(f"  ✅ Формат {detection['format']}: напрямую в pipeline")
            return detection["original_path"]
        
        # Конвертация
        if detection["strategy"] == "convert_to_pdf":
            return self._convert_to_pdf(file_path, detection["format"])
        elif detection["strategy"] == "convert_to_images":
            return self._convert_to_images(file_path, detection["format"])
        else:
            raise ValueError(f"Unknown strategy: {detection['strategy']}")
    
    def _convert_to_pdf(self, file_path: str, format_name: str) -> str:
        """Конвертирует файл в PDF через LibreOffice.
        
        Args:
            file_path: путь к входному файлу
            format_name: формат файла
        
        Returns:
            Путь к конвертированному PDF
        """
        print(f"  🔄 Конвертация {format_name} → PDF...")
        
        output_path = self.temp_dir / f"{Path(file_path).stem}.pdf"
        
        # Используем LibreOffice для конвертации
        try:
            result = subprocess.run(
                [
                    "soffice",
                    "--headless",
                    "--convert-to", "pdf",
                    "--outdir", str(self.temp_dir),
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice conversion failed: {result.stderr}")
            
            # Проверяем, что PDF создан
            if not output_path.exists():
                raise FileNotFoundError(f"PDF not created: {output_path}")
            
            print(f"  ✅ PDF создан: {output_path}")
            return str(output_path)
        
        except FileNotFoundError:
            raise RuntimeError(
                "LibreOffice not found. Install with: brew install --cask libreoffice"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice conversion timeout (120s)")
    
    def _convert_to_images(self, file_path: str, format_name: str) -> str:
        """Конвертирует файл в изображения (для SVG и подобных).
        
        Args:
            file_path: путь к входному файлу
            format_name: формат файла
        
        Returns:
            Путь к директории с изображениями
        """
        print(f"  🔄 Конвертация {format_name} → изображения...")
        
        # Для SVG используем rsvg-convert или ImageMagick
        output_dir = self.temp_dir / f"{Path(file_path).stem}_images"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # TODO: Реализовать конвертацию SVG в PNG
        # Для сейчас возвращаем оригинальный файл
        print(f"  ⚠️ Конвертация {format_name} не реализована, используем оригинал")
        return file_path
    
    def cleanup(self):
        """Очищает временную директорию."""
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
            print(f"  🧹 Временная директория очищена: {self.temp_dir}")


# Convenience function
def prepare_for_pipeline(file_path: str) -> str:
    """Подготавливает файл для pipeline (определяет формат и конвертирует если нужно).
    
    Args:
        file_path: путь к входному файлу
    
    Returns:
        Путь к файлу, готовому для pipeline
    """
    agent = FormatDetectorAgent()
    return agent.process(file_path)
