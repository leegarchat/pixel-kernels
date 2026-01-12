#!/usr/bin/env python3

import argparse
import os
import re
import subprocess
import sys

# Магический заголовок DTB
DTB_HEADER = b"\xd0\x0d\xfe\xed"

def get_readable_name(dtb_path):
    """
    Запускает dtc, читает dts и формирует имя файла по схеме:
    Arg1(compatible) - Arg2(desc_part1) - Arg3(desc_part2)
    Пример: zuma-b0-ipop.dtb
    """
    try:
        # 1. Запускаем dtc для конвертации в текст
        cmd = ["dtc", "-I", "dtb", "-O", "dts", dtb_path]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            return None # Не удалось прочитать как DTB

        dts_content = result.stdout

        # 2. Ищем compatible (Argument 1)
        # Пример: compatible = "google,zuma";
        # Нам нужно "zuma"
        arg1 = "unknown"
        comp_match = re.search(r'compatible\s*=\s*"(.*?)"', dts_content)
        if comp_match:
            raw_comp = comp_match.group(1)
            if "," in raw_comp:
                arg1 = raw_comp.split(",")[1].strip() # берем часть после запятой
            else:
                arg1 = raw_comp.strip()

        # 3. Ищем description (Argument 2 и 3)
        # Пример: description = "B0,IPOP";
        arg2 = "unk"
        arg3 = "unk"
        
        # Ищем строку description. 
        # Примечание: ищем первое вхождение. Если нужно искать строго внутри B0_IPOP,
        # логика усложнится, но обычно description уникален для блока.
        desc_match = re.search(r'description\s*=\s*"(.*?)"', dts_content)
        if desc_match:
            raw_desc = desc_match.group(1) # "B0,IPOP"
            parts = raw_desc.split(',')
            if len(parts) >= 1:
                arg2 = parts[0].strip().lower() # b0
            if len(parts) >= 2:
                arg3 = parts[1].strip().lower() # ipop
        
        # 4. Формируем итоговое имя
        new_name = f"{arg1}-{arg2}-{arg3}.dtb"
        return new_name

    except Exception as e:
        print(f"Ошибка при парсинге {dtb_path}: {e}")
        return None

def dump_file(filename, content):
    with open(filename, "wb") as fp:
        fp.write(content)

def main():
    parser = argparse.ArgumentParser(description="Extract and rename DTBs from kernel image.")
    
    # Новые аргументы
    parser.add_argument("--input", required=True, help="Path to input kernel image/binary")
    parser.add_argument("--out-dir", required=True, help="Directory to save extracted dtbs")
    
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' not found.")
        sys.exit(1)

    # Читаем весь файл в память
    with open(args.input, "rb") as fp:
        content = fp.read()

    # Ищем все смещения заголовков DTB
    positions = []
    dtb_next = content.find(DTB_HEADER)
    while dtb_next != -1:
        positions.append(dtb_next)
        dtb_next = content.find(DTB_HEADER, dtb_next + 1)

    if not positions:
        print("No DTBs found in the input file.")
        sys.exit(0)

    print(f"Found {len(positions)} DTBs. Extracting...")

    os.makedirs(args.out_dir, exist_ok=True)

    # Словарь для предотвращения дубликатов имен
    used_names = {}

    begin_pos = 0
    # Проходим по позициям. Добавляем len(content) как конец последнего блока
    loop_positions = positions + [len(content)]

    # Начинаем со второго элемента (первый блок - это обычно kernel до первого dtb, или мусор)
    # Но если файл начинается сразу с DTB, логика чуть меняется.
    # Используем логику оригинального extract-dtb:
    
    for i in range(len(positions)):
        start = positions[i]
        # Конец текущего dtb - это начало следующего, или конец файла
        end = loop_positions[i+1]
        
        chunk = content[start:end]
        
        # Временное имя
        temp_filename = f"temp_{i:02d}.dtb"
        temp_path = os.path.join(args.out_dir, temp_filename)
        
        # Сохраняем временно, чтобы dtc мог прочитать файл
        dump_file(temp_path, chunk)
        
        # Пытаемся получить красивое имя
        new_name = get_readable_name(temp_path)
        
        if new_name:
            # Обработка дубликатов (если вдруг есть два одинаковых dtb)
            if new_name in used_names:
                used_names[new_name] += 1
                base, ext = os.path.splitext(new_name)
                final_name = f"{base}_{used_names[new_name]}{ext}"
            else:
                used_names[new_name] = 0
                final_name = new_name
            
            final_path = os.path.join(args.out_dir, final_name)
            os.rename(temp_path, final_path)
            print(f"Extracted #{i}: {final_name}")
        else:
            # Если dtc не справился, оставляем базовое имя, но делаем его понятнее
            fallback_name = f"unknown_{i:02d}.dtb"
            final_path = os.path.join(args.out_dir, fallback_name)
            os.rename(temp_path, final_path)
            print(f"Extracted #{i}: {fallback_name} (parsing failed)")

    print(f"\nDone! Extracted files are in: {args.out_dir}")

if __name__ == "__main__":
    main()
