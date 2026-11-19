"""Canvas annotations for Packet Tracer topologies.

Packet Tracer keeps the text notes drawn on the logical canvas under
``PHYSICALWORKSPACE/NOTES/NOTE``. A note anchors text at canvas coordinates
and carries a stacking value plus a cluster id:

    <NOTE uuid="{...}">
      <X>116</X><Y>52</Y><Z>40000</Z>
      <TEXT translate="true">10.0.0.1</TEXT>
      <NOTECLUSTERID>1-1</NOTECLUSTERID>
    </NOTE>

Notes with a small Z or an empty cluster id exist in the file but never show
up on the canvas, so both are set the way Packet Tracer's own notes are.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET

from . import edit

__all__ = ["NoteError", "add_note", "notes", "set_note_text", "remove_note"]


class NoteError(Exception):
    """Raised when a note cannot be placed."""


def _notes_container(root: ET.Element) -> ET.Element:
    workspace = root.find("PHYSICALWORKSPACE")
    if workspace is None:
        raise NoteError("file has no PHYSICALWORKSPACE element")
    container = workspace.find("NOTES")
    if container is None:
        container = ET.SubElement(workspace, "NOTES")
    return container


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text_of(note: ET.Element) -> str:
    element = note.find("TEXT")
    if element is None or element.text is None:
        return ""
    return element.text


def notes(root: ET.Element) -> list[dict]:
    """List the canvas annotations in document order."""
    container = root.find("PHYSICALWORKSPACE/NOTES")
    if container is None:
        return []
    result = []
    for note in container.findall("NOTE"):
        result.append(
            {
                "uuid": note.get("uuid", ""),
                "x": _float(note.findtext("X")),
                "y": _float(note.findtext("Y")),
                "z": _float(note.findtext("Z")),
                "text": _text_of(note),
            }
        )
    return result


def add_note(
    root: ET.Element,
    text: str,
    *,
    x: float,
    y: float,
    z: float | None = None,
    anchor_device: str | None = None,
    dx: float = 0.0,
    dy: float = -60.0,
) -> dict:
    """Append a canvas note, optionally anchored next to a device.

    Anchoring reads ``WORKSPACE/LOGICAL/X|Y`` from the device, the same
    coordinate space notes use, and offsets by ``dx``/``dy`` so the label does
    not cover the device icon.
    """
    if not text:
        raise NoteError("note text must not be empty")
    if anchor_device is not None:
        device = edit.device(root, anchor_device)
        logical = device.find("WORKSPACE/LOGICAL")
        if logical is None:
            raise NoteError(f"{anchor_device} has no logical workspace position")
        x = _float(logical.findtext("X")) + dx
        y = _float(logical.findtext("Y")) + dy
    container = _notes_container(root)
    if z is None:
        z = 40000 + len(container.findall("NOTE"))
    note = ET.SubElement(container, "NOTE", {"uuid": "{" + str(uuid.uuid4()) + "}"})
    ET.SubElement(note, "X").text = f"{x:g}"
    ET.SubElement(note, "Y").text = f"{y:g}"
    ET.SubElement(note, "Z").text = f"{z:g}"
    ET.SubElement(note, "TEXT", {"translate": "true"}).text = text
    ET.SubElement(note, "NOTECLUSTERID").text = "1-1"
    return {"uuid": note.get("uuid"), "x": x, "y": y, "z": z, "text": text}


def _note_at(root: ET.Element, index: int) -> ET.Element:
    container = root.find("PHYSICALWORKSPACE/NOTES")
    if container is None:
        raise NoteError("file has no notes")
    notes_list = container.findall("NOTE")
    if not 0 <= index < len(notes_list):
        raise NoteError(f"note index {index} out of range (0..{len(notes_list) - 1})")
    return notes_list[index]


def set_note_text(root: ET.Element, index: int, text: str) -> dict:
    """Replace the text of the note at ``index`` (0-based, document order)."""
    note = _note_at(root, index)
    element = note.find("TEXT")
    if element is None:
        element = ET.SubElement(note, "TEXT", {"translate": "true"})
    element.text = text
    return {"uuid": note.get("uuid", ""), "text": text}


def remove_note(root: ET.Element, index: int) -> dict:
    note = _note_at(root, index)
    removed = {"uuid": note.get("uuid", ""), "text": _text_of(note)}
    container = root.find("PHYSICALWORKSPACE/NOTES")
    container.remove(note)
    return removed
