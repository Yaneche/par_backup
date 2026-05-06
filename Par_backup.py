#!/usr/bin/env python3
# Par_backup.py

import argparse
import sys
import os
import glob
from datetime import datetime

from par_tools.config_io import load_config, select_device
from par_tools.par_backup_core import (
    run_browse_mode, 
    run_read_mode, 
    run_write_mode
)
from par_tools.paths import DATA_ROOT, PLC_DATA_DIR

os.makedirs(DATA_ROOT, exist_ok=True)
os.makedirs(PLC_DATA_DIR, exist_ok=True)


def flatten_tree(tree, prefix=""):
    """Вспомогательная функция для подсчёта тегов"""
    flat = {}
    def _walk(node, cur_path):
        if isinstance(node, dict) and "value" in node and "nodeid" in node:
            flat[".".join(cur_path)] = node
            return
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, cur_path + [k])
    _walk(tree, [prefix] if prefix else [])
    return flat


def copy_settings_between_furnaces(config):
    """Копирование настроек между печами (с поддержкой нескольких блоков)"""
    print("\n" + "="*60)
    print("🔄 КОПИРОВАНИЕ НАСТРОЕК МЕЖДУ ПЕЧАМИ")
    print("="*60)
    
    print("\n📤 ОТКУДА копировать:")
    src_device = select_device(config)
    if not src_device:
        return

    # Ищем все YAML по IP печи
    yaml_pattern = os.path.join(PLC_DATA_DIR, f"*{src_device['ip']}*.yaml")
    yaml_files = sorted(glob.glob(yaml_pattern), key=os.path.getmtime, reverse=True)
    
    if not yaml_files:
        print(f"❌ Нет YAML-файлов для {src_device['name']}")
        return

    print(f"\n📄 Доступные файлы для {src_device['name']}:")
    for i, f in enumerate(yaml_files[:10], 1):
        size = os.path.getsize(f) / 1024
        print(f"  {i}. {os.path.basename(f)} ({size:.1f} KB)")

    filename = input(f"\nВыберите файл (Enter={os.path.basename(yaml_files[0])}, q=отмена): ").strip()
    if filename.lower() == "q":
        return
    if not filename:
        filename = os.path.basename(yaml_files[0])

    print(f"\n📥 КУДА копировать:")
    dst_device = select_device(config)
    if not dst_device:
        return

    confirm = input(f"\n⚠ Копировать из {src_device['name']} в {dst_device['name']}? (y/N): ").strip().lower()
    if confirm not in ("y", "yes", "д", "да"):
        return

    # Загружаем файл и показываем, какие блоки будут скопированы
    import yaml
    filepath = os.path.join(PLC_DATA_DIR, filename)
    with open(filepath, 'r', encoding='utf-8') as f:
        tree = yaml.safe_load(f)
    
    root_blocks = list(tree.keys())
    print(f"\n📦 Будет скопировано {len(root_blocks)} блок(ов):")
    for block in root_blocks:
        flat_block = flatten_tree({block: tree[block]})
        print(f"  • {block} ({len(flat_block)} тегов)")
    
    confirm2 = input("\nПРОДОЛЖИТЬ КОПИРОВАНИЕ? (y/N): ").strip().lower()
    if confirm2 not in ("y", "yes", "д", "да"):
        return

    # Выполняем запись
    run_write_mode(config, dst_device, argparse.Namespace(name=filename))
    print("\n✅ Копирование завершено!")


def show_statistics():
    """Показать статистику по сохранённым файлам"""
    print("\n" + "="*60)
    print("📊 СТАТИСТИКА СОХРАНЁННЫХ ФАЙЛОВ")
    print("="*60)
    
    yaml_files = glob.glob(os.path.join(PLC_DATA_DIR, "*.yaml"))
    if not yaml_files:
        print("❌ Нет сохранённых файлов")
        return
    
    print(f"\n📁 Каталог: {PLC_DATA_DIR}")
    print(f"📄 Всего файлов: {len(yaml_files)}")
    print("\nПоследние 10 файлов:")
    
    yaml_files.sort(key=os.path.getmtime, reverse=True)
    for i, f in enumerate(yaml_files[:10], 1):
        size = os.path.getsize(f) / 1024
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {i}. {os.path.basename(f)} ({size:.1f} KB, {mtime})")


def main():
    os.makedirs(DATA_ROOT, exist_ok=True)
    os.makedirs(PLC_DATA_DIR, exist_ok=True)

    parser = argparse.ArgumentParser(
        description="OPC UA Параметры ПЛК - Резервное копирование и восстановление",
        add_help=False
    )
    parser.add_argument("--read", "-r", action="store_true", help="Режим чтения (сохранение)")
    parser.add_argument("--write", "-w", action="store_true", help="Режим записи (восстановление)")
    parser.add_argument("--copy", "-c", action="store_true", help="Копирование между устройствами")
    parser.add_argument("--browse", "-b", action="store_true", help="Режим обзора дерева")
    parser.add_argument("--name", "-n", help="Имя файла для чтения/записи")
    parser.add_argument("--csv", action="store_true", help="Дополнительно сохранить CSV")
    parser.add_argument("--stats", "-s", action="store_true", help="Показать статистику файлов")
    parser.add_argument("--help", "-h", action="store_true", help="Показать справку")
    
    args = parser.parse_args()

    if args.help:
        print("""
╔══════════════════════════════════════════════════════════════╗
║     OPC UA Параметры ПЛК - Резервное копирование            ║
╚══════════════════════════════════════════════════════════════╝

РЕЖИМЫ РАБОТЫ:
  1. Сохранение настроек     -r
  2. Восстановление настроек -w
  3. Обзор дерева OPC UA     -b
  4. Копирование между ПЛК    -c
  5. Статистика файлов       -s

ПРИМЕРЫ:
  python Par_backup.py -r                    # Интерактивное сохранение
  python Par_backup.py -w                    # Интерактивное восстановление
  python Par_backup.py -r --csv              # Сохранение + CSV
  python Par_backup.py -s                    # Показать статистику
        """)
        sys.exit(0)

    if args.stats:
        show_statistics()
        return

    config = load_config()

    # Интерактивный режим
    while True:
        if args.read:
            mode = "read"
        elif args.write:
            mode = "write"
        elif args.copy:
            mode = "copy"
        elif args.browse:
            mode = "browse"
        else:
            print("\n" + "="*60)
            print("🎛 ГЛАВНОЕ МЕНЮ")
            print("="*60)
            print("1. 💾 Сохранить настройки (поддерживает несколько блоков)")
            print("2. ⏫ Восстановить настройки из файла")
            print("3. 🌲 Обзор дерева OPC UA")
            print("4. 📤 Копировать настройки (ПЛК → ПЛК)")
            print("5. 📊 Статистика файлов")
            print("q. 🚪 Выход")
            
            choice = input("\nВыбор (1-5/q): ").strip().lower()
            
            if choice == "1":
                mode = "read"
            elif choice == "2":
                mode = "write"
            elif choice == "3":
                mode = "browse"
            elif choice == "4":
                mode = "copy"
            elif choice == "5":
                show_statistics()
                continue
            elif choice == "q":
                print("\n🔌 Выход.")
                break
            else:
                print("❌ Неверный выбор.")
                continue

        if mode == "copy":
            copy_settings_between_furnaces(config)
        else:
            device = select_device(config)
            if device is None:
                print("\n🔌 Выход.")
                break

            if mode == "browse":
                run_browse_mode(config, device, args)
            elif mode == "read":
                run_read_mode(config, device, args)
            elif mode == "write":
                run_write_mode(config, device, args)

        # Сброс аргументов для следующей итерации
        args.read = False
        args.write = False
        args.copy = False
        args.browse = False
        
        ans = input("\nEnter = вернуться в меню, 'q' = выход: ").strip().lower()
        if ans == "q":
            print("\n🔌 Выход.")
            break


if __name__ == "__main__":
    main()