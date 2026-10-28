#!/usr/bin/env python3
"""Sunroom screen: labwc settings for the full-screen browser.

Edits ~/.config/labwc/rc.xml (first copying /etc/xdg/labwc/rc.xml when the user has no
file of their own, or starting a minimal one) so that:

* a <windowRule identifier="chromium*"> moves the pointer to the bottom-right corner and
  hides it when the browser opens (labwc-actions(5): WarpCursor since labwc 0.8.3,
  HideCursor since 0.8.4; older versions log and ignore them; touch input itself hides
  the pointer since 0.8.2), and
* touch screens deliver real touch events instead of emulated mouse clicks, so finger
  scrolling and multi-touch work in Chromium (<touch mouseEmulation="no"/>, labwc 0.8.2+).
  Raspberry Pi OS turns mouse emulation on per device in two places: its system rc.xml
  (for the official DSI panels) and its "autotouch" login helper, which adds an entry for
  a lone touch screen unless rc.xml already has a line matching "touch.*mouseEmulation".
  labwc picks the last matching <touch> entry and runs with --merge-config on Raspberry
  Pi OS, so entries in the user file override the system file.

With --rotate N (Sunroom Screen's Rotation, docs/M7.md T7), touch follows the turned picture:
with --output, Sunroom's own <touch> entries map to that output, and wlroots turns touch with
the output's transform; without an output, a libinput calibration matrix for touch devices
turns it instead (the matrices in docs/KIOSK.md). Never both, so touch is never turned twice.

Each change is made once (a second run changes nothing). Before the first edit of a file
the user wrote, a copy is kept as rc.xml.sunroom-backup. With --remove, the backup is put
back if nothing else changed since; otherwise only Sunroom's own elements are taken out.

Standard library only (xml.etree.ElementTree): comments inside the document, element order
and attribute order survive; comments outside the root element and the exact spelling of
the XML declaration do not. Part of kiosk/; see docs/PLAN.md §13.2 and §17 (risk 5).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

MARK = "sunroom-kiosk"
# Unverified: Chromium's exact Wayland app_id on Raspberry Pi OS ("chromium" or
# "chromium-browser"); the glob matches both, case-insensitively (labwc-config(5)).
RULE_IDENTIFIER = "chromium*"
OPENBOX_NS = "http://openbox.org/3.4/rc"
# Raspberry Pi's own tools (autotouch, raindrop) look for this root element and namespace.
MINIMAL_RC = f'<?xml version="1.0" encoding="UTF-8"?>\n<openbox_config xmlns="{OPENBOX_NS}">\n</openbox_config>\n'
BACKUP_SUFFIX = ".sunroom-backup"
TRUE_WORDS = {"yes", "true", "on", "1"}  # what labwc's parse_tristate() accepts as true
# libinput's calibration matrix for touch on a picture turned N degrees (docs/KIOSK.md).
MATRICES = {90: "0 -1 1 1 0 0", 180: "-1 0 1 0 -1 1", 270: "0 1 0 -1 0 1"}
HOME = os.path.expanduser("~")


class Doc:
    """A parsed rc.xml with its default namespace (empty for <labwc_config>)."""

    def __init__(self, root: ET.Element) -> None:
        self.root = root
        self.ns = namespace(root.tag)
        # The file's own indent step (a tab in files written by Raspberry Pi's tools).
        self.unit = indent_of(root.text) if len(root) and indent_of(root.text) else "  "

    def q(self, name: str) -> str:
        return f"{{{self.ns}}}{name}" if self.ns else name


def say(message: str) -> None:
    print(message)


def tidy(path: str) -> str:
    return "~" + path[len(HOME) :] if path.startswith(HOME + os.sep) else path


def namespace(tag: object) -> str:
    if isinstance(tag, str) and tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def local_name(tag: object) -> str:
    """The element name without its namespace; "" for comments."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def is_comment(node: ET.Element) -> bool:
    return node.tag is ET.Comment


def is_marker(node: ET.Element) -> bool:
    return is_comment(node) and (node.text or "").strip().startswith(MARK)


def parse_root(source: str, from_text: bool = False) -> Doc:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    if from_text:
        parser.feed(source)
        root = parser.close()
    else:
        root = ET.parse(source, parser=parser).getroot()
    if local_name(root.tag) not in ("labwc_config", "openbox_config"):
        raise ValueError(f"it starts with <{local_name(root.tag)}>, not <labwc_config> or <openbox_config>")
    return Doc(root)


# labwc reads options as attributes or as child elements, with case-insensitive names.
def find_key(element: ET.Element, key: str) -> tuple[str | None, ET.Element | None]:
    wanted = key.lower()
    for name in element.attrib:
        if name.lower() == wanted:
            return name, None
    for child in element:
        if local_name(child.tag).lower() == wanted:
            return None, child
    return None, None


def get_key(element: ET.Element, key: str) -> str | None:
    name, child = find_key(element, key)
    if name is not None:
        return element.attrib[name]
    if child is not None:
        return (child.text or "").strip()
    return None


def set_key(element: ET.Element, key: str, value: str | None) -> None:
    name, child = find_key(element, key)
    if child is not None:
        if value is None:
            element.remove(child)
        else:
            child.text = value
        return
    name = name or key
    if value is None:
        element.attrib.pop(name, None)
    else:
        element.set(name, value)


def is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUE_WORDS


# Whitespace handling, so inserted elements line up with their neighbours.
def indent_of(whitespace: str | None) -> str | None:
    if whitespace and "\n" in whitespace and not whitespace.strip():
        return whitespace.rsplit("\n", 1)[1]
    return None


def child_indent(parent: ET.Element, parent_indent: str, unit: str = "  ") -> str:
    if len(parent):
        found = indent_of(parent.text)
        if found is not None:
            return found
    return parent_indent + unit


def append_child(doc: Doc, parent: ET.Element, node: ET.Element, parent_indent: str) -> None:
    indent = child_indent(parent, parent_indent, doc.unit)
    if len(parent):
        last = parent[-1]
        closing = last.tail if indent_of(last.tail) is not None else "\n" + parent_indent
        last.tail = "\n" + indent
        node.tail = closing
    else:
        parent.text = "\n" + indent
        node.tail = "\n" + parent_indent
    parent.append(node)


def remove_child(parent: ET.Element, node: ET.Element) -> None:
    children = list(parent)
    index = children.index(node)
    if index == len(children) - 1:
        if index > 0:
            children[index - 1].tail = node.tail
        else:
            parent.text = None
    parent.remove(node)


def marker(label: str, what: str) -> ET.Element:
    return ET.Comment(f" {MARK} ({label}): {what} ")


def is_our_rule(element: ET.Element) -> bool:
    if local_name(element.tag) != "windowRule":
        return False
    if (get_key(element, "identifier") or "").lower() != RULE_IDENTIFIER:
        return False
    actions = {(a.get("name") or "").lower() for a in element if local_name(a.tag) == "action"}
    return {"warpcursor", "hidecursor"} <= actions


def touches(doc: Doc) -> list[ET.Element]:
    return [child for child in doc.root if local_name(child.tag) == "touch"]


def device_of(element: ET.Element) -> str:
    return get_key(element, "deviceName") or ""


def is_default_touch(element: ET.Element) -> bool:
    """labwc treats a <touch> as the fallback only when it has no deviceName at all."""
    return find_key(element, "deviceName") == (None, None)


def looks_ours(node: ET.Element) -> bool:
    if is_our_rule(node):
        return True
    if local_name(node.tag) == "libinput":
        return True  # only ever one after Sunroom's own marker
    return local_name(node.tag) == "touch" and (get_key(node, "mouseEmulation") or "").strip().lower() == "no"


def serialize(doc: Doc) -> str:
    if doc.ns:
        ET.register_namespace("", doc.ns)
    body = ET.tostring(doc.root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body.rstrip() + "\n"


def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def write_doc(doc: Doc, path: str) -> str:
    """Write atomically, keeping the file's permissions; returns the new content's hash."""
    data = serialize(doc)
    ET.fromstring(data)  # never write something that does not parse
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o644
    fd, tmp = tempfile.mkstemp(prefix=".rc.xml.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def load_state(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def drop_state(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def load_system(path: str) -> Doc | None:
    if not os.path.isfile(path):
        return None
    try:
        return parse_root(path)
    except (ET.ParseError, ValueError, OSError):
        return None


def ensure_rule(doc: Doc, label: str, state: dict, changes: list[str]) -> None:
    root_indent = child_indent(doc.root, "", doc.unit)
    rules = next((c for c in doc.root if local_name(c.tag) == "windowRules"), None)
    if rules is None:
        rules = ET.Element(doc.q("windowRules"))
        append_child(doc, doc.root, rules, "")
        state["created_window_rules"] = True
    elif any(is_our_rule(rule) for rule in rules):
        return
    rule_indent = child_indent(rules, root_indent, doc.unit)
    rule = ET.Element(doc.q("windowRule"), {"identifier": RULE_IDENTIFIER})
    warp = ET.SubElement(rule, doc.q("action"), {"name": "WarpCursor", "to": "output", "x": "-1", "y": "-1"})
    hide = ET.SubElement(rule, doc.q("action"), {"name": "HideCursor"})
    rule.text = "\n" + rule_indent + doc.unit
    warp.tail = "\n" + rule_indent + doc.unit
    hide.tail = "\n" + rule_indent
    append_child(doc, rules, marker(label, "move the pointer to a corner and hide it over the screen"), root_indent)
    append_child(doc, rules, rule, root_indent)
    changes.append("Added a rule that hides the mouse pointer when the screen opens.")


def add_touch(doc: Doc, attributes: dict[str, str], label: str, what: str) -> None:
    append_child(doc, doc.root, marker(label, what), "")
    append_child(doc, doc.root, ET.Element(doc.q("touch"), attributes), "")


def ensure_touch(doc: Doc, system: Doc | None, label: str, state: dict, changes: list[str]) -> None:
    changed = state.setdefault("touch_changed", [])
    count = 0
    for entry in touches(doc):
        value = get_key(entry, "mouseEmulation")
        # autotouch skips files with a touch line naming mouseEmulation, so the default
        # entry always spells it out.
        if is_true(value) or (is_default_touch(entry) and value is None):
            set_key(entry, "mouseEmulation", "no")
            changed.append(
                {"deviceName": device_of(entry), "mapToOutput": get_key(entry, "mapToOutput") or "", "before": value}
            )
            count += 1

    if not any(is_default_touch(entry) for entry in touches(doc)):
        add_touch(doc, {"mouseEmulation": "no"}, label, "real touch events (multi-touch) for every touch screen")
        count += 1

    if system is not None:
        known = {device_of(entry).lower() for entry in touches(doc)}
        for entry in touches(system):
            name = device_of(entry)
            if not name or name.lower() in known or not is_true(get_key(entry, "mouseEmulation")):
                continue
            attributes = {"deviceName": name}
            output = get_key(entry, "mapToOutput")
            if output:
                attributes["mapToOutput"] = output
            attributes["mouseEmulation"] = "no"
            add_touch(doc, attributes, label, f"real touch events for {name}")
            known.add(name.lower())
            count += 1

    if count:
        changes.append(
            "Turned on finger scrolling and multi-touch for touch screens "
            f"(mouseEmulation=no; {count} setting{'s' if count != 1 else ''} changed or added)."
        )


def ours_after_marker(doc: Doc) -> list[ET.Element]:
    """The elements Sunroom added: each right after one of its marker comments."""
    children = list(doc.root)
    return [
        children[index + 1]
        for index, node in enumerate(children)
        if is_marker(node) and index + 1 < len(children) and looks_ours(children[index + 1])
    ]


def ensure_rotation(doc: Doc, label: str, rotate: int, output: str, changes: list[str]) -> None:
    ours = ours_after_marker(doc)
    touch_entries = [node for node in ours if local_name(node.tag) == "touch"]
    mapped = output if rotate else ""
    moved = False
    for entry in touch_entries:
        if (entry.get("mapToOutput") or "") == mapped:
            continue
        moved = True
        if mapped:
            entry.set("mapToOutput", mapped)
        else:
            entry.attrib.pop("mapToOutput", None)
    if moved:
        changes.append(f"Touch now follows the screen {mapped}." if mapped else "Touch follows the whole desktop again.")
    # The matrix only when no output can be named: never turn touch twice.
    wanted = MATRICES.get(rotate) if rotate and not output else None
    current = next((node for node in ours if local_name(node.tag) == "libinput"), None)
    if current is not None:
        matrix = current.find(f".//{doc.q('calibrationMatrix')}")
        if wanted and matrix is not None and (matrix.text or "").strip() == wanted:
            return
        children = list(doc.root)
        index = children.index(current)
        remove_child(doc.root, current)
        if index > 0 and is_marker(children[index - 1]):
            remove_child(doc.root, children[index - 1])
        if not wanted:
            changes.append("Took out the touch turning for a turned picture.")
    if wanted:
        block = ET.Element(doc.q("libinput"))
        device = ET.SubElement(block, doc.q("device"), {"category": "touch"})
        matrix = ET.SubElement(device, doc.q("calibrationMatrix"))
        matrix.text = wanted
        indent = child_indent(doc.root, "", doc.unit)
        block.text = "\n" + indent + doc.unit
        device.text = "\n" + indent + doc.unit * 2
        matrix.tail = "\n" + indent + doc.unit
        device.tail = "\n" + indent
        append_child(doc, doc.root, marker(label, f"turn touch with the picture ({rotate} degrees)"), "")
        append_child(doc, doc.root, block, "")
        changes.append(f"Touch now turns with the picture ({rotate} degrees).")


def install(args: argparse.Namespace) -> int:
    rc, label = args.rc, f"installer {args.installer_version}"
    state = load_state(args.state)
    backup = rc + BACKUP_SUFFIX
    changes: list[str] = []
    notes: list[str] = []

    if os.path.exists(rc):
        try:
            doc = parse_root(rc)
        except (ET.ParseError, ValueError, OSError) as exc:
            say(f"Could not read {tidy(rc)} ({exc}), so it was left alone.")
            say("The screen still works, but the pointer may show and multi-touch may be off.")
            return 2
        with open(rc, encoding="utf-8", errors="replace") as f:
            pristine = MARK not in f.read()
        if os.path.exists(backup):
            state["backup"] = backup
        elif pristine:
            state["pending_backup"] = True
    else:
        system_text = None
        if os.path.isfile(args.system_rc):
            with open(args.system_rc, encoding="utf-8", errors="replace") as f:
                system_text = f.read()
        try:
            doc = parse_root(system_text, from_text=True) if system_text else parse_root(MINIMAL_RC, from_text=True)
            source = f"the desktop's defaults in {args.system_rc}" if system_text else "a minimal file"
        except (ET.ParseError, ValueError):
            doc, source = parse_root(MINIMAL_RC, from_text=True), "a minimal file"
        state["created"] = True
        notes.append(f"Created {tidy(rc)} from {source}.")

    ensure_rule(doc, label, state, changes)
    ensure_touch(doc, load_system(args.system_rc), label, state, changes)
    if args.rotate is not None:
        ensure_rotation(doc, label, args.rotate, args.output or "", changes)

    if not changes and os.path.exists(rc):
        state.pop("pending_backup", None)
        if state:
            state.setdefault("rc", rc)
            save_state(args.state, state)
        say(f"Nothing to change in {tidy(rc)}; the screen's settings are already there.")
        return 0

    if state.pop("pending_backup", False):
        shutil.copy2(rc, backup)
        state["backup"] = backup
        notes.append(f"Saved your previous settings as {tidy(backup)}.")
    state["rc"] = rc
    state["sha256"] = write_doc(doc, rc)
    save_state(args.state, state)
    for line in notes + changes:
        say(line)
    return 0


def remove_marked(doc: Doc) -> int:
    removed = 0
    parents = [doc.root] + [c for c in doc.root if local_name(c.tag) == "windowRules"]
    for parent in parents:
        children = list(parent)
        for index, node in enumerate(children):
            if not is_marker(node):
                continue
            following = children[index + 1] if index + 1 < len(children) else None
            if following is not None and looks_ours(following) and following in list(parent):
                remove_child(parent, following)
                removed += 1
            remove_child(parent, node)
    return removed


def restore_touch(doc: Doc, records: list) -> int:
    restored = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        device = (record.get("deviceName") or "").lower()
        output = record.get("mapToOutput") or ""
        for entry in touches(doc):
            if device_of(entry).lower() != device or (get_key(entry, "mapToOutput") or "") != output:
                continue
            if (get_key(entry, "mouseEmulation") or "").strip().lower() == "no":
                set_key(entry, "mouseEmulation", record.get("before"))
                restored += 1
            break
    return restored


def remove(args: argparse.Namespace) -> int:
    rc = args.rc
    state = load_state(args.state)
    backup = state.get("backup") or rc + BACKUP_SUFFIX
    has_backup = os.path.exists(backup)

    if not os.path.exists(rc):
        if has_backup:
            os.replace(backup, rc)
            say(f"Put back your previous {tidy(rc)}.")
        else:
            say(f"Nothing to remove: {tidy(rc)} does not exist.")
        drop_state(args.state)
        return 0

    if state.get("sha256") and state.get("sha256") == sha256_file(rc):
        if has_backup:
            os.replace(backup, rc)
            say(f"Put back your previous {tidy(rc)} (only Sunroom had changed it).")
            drop_state(args.state)
            return 0
        if state.get("created"):
            os.remove(rc)
            say(f"Removed {tidy(rc)}; the installer had created it.")
            drop_state(args.state)
            return 0

    try:
        doc = parse_root(rc)
    except (ET.ParseError, ValueError, OSError) as exc:
        say(f"Could not read {tidy(rc)} ({exc}); remove the lines marked '{MARK}' by hand.")
        return 2
    removed = remove_marked(doc)
    restored = restore_touch(doc, state.get("touch_changed", []))
    rules = next((c for c in doc.root if local_name(c.tag) == "windowRules"), None)
    if rules is not None and len(rules) == 0 and state.get("created_window_rules", True):
        remove_child(doc.root, rules)
    if removed or restored:
        write_doc(doc, rc)
        say(f"Took Sunroom's pointer and touch settings out of {tidy(rc)}; your other changes stay.")
    else:
        say(f"No Sunroom settings found in {tidy(rc)}.")
    if has_backup:
        say(f"Your copy from before Sunroom is still at {tidy(backup)}; delete it if you don't need it.")
    drop_state(args.state)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Add (or with --remove, take out) the Sunroom screen's labwc settings.",
    )
    parser.add_argument("--remove", action="store_true", help="undo what an earlier run added")
    parser.add_argument("--rc", default=os.path.join(HOME, ".config", "labwc", "rc.xml"), help="the user's rc.xml")
    parser.add_argument("--system-rc", default="/etc/xdg/labwc/rc.xml", help="the desktop's default rc.xml")
    parser.add_argument(
        "--state",
        default=os.path.join(HOME, ".local", "state", "sunroom-kiosk", "labwc-rule.json"),
        help="where to remember what was changed",
    )
    parser.add_argument("--installer-version", default="dev", help="written into the marker comments")
    parser.add_argument(
        "--rotate",
        type=int,
        choices=[0, 90, 180, 270],
        default=None,
        help="the picture's rotation: touch is turned to follow it",
    )
    parser.add_argument("--output", default="", help="the screen's connector (HDMI-A-1), with --rotate")
    args = parser.parse_args(argv)
    return remove(args) if args.remove else install(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
