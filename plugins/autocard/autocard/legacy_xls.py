from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .errors import InvalidWorkbookError
from .ooxml import MAIN, Cell, EmbeddedImage, Worksheet


OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


def _column_letters(number: int) -> str:
    value = ""
    while number > 0:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value or "A"


def _scalar(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


class LegacyWorkbook:
    """Read-only BIFF8/XLS adapter exposing the same surface as the OOXML reader.

    xlrd reads cached cell results and does not execute VBA or formula code.
    """

    MAX_FILE_BYTES = 25 * 1024 * 1024

    def __init__(self, data: bytes, filename: str = "upload.xls") -> None:
        if len(data) > self.MAX_FILE_BYTES:
            raise InvalidWorkbookError("旧版 XLS 文件超过 25 MiB 限制")
        if not data.startswith(OLE_SIGNATURE):
            raise InvalidWorkbookError("文件不是有效的旧版 .xls 工作簿")
        try:
            import xlrd
        except ImportError as exc:  # pragma: no cover - packaging failure only
            raise InvalidWorkbookError("服务缺少旧版 XLS 读取组件 xlrd") from exc
        try:
            book = xlrd.open_workbook(file_contents=data, on_demand=False, formatting_info=False)
        except Exception as exc:
            raise InvalidWorkbookError("无法读取旧版 .xls 工作簿") from exc

        self.data = data
        self.filename = Path(filename).name
        self.format = "xls"
        self.sheets: dict[str, Worksheet] = {}
        self.sheet_order: list[str] = []
        for source in book.sheets():
            cells: dict[str, Cell] = {}
            for row in range(source.nrows):
                for column in range(source.ncols):
                    item = source.cell(row, column)
                    if item.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                        continue
                    address = f"{_column_letters(column + 1)}{row + 1}"
                    value = _scalar(item.value)
                    cells[address] = Cell(address, value, None, value)
            root = ET.Element(f"{{{MAIN}}}worksheet")
            bottom_right = f"{_column_letters(max(1, source.ncols))}{max(1, source.nrows)}"
            ET.SubElement(root, f"{{{MAIN}}}dimension", {"ref": f"A1:{bottom_right}"})
            state = "visible" if getattr(source, "visibility", 0) == 0 else "hidden"
            sheet = Worksheet(source.name, state, "", cells, root)
            self.sheet_order.append(source.name)
            self.sheets[source.name] = sheet

    @classmethod
    def from_path(cls, path: str | Path) -> "LegacyWorkbook":
        source = Path(path)
        return cls(source.read_bytes(), source.name)

    def get_sheet(self, name: str) -> Worksheet | None:
        return self.sheets.get(name)

    def get(self, sheet: str, address: str, default: object = None) -> object:
        worksheet = self.get_sheet(sheet)
        return worksheet.get(address, default) if worksheet else default

    def embedded_images(self) -> list[EmbeddedImage]:
        return []

    def best_portrait(self, preferred_sheets: tuple[str, ...]) -> EmbeddedImage | None:
        return None
