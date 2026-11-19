"""Read and rewrite the HTTP pages a Packet Tracer Server serves.

Packet Tracer stores each server's web root as a file system inside the
device element: ``FILES/FILE[NAME=http:]/FILES/FILE[NAME=index.html]`` whose
``FILE_CONTENT/TEXT`` holds the HTML source. That means the page can be replaced
offline, without touching the GUI.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from . import edit

__all__ = ["WebError", "list_pages", "read_page", "set_page"]


class WebError(RuntimeError):
    pass


_NAME = "http:"


def _http_root(device_element: ET.Element) -> ET.Element:
    for files in device_element.iter("FILES"):
        for entry in files.findall("FILE"):
            if (entry.findtext("NAME") or "").strip().lower() == _NAME:
                return entry
    raise WebError("this device has no HTTP file system (is it a Server-PT?)")


def _page(node: ET.Element, name: str) -> ET.Element:
    want = name.strip().lower()
    for entry in _http_root(node).iter("FILE"):
        if (entry.findtext("NAME") or "").strip().lower() == want:
            return entry
    raise WebError(f"no page named {name!r} on this server")


def list_pages(path: str) -> dict:
    root = edit.load(path)
    device = _pick_server(root)
    node = edit.device(root, device)
    names = [
        (entry.findtext("NAME") or "").strip()
        for entry in _http_root(node).iter("FILE")
        if (entry.findtext("NAME") or "").strip().lower() != _NAME
        and entry.find("FILE_CONTENT") is not None
        and (entry.findtext("NAME") or "").strip()
    ]
    return {"device": device, "pages": names}


def _pick_server(root: ET.Element) -> str:
    servers = []
    for name, element in edit.devices(root).items():
        if _token(element) == "server":
            servers.append(name.strip())
    if not servers:
        raise WebError("this topology has no Server-PT device")
    return servers[0]


def _token(device: ET.Element) -> str:
    engine = device.find("ENGINE")
    if engine is None:
        return ""
    type_node = engine.find("TYPE")
    return (type_node.text or "").strip().lower() if type_node is not None else ""


def read_page(path: str, device: str | None = None, name: str = "index.html") -> dict:
    root = edit.load(path)
    target = device or _pick_server(root)
    node = edit.device(root, target)
    page = _page(node, name)
    content = page.find("FILE_CONTENT")
    text = content.findtext("TEXT") if content is not None else ""
    return {"device": target, "page": name, "html": text or ""}


def set_page(
    path: str,
    html: str,
    *,
    device: str | None = None,
    name: str = "index.html",
    out: str | None = None,
) -> dict:
    root = edit.load(path)
    target = device or _pick_server(root)
    node = edit.device(root, target)
    page = _page(node, name)
    content = page.find("FILE_CONTENT")
    if content is None:
        content = ET.SubElement(page, "FILE_CONTENT")
        content.set("class", "CHttpPage")
    text_node = content.find("TEXT")
    if text_node is None:
        text_node = ET.SubElement(content, "TEXT")
    text_node.text = html
    target_path = edit.save(root, out or path)
    return {"device": target, "page": name, "bytes": len(html), "path": str(target_path)}


