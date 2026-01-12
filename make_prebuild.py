#!/usr/bin/env python3

import os
import sys
import argparse
import shutil
import subprocess
import glob
import tempfile
import time
from pathlib import Path
import gzip # Import gzip explicitly

# === Цвета для вывода ===
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

# === Глобальные настройки ===
DEBUG_MODE = False
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRACT_DTB_SCRIPT = os.path.join(SCRIPT_DIR, "extractdtb.py") # Предполагаемое имя скрипта из шага 1

# === Вспомогательные функции ===

def log(message, color=Colors.OKBLUE):
    print(f"{color}{message}{Colors.ENDC}")

def run_cmd(command, cwd=None, shell=False, check=True):
    """Запускает команду оболочки. Вывод скрыт, если нет флага --debug."""
    try:
        stdout_dest = subprocess.PIPE if not DEBUG_MODE else None
        stderr_dest = subprocess.PIPE if not DEBUG_MODE else None
        
        if DEBUG_MODE:
            print(f"{Colors.WARNING}[CMD] {command} (cwd={cwd}){Colors.ENDC}")

        # Если command передана как строка и shell=False, разбиваем её (если это не сложная команда)
        if isinstance(command, str) and not shell:
            import shlex
            command = shlex.split(command)

        result = subprocess.run(
            command,
            cwd=cwd,
            shell=shell,
            stdout=stdout_dest,
            stderr=stderr_dest,
            text=True,
            check=check
        )
        return True
    except subprocess.CalledProcessError as e:
        # Если check=True, мы попадем сюда. 
        # Если check=False, subprocess.run не вызовет исключение, но вернет result с returncode.
        log(f"Ошибка при выполнении команды: {command}", Colors.WARNING)
        if not DEBUG_MODE:
             # Выводим ошибку, даже если debug выключен, чтобы понять причину
            if e.stdout: print(f"STDOUT: {e.stdout}")
            if e.stderr: print(f"STDERR: {e.stderr}")
        return False

def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def copy_file(src, dst):
    """Копирует файл с обработкой исключений."""
    try:
        if os.path.isdir(dst):
            shutil.copy2(src, dst)
        else:
            shutil.copy2(src, dst)
        if DEBUG_MODE:
            print(f"Copied: {src} -> {dst}")
    except Exception as e:
        log(f"Ошибка копирования {src} -> {dst}: {e}", Colors.FAIL)

def find_files(directory, pattern):
    """Рекурсивный поиск файлов."""
    return glob.glob(os.path.join(directory, "**", pattern), recursive=True)

def mount_image(image_path, mount_point):
    """Монтирует образ в указанную папку (требует sudo)."""
    log(f"   Монтирование {os.path.basename(image_path)}...", Colors.OKBLUE)
    # Используем mount -o loop,ro. Требует прав суперпользователя.
    cmd = f"sudo mount -o loop,ro {image_path} {mount_point}"
    return run_cmd(cmd, shell=True)

def unmount_image(mount_point):
    """Размонтирует образ."""
    log(f"   Размонтирование {mount_point}...", Colors.OKBLUE)
    cmd = f"sudo umount {mount_point}"
    # Игнорируем ошибки размонтирования, если вдруг уже размонтировано
    subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# === Основные шаги ===

def step_1_system_dlkm(tmp_dir, input_dir, out_dir):
    log("\n[Шаг 1] Обработка system_dlkm.img", Colors.HEADER)
    img_path = os.path.join(input_dir, "system_dlkm.img")
    mnt_dir = os.path.join(tmp_dir, "mnt_system")
    ensure_dir(mnt_dir)

    if mount_image(img_path, mnt_dir):
        try:
            # 1. Найти *.ko (кроме 16k-mode)
            ko_files = find_files(mnt_dir, "*.ko")
            count = 0
            for f in ko_files:
                if "16k-mode" not in f:
                    copy_file(f, out_dir)
                    count += 1
            log(f"   Скопировано модулей (.ko): {count}", Colors.OKGREEN)

            # 2. modules.blocklist
            blocklists = find_files(mnt_dir, "modules.blocklist")
            dest_blocklist = os.path.join(out_dir, "system_dlkm.modules.blocklist")
            if blocklists:
                copy_file(blocklists[0], dest_blocklist)
                log("   Найден и скопирован modules.blocklist", Colors.OKGREEN)
            else:
                Path(dest_blocklist).touch()
                log("   modules.blocklist не найден. Создан пустой файл.", Colors.WARNING)

            # 3. modules.load
            loads = find_files(mnt_dir, "modules.load")
            dest_load = os.path.join(out_dir, "system_dlkm.modules.load")
            if loads:
                copy_file(loads[0], dest_load)
                log("   Найден и скопирован modules.load", Colors.OKGREEN)
            else:
                 log("   modules.load не найден!", Colors.FAIL)

        finally:
            unmount_image(mnt_dir)
    else:
        log("Не удалось примонтировать system_dlkm.img", Colors.FAIL)

def step_2_vendor_dlkm(tmp_dir, input_dir, out_dir):
    log("\n[Шаг 2] Обработка vendor_dlkm.img", Colors.HEADER)
    img_path = os.path.join(input_dir, "vendor_dlkm.img")
    mnt_dir = os.path.join(tmp_dir, "mnt_vendor")
    ensure_dir(mnt_dir)

    if mount_image(img_path, mnt_dir):
        try:
            # 1. Найти *.ko (кроме 16k-mode)
            ko_files = find_files(mnt_dir, "*.ko")
            count = 0
            for f in ko_files:
                if "16k-mode" not in f:
                    copy_file(f, out_dir)
                    count += 1
            log(f"   Скопировано модулей (.ko): {count}", Colors.OKGREEN)

            # 2. modules.blocklist
            blocklists = find_files(mnt_dir, "modules.blocklist")
            dest_blocklist = os.path.join(out_dir, "vendor_dlkm.modules.blocklist")
            if blocklists:
                copy_file(blocklists[0], dest_blocklist)
                log("   Найден и скопирован modules.blocklist", Colors.OKGREEN)
            else:
                Path(dest_blocklist).touch()
                log("   modules.blocklist не найден. Создан пустой файл.", Colors.WARNING)

            # 3. modules.load
            loads = find_files(mnt_dir, "modules.load")
            dest_load = os.path.join(out_dir, "vendor_dlkm.modules.load")
            if loads:
                copy_file(loads[0], dest_load)
                log("   Найден и скопирован modules.load", Colors.OKGREEN)

            # 4. init.insmod* в корне etc/ (не глубже)
            etc_dir = os.path.join(mnt_dir, "etc")
            if os.path.exists(etc_dir):
                # glob не рекурсивно
                insmods = glob.glob(os.path.join(etc_dir, "init.insmod*"))
                for f in insmods:
                    copy_file(f, out_dir)
                log(f"   Скопировано init.insmod файлов: {len(insmods)}", Colors.OKGREEN)

        finally:
            unmount_image(mnt_dir)
    else:
        log("Не удалось примонтировать vendor_dlkm.img", Colors.FAIL)

def step_3_vendor_kernel_boot(tmp_dir, input_dir, out_dir):
    log("\n[Шаг 3] Обработка vendor_kernel_boot.img", Colors.HEADER)
    
    # Рабочая папка для этого шага
    work_dir = os.path.join(tmp_dir, "vkb_extract")
    ensure_dir(work_dir)
    
    # Копируем img
    src_img = os.path.join(input_dir, "vendor_kernel_boot.img")
    copy_file(src_img, work_dir)
    
    # Распаковка
    log("   Распаковка образа через magiskboot...", Colors.OKBLUE)
    # magiskboot может вернуть ошибку на некоторых форматах, но распаковать ramdisk. 
    # Ставим check=False и проверяем результат вручную.
    run_cmd("magiskboot unpack vendor_kernel_boot.img", cwd=work_dir, check=False)
    
    # Извлечение cpio
    cpio_files = find_files(work_dir, "*.cpio")
    if cpio_files:
        # Используем полный путь к найденному CPIO, так как он может быть в подпапке
        cpio_path = cpio_files[0]
        cpio_name = os.path.basename(cpio_path)
        log(f"   Извлечение CPIO архива: {cpio_name} (из {cpio_path})", Colors.OKBLUE)
        
        # Извлекаем CPIO. Используем полный путь к cpio, cwd остается work_dir, 
        # чтобы файлы извлекались в корень рабочей папки.
        run_cmd(f"magiskboot cpio {cpio_path} extract", cwd=work_dir)
        
        # 1. Найти *.ko
        ko_files = find_files(work_dir, "*.ko")
        count = 0
        for f in ko_files:
            if "16k-mode" not in f:
                copy_file(f, out_dir)
                count += 1
        
        if count == 0:
            log(f"   Внимание: Модулей (.ko) не найдено в ramdisk!", Colors.WARNING)
        else:
            log(f"   Скопировано модулей (.ko): {count}", Colors.OKGREEN)
        
        # 2. modules.blocklist
        blocklists = find_files(work_dir, "modules.blocklist")
        dest_blocklist = os.path.join(out_dir, "vendor_kernel_boot.modules.blocklist")
        if blocklists:
            copy_file(blocklists[0], dest_blocklist)
            log("   Найден и скопирован modules.blocklist", Colors.OKGREEN)
        else:
            Path(dest_blocklist).touch()
            log("   modules.blocklist не найден. Создан пустой файл.", Colors.WARNING)
            
        # 3. modules.load -> modules.load
        loads = find_files(work_dir, "modules.load")
        dest_load = os.path.join(out_dir, "modules.load")
        dest_load_2 = os.path.join(out_dir, "vendor_kernel_boot.modules.load")
        if loads:
            copy_file(loads[0], dest_load)
            copy_file(loads[0], dest_load_2)
            log("   Найден и скопирован modules.load и vendor_kernel_boot.modules.load", Colors.OKGREEN)
    else:
        log("   CPIO файл не найден внутри vendor_kernel_boot.img (возможно, ошибка распаковки)", Colors.FAIL)

    return work_dir # Возвращаем путь, так как там лежат распакованные dtb для шага 3.1

def step_3_1_process_dtb(vkb_work_dir, out_dir):
    log("\n[Шаг 3.1] Обработка DTB", Colors.HEADER)
    
    # Ищем dtb в распакованном vkb
    dtb_candidates = glob.glob(os.path.join(vkb_work_dir, "dtb"))
    
    if not dtb_candidates:
        log("   Файл 'dtb' не найден в vendor_kernel_boot.", Colors.WARNING)
        return []

    dtb_src = dtb_candidates[0]
    
    # Проверка наличия внешнего скрипта
    if not os.path.exists(EXTRACT_DTB_SCRIPT):
        log(f"   Ошибка: Скрипт {EXTRACT_DTB_SCRIPT} не найден!", Colors.FAIL)
        return []

    # Запускаем скрипт extractdtb.py
    log(f"   Запуск extractdtb.py для {dtb_src}...", Colors.OKBLUE)
    
    # Запускаем скрипт
    cmd = [sys.executable, EXTRACT_DTB_SCRIPT, "--input", dtb_src, "--out-dir", out_dir]
    run_cmd(cmd) 
    
    # Ищем все .dtb файлы в выходной папке (независимо от того, были они там или создались)
    all_dtbs = glob.glob(os.path.join(out_dir, "*.dtb"))
    
    # Исключаем dtb.img и просто dtb, если они вдруг попали под маску (хотя у них нет расширения .dtb)
    final_dtbs = [os.path.basename(f) for f in all_dtbs if f.endswith(".dtb")]
    
    log(f"   Всего DTB файлов в выходной папке: {len(final_dtbs)}", Colors.OKGREEN)
    
    # Копируем исходный dtb как dtb.img и dtb
    copy_file(dtb_src, os.path.join(out_dir, "dtb.img"))
    copy_file(dtb_src, os.path.join(out_dir, "dtb"))
    
    return final_dtbs

def step_4_boot_img(tmp_dir, input_dir, out_dir):
    log("\n[Шаг 4] Обработка boot.img", Colors.HEADER)
    work_dir = os.path.join(tmp_dir, "boot_extract")
    ensure_dir(work_dir)
    
    src_boot = os.path.join(input_dir, "boot.img")
    copy_file(src_boot, work_dir)
    
    log("   Распаковка boot.img...", Colors.OKBLUE)
    run_cmd("magiskboot unpack boot.img", cwd=work_dir)
    
    # Ищем kernel
    if os.path.exists(os.path.join(work_dir, "kernel")):
        log("   Ядро (kernel) найдено.", Colors.OKGREEN)
        
        # Копируем как Image
        copy_file(os.path.join(work_dir, "kernel"), os.path.join(out_dir, "Image"))
        
        # Сжимаем lz4
        log("   Сжатие kernel в Image.lz4...", Colors.OKBLUE)
        # ВАЖНО: out_dir теперь абсолютный путь, поэтому ошибки "No such file" не будет
        run_cmd(f"magiskboot compress=lz4_legacy kernel {os.path.join(out_dir, 'Image.lz4')}", cwd=work_dir)
        
        # Сжимаем gz
        log("   Сжатие kernel в Image.gz...", Colors.OKBLUE)
        
        # Используем модуль gzip, удалив старый код с os.popen
        with open(os.path.join(work_dir, "kernel"), 'rb') as f_in:
            with gzip.open(os.path.join(out_dir, "Image.gz"), 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
                
    else:
        log("   Файл kernel не найден в boot.img!", Colors.FAIL)
        
    # Копируем сам boot.img
    copy_file(src_boot, os.path.join(out_dir, "boot.img"))

def step_5_custom_kernel(tmp_dir, input_dir, out_dir, img_arg, dtb_created_files):
    log("\n[Шаг 5] Интеграция кастомного ядра (AnyKernel/Image)", Colors.HEADER)
    
    repacker_dir = os.path.join(tmp_dir, "repacker")
    ensure_dir(repacker_dir)
    
    # Копируем оригинальный boot.img в repacker для основы
    orig_boot = os.path.join(input_dir, "boot.img")
    copy_file(orig_boot, repacker_dir)
    
    kernel_source = None
    is_zip = img_arg.lower().endswith(".zip")
    
    if is_zip:
        log(f"   Обработка ZIP архива: {img_arg}", Colors.OKBLUE)
        zip_extract_dir = os.path.join(tmp_dir, "zip_extract")
        ensure_dir(zip_extract_dir)
        run_cmd(f"unzip -o {img_arg} -d {zip_extract_dir}")
        
        # Поиск ядра (Image, kernel, zImage)
        candidates = ["Image", "kernel", "zImage", "Image.gz", "Image.lz4"]
        found_kernel = None
        
        # Ищем рекурсивно или в корне
        for root, dirs, files in os.walk(zip_extract_dir):
            for f in files:
                if f in candidates:
                    found_kernel = os.path.join(root, f)
                    break
            if found_kernel: break
            
        if found_kernel:
            log(f"   Найдено ядро в ZIP: {found_kernel}", Colors.OKGREEN)
            decompressed_kernel = os.path.join(repacker_dir, "kernel")
            
            # Проверка типа файла через 'file'
            is_raw = False
            try:
                res = subprocess.run(["file", found_kernel], capture_output=True, text=True)
                # Raw Image обычно содержит "Linux kernel ... boot executable"
                if "boot executable" in res.stdout and "Linux kernel" in res.stdout:
                    is_raw = True
            except Exception:
                pass

            if is_raw:
                log("   Определен формат RAW Image. Копируем...", Colors.OKBLUE)
                copy_file(found_kernel, decompressed_kernel)
            else:
                # Пытаемся разжать
                if not run_cmd(f"magiskboot decompress {found_kernel} {decompressed_kernel}", check=False):
                    log("   Не удалось разжать (возможно, raw format). Копируем как есть...", Colors.WARNING)
                    copy_file(found_kernel, decompressed_kernel)
            
            kernel_source = decompressed_kernel
        else:
            log("   Ядро не найдено внутри ZIP!", Colors.FAIL)
            return

        # Шаг 5.2 - DTB в ZIP
        # Ищем dtb или dtb.img
        found_dtb = None
        for root, dirs, files in os.walk(zip_extract_dir):
            for f in ["dtb", "dtb.img"]:
                if f in files:
                    found_dtb = os.path.join(root, f)
                    break
        
        if found_dtb:
            log(f"   Найден DTB в ZIP: {found_dtb}. Обновляем...", Colors.OKBLUE)
            
            # Удаляем старые файлы (теперь dtb_created_files содержит полный список)
            if dtb_created_files:
                log(f"   Удаление старых DTB файлов ({len(dtb_created_files)} шт)...", Colors.OKBLUE)
                for f in dtb_created_files:
                    f_path = os.path.join(out_dir, f)
                    if os.path.exists(f_path):
                        os.remove(f_path)
            else:
                log("   Старых DTB файлов для удаления не найдено.", Colors.WARNING)
            
            # Копируем новый
            copy_file(found_dtb, os.path.join(out_dir, "dtb.img"))
            copy_file(found_dtb, os.path.join(out_dir, "dtb"))
            
            # Запускаем extractdtb снова
            cmd = [sys.executable, EXTRACT_DTB_SCRIPT, "--input", found_dtb, "--out-dir", out_dir]
            run_cmd(cmd)
            log("   DTB обновлен и распакован.", Colors.OKGREEN)
            
    else:
        # Это сырой образ
        log(f"   Обработка файла образа: {img_arg}", Colors.OKBLUE)
        decompressed_kernel = os.path.join(repacker_dir, "kernel")
        
        # Проверка типа файла через 'file'
        is_raw = False
        try:
            res = subprocess.run(["file", img_arg], capture_output=True, text=True)
            if "boot executable" in res.stdout and "Linux kernel" in res.stdout:
                is_raw = True
        except Exception:
            pass

        if is_raw:
             log("   Определен формат RAW Image. Копируем...", Colors.OKBLUE)
             copy_file(img_arg, decompressed_kernel)
        else:
            # Пытаемся разжать. Если не выходит (например, формат raw), копируем как есть.
            if not run_cmd(f"magiskboot decompress {img_arg} {decompressed_kernel}", check=False):
                log("   Не удалось разжать (возможно, raw format). Копируем как есть...", Colors.WARNING)
                copy_file(img_arg, decompressed_kernel)
            
        kernel_source = decompressed_kernel

    # Repack
    if kernel_source and os.path.exists(os.path.join(repacker_dir, "kernel")):
        log("   Пересборка boot.img с новым ядром...", Colors.OKBLUE)
        # magiskboot repack <boot.img> (он берет kernel из текущей папки repacker)
        run_cmd(f"magiskboot repack boot.img", cwd=repacker_dir)
        
        new_boot = os.path.join(repacker_dir, "new-boot.img")
        if os.path.exists(new_boot):
            log("   new-boot.img успешно создан.", Colors.OKGREEN)
            # Копируем с заменой в out
            copy_file(new_boot, os.path.join(out_dir, "boot.img"))
            
            # Обновляем Image файлы в out
            copy_file(os.path.join(repacker_dir, "kernel"), os.path.join(out_dir, "Image"))
            run_cmd(f"magiskboot compress=lz4_legacy kernel {os.path.join(out_dir, 'Image.lz4')}", cwd=repacker_dir)
            
            import gzip
            with open(os.path.join(repacker_dir, "kernel"), 'rb') as f_in:
                with gzip.open(os.path.join(out_dir, "Image.gz"), 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            log("   Выходные файлы Image/boot.img обновлены.", Colors.OKGREEN)
        else:
            log("   Ошибка: new-boot.img не был создан.", Colors.FAIL)

# === Main ===

def main():
    parser = argparse.ArgumentParser(description="Подготовка prebuilt ядра и модулей.")
    parser.add_argument("--input", required=True, help="Папка с img файлами")
    parser.add_argument("--out", required=True, help="Выходная папка")
    parser.add_argument("--img", required=False, help="Кастомное ядро (zip или img)")
    parser.add_argument("--debug", action="store_true", help="Показывать stdout команд")
    
    args = parser.parse_args()
    
    # Превращаем пути в абсолютные сразу же
    args.input = os.path.abspath(args.input)
    args.out = os.path.abspath(args.out)
    if args.img:
        args.img = os.path.abspath(args.img)
    
    global DEBUG_MODE
    DEBUG_MODE = args.debug

    # Проверка входных файлов
    required_files = [
        "vendor_kernel_boot.img", "dtbo.img", "vendor_dlkm.img", 
        "system_dlkm.img", "boot.img"
    ]
    
    missing_files = []
    for f in required_files:
        if not os.path.exists(os.path.join(args.input, f)):
            missing_files.append(f)
            
    if missing_files:
        log(f"Ошибка: Отсутствуют файлы во входной папке: {', '.join(missing_files)}", Colors.FAIL)
        sys.exit(1)

    # Проверка наличия extractdtb.py
    if not os.path.exists(EXTRACT_DTB_SCRIPT):
        log(f"Внимание: Скрипт {EXTRACT_DTB_SCRIPT} не найден. Шаги с DTB могут завершиться ошибкой.", Colors.WARNING)

    ensure_dir(args.out)
    
    # Копируем dtbo.img сразу (он не требует обработки по ТЗ, но должен быть проверен)
    # Копируем его как dtbo и как dtbo.img без обработки
    src_dtbo = os.path.join(args.input, "dtbo.img")
    copy_file(src_dtbo, os.path.join(args.out, "dtbo.img"))
    copy_file(src_dtbo, os.path.join(args.out, "dtbo"))
    log("   Скопирован dtbo.img (как dtbo и dtbo.img)", Colors.OKGREEN)

    # Создаем временную директорию
    with tempfile.TemporaryDirectory() as tmp_dir:
        log(f"Временная папка: {tmp_dir}", Colors.HEADER)
        
        try:
            # Шаг 1
            step_1_system_dlkm(tmp_dir, args.input, args.out)
            
            # Шаг 2
            step_2_vendor_dlkm(tmp_dir, args.input, args.out)
            
            # Шаг 3 (возвращает папку, где лежит распакованный dtb)
            vkb_extract_dir = step_3_vendor_kernel_boot(tmp_dir, args.input, args.out)
            
            # Шаг 3.1 (возвращает список созданных файлов)
            dtb_files = step_3_1_process_dtb(vkb_extract_dir, args.out)
            
            # Шаг 4
            step_4_boot_img(tmp_dir, args.input, args.out)
            
            # Шаг 5 (Опционально)
            if args.img:
                if os.path.exists(args.img):
                    step_5_custom_kernel(tmp_dir, args.input, args.out, args.img, dtb_files)
                else:
                    log(f"Файл {args.img} не найден!", Colors.FAIL)
            
        except KeyboardInterrupt:
            log("\nПрервано пользователем.", Colors.FAIL)
        except Exception as e:
            log(f"\nКритическая ошибка: {e}", Colors.FAIL)
            import traceback
            traceback.print_exc()

    log("\nГотово! Временные файлы удалены.", Colors.OKGREEN)

if __name__ == "__main__":
    main()