#!/bin/bash
# Скрипт для замены ядра и DTB в образах boot.img и vendor_kernel_boot.img
# Использует magiskboot для распаковки и запаковки.

# =================================================================
# 1. КОНФИГУРАЦИЯ И ПРОВЕРКА
# =================================================================

# Функция для вывода справки
show_help() {
    echo "Usage: $0 --input <Input_Dir> --out <Output_Dir> [--zip <AnyKernel.zip>] [--Image <Kernel_Image>]"
    echo ""
    echo "Arguments:"
    echo "  --input   Directory containing original boot.img and vendor_kernel_boot.img"
    echo "  --out     Directory to save modified images"
    echo "  --zip     Path to AnyKernel zip archive (optional)"
    echo "  --Image   Path to custom kernel Image file (optional)"
    exit 1
}

# Проверка аргументов
if [ $# -lt 4 ]; then
    show_help
fi

INPUT_DIR=""
OUT_DIR=""
ZIP_FILE=""
CUSTOM_IMAGE=""

while [ "$1" != "" ]; do
    case $1 in
        --input )   shift
                    INPUT_DIR=$(readlink -f "$1")
                    ;;
        --out )     shift
                    OUT_DIR=$(readlink -f "$1")
                    ;;
        --zip )     shift
                    ZIP_FILE=$(readlink -f "$1")
                    ;;
        --Image )   shift
                    CUSTOM_IMAGE=$(readlink -f "$1")
                    ;;
        * )         echo "Invalid argument: $1"
                    exit 1
                    ;;
    esac
    shift
done

# Проверка обязательных путей
if [ -z "$INPUT_DIR" ] || [ ! -d "$INPUT_DIR" ]; then
    echo "Error: Input directory not found or not specified."
    exit 1
fi

if [ -z "$OUT_DIR" ]; then
    echo "Error: Output directory not specified."
    exit 1
fi

# Проверка наличия magiskboot
if ! command -v magiskboot &> /dev/null; then
    echo "Error: magiskboot utility is not found. Ensure it is in your PATH."
    exit 1
fi

# Установка служебных переменных
TEMP_DIR=$(mktemp -d -t repack-XXXXXXXXXX)
trap "rm -rf $TEMP_DIR" EXIT

echo "Working directory: $TEMP_DIR"
mkdir -p "$OUT_DIR"

# =================================================================
# 2. ПОДГОТОВКА ФАЙЛОВ ЯДРА И DTB
# =================================================================

NEW_KERNEL=""
NEW_DTB=""

# Если указан ZIP, извлекаем из него
if [ -n "$ZIP_FILE" ] && [ -f "$ZIP_FILE" ]; then
    echo "Extracting from ZIP: $ZIP_FILE"
    unzip -q "$ZIP_FILE" -d "$TEMP_DIR/zip_content" > /dev/null 2>&1
    
    # Ищем ядро в ZIP
    if [ -f "$TEMP_DIR/zip_content/Image.lz4" ]; then
        NEW_KERNEL="$TEMP_DIR/zip_content/Image.lz4"
        echo "Found kernel (lz4) in zip."
    elif [ -f "$TEMP_DIR/zip_content/Image.gz" ]; then
        # Если gz, распаковываем для единообразия, потом сожмем как надо boot.img
        gzip -d "$TEMP_DIR/zip_content/Image.gz"
        NEW_KERNEL="$TEMP_DIR/zip_content/Image"
        echo "Found kernel (gz->raw) in zip."
    elif [ -f "$TEMP_DIR/zip_content/Image" ]; then
        NEW_KERNEL="$TEMP_DIR/zip_content/Image"
        echo "Found kernel (raw) in zip."
    fi

    # Ищем dtb в ZIP
    if [ -f "$TEMP_DIR/zip_content/dtb" ]; then
        NEW_DTB="$TEMP_DIR/zip_content/dtb"
        echo "Found dtb in zip."
    elif [ -f "$TEMP_DIR/zip_content/dtb.img" ]; then
        NEW_DTB="$TEMP_DIR/zip_content/dtb.img"
        echo "Found dtb.img in zip."
    fi
fi

# Если указан отдельный Image, он имеет приоритет над ZIP
if [ -n "$CUSTOM_IMAGE" ] && [ -f "$CUSTOM_IMAGE" ]; then
    echo "Using custom Image file: $CUSTOM_IMAGE"
    NEW_KERNEL="$CUSTOM_IMAGE"
fi

if [ -z "$NEW_KERNEL" ] && [ -z "$NEW_DTB" ]; then
    echo "Warning: No new kernel or DTB found to update. Nothing to do."
    exit 0
fi

# =================================================================
# 3. ПЕРЕПАКОВКА BOOT.IMG (Замена ядра)
# =================================================================

if [ -n "$NEW_KERNEL" ]; then
    if [ -f "$INPUT_DIR/boot.img" ]; then
        echo "Repacking boot.img..."
        mkdir -p "$TEMP_DIR/boot"
        cd "$TEMP_DIR/boot"
        
        # Распаковка
        magiskboot unpack "$INPUT_DIR/boot.img" > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "Error unpacking boot.img"
            exit 1
        fi

        # Подмена ядра. magiskboot ожидает файл с именем 'kernel'
        cp "$NEW_KERNEL" kernel
        
        # Запаковка
        magiskboot repack "$INPUT_DIR/boot.img" > /dev/null 2>&1
        if [ $? -eq 0 ] && [ -f "new-boot.img" ]; then
            cp "new-boot.img" "$OUT_DIR/boot.img"
            echo "Successfully repacked boot.img -> $OUT_DIR/boot.img"
        else
            echo "Error repacking boot.img"
            exit 1
        fi
        cd "$OLDPWD"
    else
        echo "boot.img not found in input directory. Skipping."
    fi
fi

# =================================================================
# 4. ПЕРЕПАКОВКА VENDOR_KERNEL_BOOT.IMG (Замена DTB)
# =================================================================

if [ -n "$NEW_DTB" ]; then
    if [ -f "$INPUT_DIR/vendor_kernel_boot.img" ]; then
        echo "Repacking vendor_kernel_boot.img..."
        mkdir -p "$TEMP_DIR/vkboot"
        cd "$TEMP_DIR/vkboot"

        # Распаковка
        magiskboot unpack "$INPUT_DIR/vendor_kernel_boot.img" > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            echo "Error unpacking vendor_kernel_boot.img"
            exit 1
        fi

        # Подмена DTB. magiskboot извлекает dtb в файл 'dtb'
        cp "$NEW_DTB" dtb

        # Запаковка
        magiskboot repack "$INPUT_DIR/vendor_kernel_boot.img" > /dev/null 2>&1
        if [ $? -eq 0 ] && [ -f "new-boot.img" ]; then
            cp "new-boot.img" "$OUT_DIR/vendor_kernel_boot.img"
            echo "Successfully repacked vendor_kernel_boot.img -> $OUT_DIR/vendor_kernel_boot.img"
        else
            echo "Error repacking vendor_kernel_boot.img"
            exit 1
        fi
        cd "$OLDPWD"
    else
        echo "vendor_kernel_boot.img not found in input directory. Skipping."
    fi
fi

echo "Done."