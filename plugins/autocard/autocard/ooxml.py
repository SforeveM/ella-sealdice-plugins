from __future__ import annotations

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image

from .errors import InvalidWorkbookError


MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
DRAW = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
DRAW_MAIN = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"m": MAIN, "r": REL, "p": PKG_REL, "xdr": DRAW, "a": DRAW_MAIN}
COORDINATE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


def column_number(letters: str) -> int:
    value = 0
    for char in letters.upper():
        value = value * 26 + ord(char) - 64
    return value


def split_coordinate(address: str) -> tuple[int, int]:
    match = COORDINATE.fullmatch(address.upper())
    if not match:
        raise ValueError(f"Invalid cell coordinate: {address}")
    return int(match.group(2)), column_number(match.group(1))


def _resolve_target(base: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base), target))


@dataclass(frozen=True, slots=True)
class Cell:
    address: str
    value: object
    formula: str | None
    cached: object
    # Excel stores in-cell Rich Data values (including local images) behind
    # the worksheet cell's ``vm`` attribute.  Keep the raw 1-based metadata
    # index so callers that construct Cells themselves remain compatible.
    metadata_index: int | None = None

    @property
    def effective(self) -> object:
        return self.cached if self.formula is not None else self.value


@dataclass(frozen=True, slots=True)
class EmbeddedImage:
    sheet: str
    row: int
    column: int
    width: int
    height: int
    mime: str
    data: bytes


@dataclass(slots=True)
class Worksheet:
    name: str
    state: str
    path: str
    cells: dict[str, Cell]
    xml: ET.Element

    def get(self, address: str, default: object = None) -> object:
        cell = self.cells.get(address.upper())
        if cell is None:
            return default
        value = cell.effective
        return default if value is None else value

    def cell(self, address: str) -> Cell | None:
        return self.cells.get(address.upper())

    def iter_cells(self):
        return iter(self.cells.values())


class Workbook:
    """Small, dependency-light OOXML reader that preserves cached formula values."""

    MAX_ENTRIES = 8_000
    MAX_MEMBER_BYTES = 90 * 1024 * 1024
    MAX_TOTAL_BYTES = 350 * 1024 * 1024
    MAX_RATIO = 1_500

    def __init__(self, data: bytes, filename: str = "upload.xlsx") -> None:
        self.data = data
        self.filename = Path(filename).name
        self.format = Path(filename).suffix.lower().lstrip(".") or "xlsx"
        try:
            self.archive = zipfile.ZipFile(io.BytesIO(data))
        except (zipfile.BadZipFile, OSError) as exc:
            raise InvalidWorkbookError("文件不是有效的 .xlsx/.xlsm 工作簿") from exc
        self._validate_archive()
        self.shared_strings = self._read_shared_strings()
        self.sheets: dict[str, Worksheet] = {}
        self.sheet_order: list[str] = []
        self._load_sheets()

    @classmethod
    def from_path(cls, path: str | Path):
        source = Path(path)
        return load_workbook(source.read_bytes(), source.name)

    def _validate_archive(self) -> None:
        infos = self.archive.infolist()
        if len(infos) > self.MAX_ENTRIES:
            raise InvalidWorkbookError("工作簿内部文件数量异常")
        total = 0
        for info in infos:
            clean = posixpath.normpath(info.filename.replace("\\", "/"))
            if clean.startswith("../") or clean.startswith("/"):
                raise InvalidWorkbookError("工作簿包含不安全路径")
            if info.file_size > self.MAX_MEMBER_BYTES:
                raise InvalidWorkbookError("工作簿内部单个文件过大")
            total += info.file_size
            if info.compress_size and info.file_size / info.compress_size > self.MAX_RATIO:
                raise InvalidWorkbookError("工作簿压缩率异常")
        if total > self.MAX_TOTAL_BYTES:
            raise InvalidWorkbookError("工作簿解压后过大")
        required = {"[Content_Types].xml", "xl/workbook.xml"}
        if not required.issubset(set(self.archive.namelist())):
            raise InvalidWorkbookError("文件缺少 Excel 工作簿结构")

    def _xml(self, path: str) -> ET.Element:
        try:
            return ET.fromstring(self.archive.read(path))
        except (KeyError, ET.ParseError) as exc:
            raise InvalidWorkbookError(f"无法读取工作簿结构：{path}") from exc

    def _relationships(self, source: str) -> dict[str, str]:
        path = posixpath.join(posixpath.dirname(source), "_rels", posixpath.basename(source) + ".rels")
        if path not in self.archive.namelist():
            return {}
        root = self._xml(path)
        result = {}
        for item in root.findall("p:Relationship", NS):
            if item.attrib.get("TargetMode") == "External":
                continue
            result[item.attrib["Id"]] = _resolve_target(source, item.attrib["Target"])
        return result

    def _read_shared_strings(self) -> list[str]:
        path = "xl/sharedStrings.xml"
        if path not in self.archive.namelist():
            return []
        root = self._xml(path)
        return ["".join(node.text or "" for node in item.findall(".//m:t", NS)) for item in root.findall("m:si", NS)]

    def _parse_scalar(self, cell: ET.Element) -> tuple[object, str | None, object]:
        cell_type = cell.attrib.get("t")
        formula_node = cell.find("m:f", NS)
        value_node = cell.find("m:v", NS)
        inline = cell.find("m:is", NS)
        raw = value_node.text if value_node is not None else None
        if inline is not None:
            cached: object = "".join(node.text or "" for node in inline.findall(".//m:t", NS))
        elif raw is None:
            cached = None
        elif cell_type == "s":
            try:
                cached = self.shared_strings[int(raw)]
            except (ValueError, IndexError):
                cached = raw
        elif cell_type in {"str", "e"}:
            cached = raw
        elif cell_type == "b":
            cached = raw == "1"
        else:
            try:
                cached = float(raw) if "." in raw or "e" in raw.lower() else int(raw)
            except ValueError:
                cached = raw
        formula = formula_node.text if formula_node is not None else None
        value = cached if formula is None else "=" + (formula or "")
        return value, formula, cached

    def _load_sheets(self) -> None:
        workbook_path = "xl/workbook.xml"
        root = self._xml(workbook_path)
        relationships = self._relationships(workbook_path)
        for node in root.findall("m:sheets/m:sheet", NS):
            rel_id = node.attrib.get(f"{{{REL}}}id", "")
            path = relationships.get(rel_id)
            if not path:
                continue
            sheet_xml = self._xml(path)
            cells: dict[str, Cell] = {}
            for cell_node in sheet_xml.findall(".//m:sheetData/m:row/m:c", NS):
                address = cell_node.attrib.get("r", "").upper()
                if not address:
                    continue
                value, formula, cached = self._parse_scalar(cell_node)
                metadata_index = None
                raw_metadata_index = cell_node.attrib.get("vm")
                if raw_metadata_index is not None:
                    try:
                        metadata_index = int(raw_metadata_index)
                    except ValueError:
                        metadata_index = None
                cells[address] = Cell(address, value, formula, cached, metadata_index)
            name = node.attrib["name"]
            self.sheet_order.append(name)
            self.sheets[name] = Worksheet(name, node.attrib.get("state", "visible"), path, cells, sheet_xml)

    def get_sheet(self, name: str) -> Worksheet | None:
        return self.sheets.get(name)

    def get(self, sheet: str, address: str, default: object = None) -> object:
        worksheet = self.get_sheet(sheet)
        return worksheet.get(address, default) if worksheet else default

    def embedded_images(self) -> list[EmbeddedImage]:
        result: list[EmbeddedImage] = []
        for sheet in self.sheets.values():
            sheet_rels = self._relationships(sheet.path)
            for drawing_node in sheet.xml.findall("m:drawing", NS):
                drawing_path = sheet_rels.get(drawing_node.attrib.get(f"{{{REL}}}id", ""))
                if not drawing_path:
                    continue
                drawing = self._xml(drawing_path)
                drawing_rels = self._relationships(drawing_path)
                for anchor in list(drawing.findall("xdr:twoCellAnchor", NS)) + list(drawing.findall("xdr:oneCellAnchor", NS)):
                    start = anchor.find("xdr:from", NS)
                    blip = anchor.find(".//a:blip", NS)
                    if start is None or blip is None:
                        continue
                    media_path = drawing_rels.get(blip.attrib.get(f"{{{REL}}}embed", ""))
                    if not media_path or media_path not in self.archive.namelist():
                        continue
                    data = self.archive.read(media_path)
                    try:
                        with Image.open(io.BytesIO(data)) as image:
                            width, height = image.size
                            mime = Image.MIME.get(image.format, "application/octet-stream")
                    except Exception:
                        continue
                    row_node = start.find("xdr:row", NS)
                    col_node = start.find("xdr:col", NS)
                    result.append(
                        EmbeddedImage(
                            sheet=sheet.name,
                            row=int(row_node.text or "0") if row_node is not None else 0,
                            column=int(col_node.text or "0") if col_node is not None else 0,
                            width=width,
                            height=height,
                            mime=mime,
                            data=data,
                        )
                    )
        result.extend(self._cell_images())
        result.extend(self._rich_data_images())
        return result

    @staticmethod
    def _local_name(tag: str) -> str:
        """Return an XML element's local name regardless of its namespace."""
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _attribute(element: ET.Element, local_name: str) -> str | None:
        """Read an attribute by local name, including namespaced attributes."""
        value = element.attrib.get(local_name)
        if value is not None:
            return value
        for key, candidate in element.attrib.items():
            if key.rsplit("}", 1)[-1] == local_name:
                return candidate
        return None

    def _rich_data_images(self) -> list[EmbeddedImage]:
        """Read Excel's Rich Data local images and attach them to their cells.

        Recent Excel versions save an image placed *inside* a cell as a Rich
        Data value rather than as a drawing or ``DISPIMG`` formula.  The
        worksheet cell's ``vm`` points into ``metadata.xml``; that entry points
        to a rich-value record, whose local image identifier selects a relation
        in ``richValueRel.xml``.  Older workbooks simply do not contain these
        parts, so this is intentionally a no-op for them.
        """
        metadata_path = "xl/metadata.xml"
        rich_values_path = "xl/richData/rdrichvalue.xml"
        rich_structure_path = "xl/richData/rdrichvaluestructure.xml"
        rich_rel_path = "xl/richData/richValueRel.xml"
        if not all(
            path in self.archive.namelist()
            for path in (metadata_path, rich_values_path, rich_structure_path, rich_rel_path)
        ):
            return []

        metadata_root = self._xml(metadata_path)
        metadata_entries: list[int | None] = []
        for node in metadata_root.iter():
            if self._local_name(node.tag) != "valueMetadata":
                continue
            for block in node:
                if self._local_name(block.tag) != "bk":
                    continue
                rich_index = None
                for child in block.iter():
                    if self._local_name(child.tag) != "rc":
                        continue
                    raw = self._attribute(child, "v")
                    try:
                        rich_index = int(raw) if raw is not None else None
                    except ValueError:
                        rich_index = None
                    break
                metadata_entries.append(rich_index)
            break
        if not metadata_entries:
            return []

        structure_root = self._xml(rich_structure_path)
        image_value_index = 0
        for node in structure_root.iter():
            if self._local_name(node.tag) != "s":
                continue
            keys = [child for child in node if self._local_name(child.tag) == "k"]
            for index, key in enumerate(keys):
                name = self._attribute(key, "n") or ""
                if "LocalImageIdentifier" in name:
                    image_value_index = index
                    break
            break

        rich_values_root = self._xml(rich_values_path)
        rich_values: list[list[str]] = []
        for node in rich_values_root.iter():
            if self._local_name(node.tag) != "rv":
                continue
            rich_values.append([
                (child.text or "").strip()
                for child in node
                if self._local_name(child.tag) == "v"
            ])

        rich_rel_root = self._xml(rich_rel_path)
        relation_ids = [
            self._attribute(node, "id")
            for node in rich_rel_root.iter()
            if self._local_name(node.tag) == "rel"
        ]
        relationships = self._relationships(rich_rel_path)
        rich_media: dict[int, str] = {}
        for index, relation_id in enumerate(relation_ids):
            if relation_id and relation_id in relationships:
                rich_media[index] = relationships[relation_id]

        # Cache image decoding because a workbook may reference the same local
        # image from more than one cell or worksheet.
        image_cache: dict[str, tuple[bytes, int, int, str] | None] = {}

        def load_image(media_path: str) -> tuple[bytes, int, int, str] | None:
            if media_path in image_cache:
                return image_cache[media_path]
            if media_path not in self.archive.namelist():
                image_cache[media_path] = None
                return None
            data = self.archive.read(media_path)
            try:
                with Image.open(io.BytesIO(data)) as image:
                    payload = (data, image.width, image.height, Image.MIME.get(image.format, "application/octet-stream"))
            except Exception:
                payload = None
            image_cache[media_path] = payload
            return payload

        result: list[EmbeddedImage] = []
        seen: set[tuple[str, int, int, str]] = set()
        for sheet in self.sheets.values():
            for cell in sheet.iter_cells():
                raw_metadata_index = cell.metadata_index
                if raw_metadata_index is None:
                    continue
                # Worksheet ``vm`` values are 1-based.  Be permissive with
                # malformed/exporter-specific zero-based values as well.
                metadata_slot = raw_metadata_index - 1 if raw_metadata_index > 0 else raw_metadata_index
                if not (0 <= metadata_slot < len(metadata_entries)):
                    continue
                rich_index = metadata_entries[metadata_slot]
                if rich_index is None or not (0 <= rich_index < len(rich_values)):
                    continue
                values = rich_values[rich_index]
                if image_value_index >= len(values):
                    continue
                try:
                    local_image_index = int(values[image_value_index])
                except (TypeError, ValueError):
                    continue
                media_path = rich_media.get(rich_index)
                if not media_path:
                    # The relation list is normally aligned with rich-value
                    # records.  Some exporters store an explicit local index;
                    # accept that as a fallback when it points to a relation.
                    media_path = rich_media.get(local_image_index)
                if not media_path:
                    continue
                row, column = split_coordinate(cell.address)
                key = (sheet.name, row - 1, column - 1, media_path)
                if key in seen:
                    continue
                payload = load_image(media_path)
                if payload is None:
                    continue
                seen.add(key)
                data, width, height, mime = payload
                result.append(
                    EmbeddedImage(
                        sheet=sheet.name,
                        row=row - 1,
                        column=column - 1,
                        width=width,
                        height=height,
                        mime=mime,
                        data=data,
                    )
                )
        return result

    def _cell_images(self) -> list[EmbeddedImage]:
        """Read WPS/Excel in-cell images referenced through DISPIMG formulas."""
        path = "xl/cellimages.xml"
        if path not in self.archive.namelist():
            return []
        root = self._xml(path)
        relationships = self._relationships(path)
        image_by_name: dict[str, tuple[bytes, int, int, str]] = {}
        for picture in root.findall(".//xdr:pic", NS):
            properties = picture.find(".//xdr:cNvPr", NS)
            blip = picture.find(".//a:blip", NS)
            if properties is None or blip is None:
                continue
            name = properties.attrib.get("name", "")
            media_path = relationships.get(blip.attrib.get(f"{{{REL}}}embed", ""))
            if not name or not media_path or media_path not in self.archive.namelist():
                continue
            data = self.archive.read(media_path)
            try:
                with Image.open(io.BytesIO(data)) as image:
                    width, height = image.size
                    mime = Image.MIME.get(image.format, "application/octet-stream")
            except Exception:
                continue
            image_by_name[name] = (data, width, height, mime)

        result: list[EmbeddedImage] = []
        formula_pattern = re.compile(r'DISPIMG\(\s*"([^"]+)"', re.IGNORECASE)
        for sheet in self.sheets.values():
            for cell in sheet.iter_cells():
                if not cell.formula:
                    continue
                match = formula_pattern.search(cell.formula)
                if not match or match.group(1) not in image_by_name:
                    continue
                row, column = split_coordinate(cell.address)
                data, width, height, mime = image_by_name[match.group(1)]
                result.append(
                    EmbeddedImage(
                        sheet=sheet.name,
                        row=row - 1,
                        column=column - 1,
                        width=width,
                        height=height,
                        mime=mime,
                        data=data,
                    )
                )
        return result

    def best_portrait(self, preferred_sheets: tuple[str, ...]) -> EmbeddedImage | None:
        images = self.embedded_images()
        if not images:
            return None
        preferred = [image for image in images if image.sheet in preferred_sheets]
        pool = preferred or images
        candidates = [image for image in pool if image.width >= 160 and image.height >= 160]
        if not candidates:
            return None
        return max(candidates, key=lambda image: min(image.width, image.height) * 3 - abs(image.width - image.height))


def load_workbook(data: bytes, filename: str = "upload.xlsx"):
    if data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        from .legacy_xls import LegacyWorkbook

        return LegacyWorkbook(data, filename)
    return Workbook(data, filename)


def load_workbook_path(path: str | Path):
    source = Path(path)
    return load_workbook(source.read_bytes(), source.name)
