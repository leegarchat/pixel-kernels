#!/usr/bin/env python3
"""Extract concatenated DTBs from a kernel/vendor_kernel_boot dtb blob.

Works without external `dtc` dependency (pure-python FDT parser),
supports both zuma (Pixel 8, description "B0,IPOP") and
laguna/lga (Pixel 10 / mustang, description "LGA A0" / "LGA B0") formats.
"""

import argparse
import hashlib
import os
import re
import struct
import sys

# Магический заголовок DTB (big-endian 0xd00dfeed)
DTB_HEADER = b"\xd0\x0d\xfe\xed"

# FDT tokens
FDT_BEGIN_NODE = 0x1
FDT_END_NODE = 0x2
FDT_PROP = 0x3
FDT_NOP = 0x4
FDT_END = 0x9

# Короткое имя compatible -> имя для файла.
# Эталон GrapheneOS device_google_laguna-kernels_6.6 держит raw имя:
# google,lga -> lga-a0.dtb, lga-b0.dtb (НЕ laguna-a0.dtb).
SOC_MAP = {
    "zuma": "zuma",
    "lga": "lga",
    "laguna": "lga",
    "malibu": "malibu",
    "komodo": "komodo",
}


def _get_string(strings: bytes, off: int):
    end = strings.index(b"\x00", off)
    return strings[off:end].decode(errors="replace")


def parse_fdt(dtb: bytes):
    """Минимальный разбор FDT. Возвращает (root_props, soc_children).

    root_props: dict prop_name -> list[str] (только для корня).
    soc_children: list[(node_name, description)] для прямых детей
        /soc_compatible в порядке появления.
    Бросает ValueError при невалидной структуре.
    """
    if len(dtb) < 40:
        raise ValueError("too small for FDT header")
    (magic, totalsize, off_struct, off_strings, off_rsvmap, version,
     last_comp, boot_cpuid, size_strings, size_struct) = struct.unpack(
        ">10I", dtb[:40])
    if magic != 0xD00DFEED:
        raise ValueError("bad magic")
    if totalsize != len(dtb):
        raise ValueError(
            f"totalsize mismatch: header={totalsize} actual={len(dtb)}")
    if (off_struct + size_struct > totalsize
            or off_strings + size_strings > totalsize):
        raise ValueError("offsets out of bounds")
    if version < 16:
        raise ValueError(f"unsupported version {version}")

    strings = dtb[off_strings:off_strings + size_strings]
    sblock = dtb[off_struct:off_struct + size_struct]

    pos = 0
    depth = 0
    stack = ["/"]
    root_props = {}
    soc_children = []  # (node_name, description or None)

    def cur_path():
        return stack[-1]

    while pos + 4 <= len(sblock):
        (tok,) = struct.unpack(">I", sblock[pos:pos + 4])
        pos += 4
        if tok == FDT_BEGIN_NODE:
            end = sblock.index(b"\x00", pos)
            name = sblock[pos:end].decode(errors="replace")
            pos = ((end + 1) + 3) // 4 * 4
            parent = stack[-1]
            if parent == "/":
                path = "/" + name if name else "/"
            else:
                path = parent.rstrip("/") + "/" + name
            stack.append(path)
            depth += 1
            # Прямой ребёнок /soc_compatible (глубина 2: / -> soc_compatible -> X)
            if depth == 3 and stack[-2] == "/soc_compatible":
                soc_children.append([name, None])
        elif tok == FDT_END_NODE:
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced END_NODE")
            stack.pop()
        elif tok == FDT_PROP:
            if pos + 8 > len(sblock):
                raise ValueError("truncated PROP header")
            sz, noff = struct.unpack(">2I", sblock[pos:pos + 8])
            pos += 8
            if pos + sz > len(sblock):
                raise ValueError("truncated PROP value")
            val = sblock[pos:pos + sz]
            pos = (pos + sz + 3) // 4 * 4
            try:
                pname = _get_string(strings, noff)
            except (ValueError, IndexError) as e:
                raise ValueError(f"bad prop name off {noff}: {e}")
            path = cur_path()
            if depth == 1:  # свойства корня
                parts = [p.decode(errors="replace")
                         for p in val.split(b"\x00") if p]
                root_props[pname] = parts
            # description прямого ребёнка /soc_compatible
            if depth == 3 and stack[-2] == "/soc_compatible" and pname == "description":
                parts = [p.decode(errors="replace")
                         for p in val.split(b"\x00") if p]
                if soc_children and parts:
                    soc_children[-1][1] = parts[0]
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            if depth != 0:
                raise ValueError("FDT_END with unbalanced depth")
            return root_props, soc_children
        else:
            raise ValueError(f"unknown token 0x{tok:x} at struct off {pos - 4}")
    raise ValueError("no FDT_END token")


def _soc_from_compatible(root_props) -> str:
    """Возвращает (mapped_soc, raw_soc)."""
    raw = "unknown"
    for comp in root_props.get("compatible", []):
        # compatible может быть списком: берём первый "google,X"
        first = comp.split("\x00")[0] if "\x00" in comp else comp
        # иногда несколько строк склеены; берём первую содержащую запятую
        candidates = [c.strip() for c in comp.split(",")]
        if "," in comp:
            raw = comp.split(",")[-1].strip().split("\x00")[0].strip()
            raw = re.split(r"[\s,]", raw)[0].lower()
            break
        elif first.strip():
            raw = re.split(r"[\s,]", first.strip())[0].lower()
    raw = re.sub(r"[^a-z0-9]", "", raw) or "unknown"
    mapped = SOC_MAP.get(raw, raw)
    return mapped, raw


def _tokens_from_description(desc: str, soc_mapped: str, soc_raw: str):
    # Делим и по запятой (zuma "B0,IPOP"), и по пробелу/подчёркиванию (laguna "LGA A0")
    parts = [p.lower() for p in re.split(r"[,;\s_\-]+", desc.strip()) if p]
    # Убираем упоминание самого SoC чтобы не было lga-lga-a0
    drop = {soc_mapped.lower(), soc_raw.lower(), "google"}
    # "lga" <-> "laguna" считаем синонимами
    if soc_mapped == "laguna" or soc_raw in ("lga", "laguna"):
        drop |= {"lga", "laguna"}
    parts = [p for p in parts if p not in drop]
    parts = [re.sub(r"[^a-z0-9]", "", p) for p in parts]
    return [p for p in parts if p]


def get_readable_name(dtb_bytes: bytes):
    """Формирует имя вида zuma-b0-ipop.dtb / lga-a0.dtb.

    Возвращает None если blob не парсится как DTB.
    """
    try:
        root_props, soc_children = parse_fdt(dtb_bytes)
    except (ValueError, struct.error, IndexError):
        return None

    soc_mapped, soc_raw = _soc_from_compatible(root_props)

    desc = None
    node_name = None
    if soc_children:
        node_name = soc_children[0][0]
        desc = soc_children[0][1]

    tokens = []
    if desc:
        tokens = _tokens_from_description(desc, soc_mapped, soc_raw)
    if not tokens and node_name:
        # Fallback на имя ноды: B0_IPOP -> b0-ipop, A0 -> a0
        tokens = [p.lower() for p in re.split(r"[,;\s_\-]+", node_name) if p]
        drop = {soc_mapped.lower(), soc_raw.lower(), "lga", "laguna"}
        tokens = [re.sub(r"[^a-z0-9]", "", p) for p in tokens
                  if p.lower() not in drop]
        tokens = [p for p in tokens if p]

    if tokens:
        name = f"{soc_mapped}-{'-'.join(tokens)}.dtb"
    else:
        name = f"{soc_mapped}.dtb"
    # Финальная санитизация (без пробелов)
    name = name.replace(" ", "-")
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]*\.dtb", name):
        return None
    return name


def find_dtb_blobs(content: bytes):
    """Ищет валидные DTB по заголовку, границы — по totalsize из header.

    Отсекает ложные срабатывания магии внутри payload (валидация через
    parse_fdt) и корректно режет чанки даже с паддингом между DTB.
    Возвращает список (offset, blob_bytes).
    """
    blobs = []
    search_from = 0
    while True:
        off = content.find(DTB_HEADER, search_from)
        if off == -1:
            break
        # totalsize лежит по смещению +4
        if off + 40 <= len(content):
            (totalsize,) = struct.unpack(">I", content[off + 4:off + 8])
            # Sanity: totalsize в пределах остатка файла.
            # (totalsize НЕ обязан быть кратен 4 — проверяем только границы)
            if 40 <= totalsize <= len(content) - off:
                blob = content[off:off + totalsize]
                try:
                    parse_fdt(blob)
                    blobs.append((off, blob))
                    search_from = off + totalsize
                    continue
                except (ValueError, struct.error, IndexError):
                    pass  # ложное срабатывание — идём дальше на +1
        search_from = off + 1
    return blobs


def dump_file(filename, content):
    with open(filename, "wb") as fp:
        fp.write(content)


def main():
    parser = argparse.ArgumentParser(
        description="Extract and rename DTBs from kernel image.")
    parser.add_argument("--input", required=True,
                        help="Path to input kernel image/binary")
    parser.add_argument("--out-dir", required=True,
                        help="Directory to save extracted dtbs")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found.")
        sys.exit(1)

    with open(args.input, "rb") as fp:
        content = fp.read()

    blobs = find_dtb_blobs(content)

    if not blobs:
        print("No DTBs found in the input file.")
        sys.exit(0)

    print(f"Found {len(blobs)} DTBs. Extracting...")

    os.makedirs(args.out_dir, exist_ok=True)

    used_names = {}
    seen_hashes = {}
    extracted = []

    for i, (off, blob) in enumerate(blobs):
        digest = hashlib.sha256(blob).hexdigest()
        if digest in seen_hashes:
            print(f"Skipping #{i} at 0x{off:x}: duplicate of "
                  f"{seen_hashes[digest]}")
            continue

        new_name = get_readable_name(blob)

        if new_name:
            if new_name in used_names:
                used_names[new_name] += 1
                base, ext = os.path.splitext(new_name)
                final_name = f"{base}_{used_names[new_name]}{ext}"
            else:
                used_names[new_name] = 0
                final_name = new_name
        else:
            final_name = f"unknown_{i:02d}.dtb"

        final_path = os.path.join(args.out_dir, final_name)
        dump_file(final_path, blob)
        seen_hashes[digest] = final_name
        extracted.append(final_name)
        if new_name:
            print(f"Extracted #{i} at 0x{off:x} ({len(blob)} bytes): {final_name}")
        else:
            print(f"Extracted #{i} at 0x{off:x} ({len(blob)} bytes): "
                  f"{final_name} (naming fallback)")

    print(f"\nDone! Extracted files are in: {args.out_dir}")


if __name__ == "__main__":
    main()
