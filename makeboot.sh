#!/bin/bash
# Скрипт для подготовки ядра (Image) и boot-образов для Android prebuilt.

# =================================================================
# 1. КОНФИГУРАЦИЯ И ПРОВЕРКА
# =================================================================

# Проверка, что скрипт запущен с аргументами
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Usage: $0 --zip <AnyKernel_Archive.zip> --out <Output_Folder>"
    exit 1
fi

# Разбор аргументов
while [ "$1" != "" ]; do
    case $1 in
        --zip ) shift
                ZIP_FILE=$1
                ;;
        --out ) shift
                OUT_DIR=$1
                ;;
        * )     echo "Invalid argument: $1"
                exit 1
    esac
    shift
done

# Проверка наличия magiskboot
if ! command -v magiskboot &> /dev/null; then
    echo "Error: magiskboot utility is not found. Ensure it is in your PATH."
    exit 1
fi

# Проверка наличия ZIP-файла
if [ ! -f "$ZIP_FILE" ]; then
    echo "Error: ZIP file not found: $ZIP_FILE"
    exit 1
fi

# Установка служебных переменных
TEMP_DIR=$(mktemp -d -t anykernel-XXXXXXXXXX)
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
STOCK_BOOT_DIR="$SCRIPT_DIR/evolution"

# Чистка временных файлов при выходе
trap "rm -rf $TEMP_DIR" EXIT

# =================================================================
# 2. РАСПАКОВКА И ДЕКОМПРЕССИЯ ЯДРА
# =================================================================

echo "1. Unpacking $ZIP_FILE to $TEMP_DIR..."
unzip -q "$ZIP_FILE" -d "$TEMP_DIR"

# Определяем тип ядра
if [ -f "$TEMP_DIR/Image.lz4" ]; then
    KERNEL_COMPRESSED_FILE="Image.lz4"
    KERNEL_TYPE="lz4"
elif [ -f "$TEMP_DIR/Image" ]; then
    KERNEL_COMPRESSED_FILE="Image"
    KERNEL_TYPE="uncompressed"
else
    echo "Error: Neither Image nor Image.lz4 found in the ZIP file."
    exit 1
fi

# Декомпрессия в несжатое ядро
DECOMPRESSED_KERNEL="$TEMP_DIR/Image_uncompressed"

if [ "$KERNEL_TYPE" == "lz4" ]; then
    echo "2. Decompressing $KERNEL_COMPRESSED_FILE using magiskboot..."
    magiskboot decompress "$TEMP_DIR/$KERNEL_COMPRESSED_FILE" "$DECOMPRESSED_KERNEL" &> /dev/null
    if [ $? -ne 0 ]; then
        echo "Error: magiskboot decompress failed."
        exit 1
    fi
else
    echo "2. Kernel is uncompressed (Image). Copying."
    cp "$TEMP_DIR/Image" "$DECOMPRESSED_KERNEL"
fi

if [ ! -f "$DECOMPRESSED_KERNEL" ]; then
    echo "Error: Decompressed kernel file not found."
    exit 1
fi

# =================================================================
# 3. ПОДГОТОВКА KERNEL PREBUILTS
# =================================================================

echo "3. Preparing output directory: $OUT_DIR"
mkdir -p "$OUT_DIR"

# A. KERNEL: Копирование несжатой версии
cp "$DECOMPRESSED_KERNEL" "$OUT_DIR/Image"
echo "   - Created $OUT_DIR/Image (Uncompressed)"

# B. KERNEL: Создание сжатой версии Image.lz4 (lz4_legacy)
magiskboot compress=lz4_legacy "$DECOMPRESSED_KERNEL" "$OUT_DIR/Image.lz4" &> /dev/null
echo "   - Created $OUT_DIR/Image.lz4 (lz4_legacy compressed)"

# C. KERNEL: Создание сжатой версии Image.gz
gzip -c "$DECOMPRESSED_KERNEL" > "$OUT_DIR/Image.gz"
echo "   - Created $OUT_DIR/Image.gz (gzip compressed)"

# =================================================================
# 4. ПЕРЕПАКОВКА BOOT.IMG (ТОЛЬКО ЗАМЕНА ЯДРА)
# =================================================================

STOCK_BOOT_IMG="$STOCK_BOOT_DIR/boot.img"
NEW_BOOT_IMG="$OUT_DIR/boot.img"
BOOT_WORK_DIR="$TEMP_DIR/boot_work" # Изолированная папка для boot.img

if [ ! -f "$STOCK_BOOT_IMG" ]; then
    echo "Warning: Stock boot.img not found at $STOCK_BOOT_IMG. Skipping boot.img repack."
else
    echo "4. Repacking boot.img with new kernel (Kernel-only update)..."
    
    mkdir -p "$BOOT_WORK_DIR"
    
    # 4.1. Копируем: 1) Стоковый образ, 2) Новое ядро под именем 'kernel'
    cp "$STOCK_BOOT_IMG" "$BOOT_WORK_DIR/boot.img"
    cp "$DECOMPRESSED_KERNEL" "$BOOT_WORK_DIR/kernel" # Новое ядро из AnyKernel
    
    # Переходим в суб-оболочку для работы magiskboot (гарантирует new-boot.img в BOOT_WORK_DIR)
    (
        cd "$BOOT_WORK_DIR" || exit 1
        
        # Repack: magiskboot использует 'kernel' и 'boot.img' для создания нового образа.
        magiskboot repack boot.img &> /dev/null
    )
    
    # 4.2. Копирование результата из BOOT_WORK_DIR в OUT
    if [ -f "$BOOT_WORK_DIR/new-boot.img" ]; then
        mv "$BOOT_WORK_DIR/new-boot.img" "$NEW_BOOT_IMG"
        echo "   - Created $NEW_BOOT_IMG"
    else
        echo "Error: magiskboot repack of boot.img failed. new-boot.img not created."
        exit 1
    fi
fi

# =================================================================
# 5. ОБРАБОТКА DTB И ПЕРЕПАКОВКА VENDOR_KERNEL_BOOT.IMG
# =================================================================

DTB_FILE_IN_ANYKERNEL="$TEMP_DIR/dtb"
STOCK_VKB_IMG="$STOCK_BOOT_DIR/vendor_kernel_boot.img"
NEW_VKB_IMG="$OUT_DIR/vendor_kernel_boot.img"
VKB_WORK_DIR="$TEMP_DIR/vkb_work" # Изолированная папка для vendor_kernel_boot.img

if [ -f "$DTB_FILE_IN_ANYKERNEL" ]; then
    echo "5. DTB file found. Processing vendor_kernel_boot.img..."
    
    # A. Копирование несжатого DTB в out
    cp "$DTB_FILE_IN_ANYKERNEL" "$OUT_DIR/dtb.img"
    echo "   - Created $OUT_DIR/dtb.img (Uncompressed DTB)"

    if [ ! -f "$STOCK_VKB_IMG" ]; then
        echo "Warning: Stock vendor_kernel_boot.img not found at $STOCK_BOOT_DIR. Skipping VKB repack."
    else
        mkdir -p "$VKB_WORK_DIR"
        
        # 5.1. Копирование стокового VKB в рабочую папку
        cp "$STOCK_VKB_IMG" "$VKB_WORK_DIR/vendor_kernel_boot.img"
        
        # Переходим в суб-оболочку для работы magiskboot
        (
            cd "$VKB_WORK_DIR" || exit 1
            
            # Unpack: РАСПАКОВЫВАЕМ VKB. Извлекает компоненты, включая старый dtb в файл 'dtb'.
            echo "   -> Unpacking stock vendor_kernel_boot.img..."
            magiskboot unpack vendor_kernel_boot.img &> /dev/null
            
            # 5.2. ЗАМЕНА DTB: Копируем новый dtb из AnyKernel, перезаписывая старый.
            cp "$DTB_FILE_IN_ANYKERNEL" "dtb" 
            echo "   -> Replaced stock dtb with AnyKernel dtb."
            
            # 5.3. Repack: magiskboot использует новый файл 'dtb'
            echo "   -> Repacking vendor_kernel_boot.img..."
            magiskboot repack vendor_kernel_boot.img &> /dev/null
        )
        
        # 5.4. Копирование результата из VKB_WORK_DIR в OUT
        if [ -f "$VKB_WORK_DIR/new-boot.img" ]; then
            mv "$VKB_WORK_DIR/new-boot.img" "$NEW_VKB_IMG"
            echo "   - Created $NEW_VKB_IMG"
        else
            echo "Error: magiskboot repack of VKB failed. new-boot.img not created."
            exit 1
        fi
    fi
else
    echo "5. DTB file not found in AnyKernel archive. Skipping vendor_kernel_boot.img repack."
fi

# =================================================================
# 6. КОПИРОВАНИЕ ОСТАЛЬНЫХ СТОКОВЫХ ФАЙЛОВ
# =================================================================

echo "6. Copying remaining stock prebuilts to $OUT_DIR..."

# Используем rsync для копирования ВСЕГО из STOCK_BOOT_DIR в OUT_DIR, 
# исключая файлы, которые мы уже создали/обновили на предыдущих шагах.
# -a: архивный режим (сохранение прав, рекурсивное копирование).
# -v: verbose (подробный вывод).
# --ignore-existing: НЕ перезаписывать файлы, которые уже есть в OUT_DIR.

rsync -av --ignore-existing "$STOCK_BOOT_DIR/" "$OUT_DIR/" &> /dev/null

# Примечание: Файлы, созданные ранее, такие как boot.img, Image, Image.lz4 и т.д., 
# уже существуют в $OUT_DIR, поэтому они не будут перезаписаны старыми стоковыми версиями.

echo "   -> Copied all remaining files from $STOCK_BOOT_DIR, ignoring existing."


# =================================================================
# 7. ФИНАЛИЗАЦИЯ
# =================================================================

echo "7. SUCCESS. All required files are in $OUT_DIR"