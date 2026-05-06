# par_backup_core.py
# -*- coding: utf-8 -*-

import os
import csv
import time

from par_tools.opcua_client import (
    make_endpoint,
    connect_client,
    jump_to_globalvars,
    interactive_tree_select_from_node,
    read_block_tags,
    read_paths_tags,
    save_tags_yaml,
    flatten_tree,
    build_tree_from_flat,
)
from par_tools.config_io import (
    load_device_paths,
    save_device_paths,
    get_filename,
)


# ---------- общий помощник: выбор порта + подключение ----------

def _ask_port_and_connect(config, device):
    """
    Цикл выбора порта + подключение.
    Возвращает (client или None, port_str или None).
    """
    while True:
        s = input(
            f"Порт для {device['name']} (Enter={config['port']}, q=в меню): "
        ).strip()
        if s.lower() == "q":
            print("↩ Возврат в главное меню.")
            return None, None

        if not s:
            port_str = str(config["port"])
        else:
            try:
                p = int(s)
                if not (1 <= p <= 65535):
                    print("❌ Неверный порт (допустимо 1–65535).")
                    continue
                port_str = str(p)
            except ValueError:
                print("❌ Введите номер порта, Enter или q для возврата в меню.")
                continue

        endpoint = make_endpoint(device, config, port_str)
        print(f"\n🔌 {device['name']} ({device['ip']}) → {endpoint}")

        client = connect_client(endpoint)
        if client is None:
            retry = input(
                "⚠ Порт не открыт или сервер недоступен. "
                "Повторить выбор порта? (y/N): "
            ).strip().lower()
            if retry not in ("y", "yes", "д", "да", "1"):
                print("↩ Возврат в главное меню.")
                return None, None
            continue

        return client, port_str


# ---------- работа с несколькими блоками (с обходом дерева) ----------

def _get_block_name(node):
    """Получить имя узла"""
    try:
        return node.get_browse_name().Name
    except:
        return "Unknown"


def _read_block_with_tags(client, node, block_name):
    """Прочитать блок и вернуть плоский словарь тегов"""
    flat_tags = read_block_tags(client, node, block_name)
    return flat_tags


def select_multiple_blocks(client, device_ip):
    """
    Позволяет выбрать несколько блоков через обход дерева.
    Возвращает список путей или None.
    """
    from par_tools.config_io import load_config
    config = load_config()
    saved_paths = load_device_paths(config, device_ip)
    
    while True:
        print("\n" + "="*60)
        print("📦 УПРАВЛЕНИЕ БЛОКАМИ")
        print("="*60)
        
        if saved_paths:
            print(f"\n📂 Текущие сохранённые блоки ({len(saved_paths)} шт.):")
            for i, p in enumerate(saved_paths, 1):
                name = p.get('name', 'Unknown')
                tags = p.get('tags', '?')
                print(f"  {i}. {name} (~{tags} тегов)")
        
        print("\nДоступные действия:")
        print("  1 - Сохранить все блоки и продолжить")
        print("  2 - Добавить новый блок (обход дерева)")
        print("  3 - Удалить блок")
        print("  4 - Очистить все блоки")
        print("  q - Отмена")
        
        choice = input("\nВыбор (1-4/q): ").strip().lower()
        
        if choice == "2":
            new_paths = _add_new_block_via_tree(client, saved_paths)
            if new_paths is not None:
                saved_paths = new_paths
                save_device_paths(config, device_ip, saved_paths)
                print(f"✅ Сохранено {len(saved_paths)} блок(ов) в конфиг")
        
        elif choice == "3":
            if not saved_paths:
                print("❌ Нет блоков для удаления")
                continue
            saved_paths = _remove_block_interactive(saved_paths)
            if saved_paths is not None:
                save_device_paths(config, device_ip, saved_paths)
        
        elif choice == "4":
            if saved_paths:
                confirm = input(f"⚠ Удалить все {len(saved_paths)} блок(ов)? (y/N): ").strip().lower()
                if confirm in ("y", "yes", "д", "да"):
                    saved_paths = []
                    save_device_paths(config, device_ip, saved_paths)
                    print("✅ Все блоки удалены")
        
        elif choice == "1":
            if not saved_paths:
                print("❌ Нет блоков для сохранения. Сначала добавьте хотя бы один блок.")
                continue
            return saved_paths
        
        elif choice == "q":
            return None
        
        else:
            print("❌ Неверный выбор")


def _add_new_block_via_tree(client, existing_paths):
    """
    Добавление блока через обход дерева (как в старом скрипте)
    """
    new_paths = existing_paths.copy() if existing_paths else []
    added_count = 0
    
    while True:
        print("\n" + "-"*40)
        print("➕ ДОБАВЛЕНИЕ НОВОГО БЛОКА")
        print("-"*40)
        
        # КАК В СТАРОМ СКРИПТЕ - ищем GlobalVars или показываем корень
        try:
            gvars = jump_to_globalvars(client)
            if gvars:
                print("\n🌲 Найден узел GlobalVars. Выберите нужный блок (например Par_Db):")
                start_node = gvars
            else:
                print("\n⚠ GlobalVars не найден, показываю дерево с корня.")
                start_node = client.get_root_node()
        except Exception as e:
            print(f"⚠ Ошибка при поиске GlobalVars: {e}")
            print("Показываю дерево с корня.")
            start_node = client.get_root_node()
        
        # Выбираем блок (как в старом скрипте)
        selected_node = interactive_tree_select_from_node(start_node)
        if selected_node is None:
            print("❌ Выбор блока отменён")
            break
        
        nid = selected_node.nodeid.to_string()
        block_name = _get_block_name(selected_node)
        
        # Проверяем, не добавлен ли уже
        if any(p["path"] == nid for p in new_paths):
            print(f"⚠ Блок '{block_name}' уже есть в списке")
        else:
            # Читаем блок, чтобы узнать количество тегов
            print(f"\n📖 Чтение блока '{block_name}' для подсчёта тегов...")
            try:
                flat_tags = _read_block_with_tags(client, selected_node, block_name)
                
                new_paths.append({
                    "path": nid,
                    "tags": len(flat_tags),
                    "name": block_name
                })
                print(f"✅ Добавлен блок: {block_name} ({len(flat_tags)} тегов)")
                added_count += 1
            except Exception as e:
                print(f"❌ Ошибка при чтении блока: {e}")
                continue
        
        more = input("\n➕ Добавить ещё блок? (y/N): ").strip().lower()
        if more not in ("y", "yes", "д", "да"):
            break
    
    if added_count > 0:
        print(f"\n📊 Добавлено блоков: {added_count}")
        return new_paths
    return None


def _remove_block_interactive(paths):
    """Удаление блока из списка"""
    print("\n" + "-"*40)
    print("🗑 УДАЛЕНИЕ БЛОКА")
    print("-"*40)
    
    for i, p in enumerate(paths, 1):
        name = p.get('name', 'Unknown')
        print(f"  {i}. {name}")
    
    print("  m. Удалить несколько")
    print("  q. Отмена")
    
    choice = input("\nВыбор (номер, m, q): ").strip().lower()
    
    if choice == "q":
        return paths
    
    if choice == "m":
        indices = input("Введите номера блоков через пробел: ").strip()
        try:
            idx_list = [int(x.strip()) - 1 for x in indices.split() if x.strip().isdigit()]
            for idx in sorted(idx_list, reverse=True):
                if 0 <= idx < len(paths):
                    removed = paths.pop(idx)
                    print(f"✅ Удалён блок: {removed.get('name', removed['path'])}")
            return paths
        except:
            print("❌ Ошибка при удалении")
            return paths
    
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(paths):
            removed = paths.pop(idx)
            print(f"✅ Удалён блок: {removed.get('name', removed['path'])}")
            return paths
        else:
            print("❌ Неверный номер")
    
    return paths


# ---------- Режим 3: Обзор дерева ----------

def run_browse_mode(config, device, args):
    """
    Режим 3: обзор дерева OPC UA.
    Ничего не сохраняет, только даёт пользователю походить по дереву.
    """
    client, _ = _ask_port_and_connect(config, device)
    if client is None:
        return

    try:
        gvars = jump_to_globalvars(client)
        if gvars:
            print("\n🌲 Автоматически найден узел GlobalVars. Можно ходить от него.")
            start_node = gvars
        else:
            print("\n⚠ Не удалось найти GlobalVars автоматически, показываю дерево с корня.")
            start_node = client.get_root_node()

        _ = interactive_tree_select_from_node(start_node)
        print("🔌 Готово!")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass


# ---------- Режим 1: Сохранить настройки (с поддержкой нескольких блоков) ----------

def run_read_mode(config, device, args):
    """
    Режим 1: сохранить настройки.
    Поддерживает несколько блоков OPC UA.
    """
    client, _ = _ask_port_and_connect(config, device)
    if client is None:
        return

    try:
        # Выбираем блоки для сохранения
        all_paths = select_multiple_blocks(client, device["ip"])
        if all_paths is None:
            print("🔌 Операция отменена")
            return
        
        if not all_paths:
            print("❌ Нет блоков для сохранения")
            return
        
        # Читаем ВСЕ выбранные блоки
        print(f"\n📖 Чтение {len(all_paths)} блок(ов)...")
        print("-"*40)
        
        tree = read_paths_tags(client, all_paths)
        
        # Проверяем, удалось ли прочитать данные
        if tree is None:
            print("\n❌ Сохранение отменено: не удалось получить данные от ПЛК")
            return
        
        # Сохраняем результат в YAML
        flat_tags = flatten_tree(tree)
        yaml_path = get_filename(device)
        os.makedirs(os.path.dirname(yaml_path), exist_ok=True)
        
        save_tags_yaml(tree, os.path.dirname(yaml_path), os.path.basename(yaml_path))
        print(f"\n💾 Сохранено {len(flat_tags)} тегов → {os.path.basename(yaml_path)}")
        
        # CSV — по желанию (только если данные успешно прочитаны)
        if hasattr(args, 'csv') and args.csv:
            csv_path = os.path.splitext(yaml_path)[0] + ".csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Path", "Value", "NodeId"])
                for path, data in flat_tags.items():
                    w.writerow([path, str(data["value"]), data["nodeid"]])
            print(f"📊 CSV сохранён: {os.path.basename(csv_path)}")
        
        # Выводим статистику по блокам
        print("\n📊 СТАТИСТИКА ПО БЛОКАМ:")
        for block_path in all_paths:
            block_name = block_path.get('name', 'Unknown')
            block_tags = block_path.get('tags', '?')
            print(f"  • {block_name}: {block_tags} тегов")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        print("\n🔌 Готово!")


# ---------- Режим 2: Восстановить настройки ----------

def run_write_mode(config, device, args):
    """
    Режим 2: восстановить настройки из YAML.
    Позволяет выбрать, какие блоки восстанавливать.
    """
    from par_tools.opcua_client import write_tags
    from par_tools.paths import PLC_DATA_DIR
    import yaml
    
    # Показываем список YAML-файлов
    try:
        yaml_files = [f for f in os.listdir(PLC_DATA_DIR) if f.lower().endswith(".yaml")]
    except FileNotFoundError:
        yaml_files = []
    
    if not yaml_files:
        print(f"\n❌ В папке {PLC_DATA_DIR} нет YAML-файлов.")
        return
    
    # Сортируем по времени (новые сверху)
    yaml_full = [os.path.join(PLC_DATA_DIR, f) for f in yaml_files]
    yaml_full.sort(key=os.path.getmtime, reverse=True)
    yaml_files_sorted = [os.path.basename(p) for p in yaml_full]
    
    print(f"\n📂 Доступные YAML-файлы в {PLC_DATA_DIR}:")
    for idx, name in enumerate(yaml_files_sorted, 1):
        size = os.path.getsize(os.path.join(PLC_DATA_DIR, name)) / 1024
        print(f"  {idx}. {name} ({size:.1f} KB)")
    
    default_yaml = yaml_files_sorted[0]
    print(f"\n💡 Файл по умолчанию: {default_yaml}")
    
    user = input(f"Выберите файл (Enter={default_yaml}, номер или имя, q=отмена): ").strip()
    if user.lower() == "q":
        print("↩ Возврат в главное меню.")
        return
    
    if not user:
        filename = default_yaml
    elif user.isdigit():
        idx = int(user)
        if 1 <= idx <= len(yaml_files_sorted):
            filename = yaml_files_sorted[idx - 1]
        else:
            print("❌ Неверный номер.")
            return
    else:
        filename = user
        if not os.path.exists(os.path.join(PLC_DATA_DIR, filename)):
            print(f"❌ Файл {filename} не найден.")
            return
    
    # Загружаем файл и показываем доступные блоки
    filepath = os.path.join(PLC_DATA_DIR, filename)
    with open(filepath, 'r', encoding='utf-8') as f:
        tree = yaml.safe_load(f)
    
    if not tree:
        print("❌ Файл пуст или имеет неверный формат")
        return
    
    # Получаем корневые блоки
    root_blocks = list(tree.keys())
    
    print(f"\n📦 БЛОКИ В ФАЙЛЕ {filename}:")
    print("-"*40)
    
    for i, block in enumerate(root_blocks, 1):
        flat_block = flatten_tree({block: tree[block]})
        print(f"  {i}. {block} ({len(flat_block)} тегов)")
    
    print("\nДоступные действия:")
    print("  a - Восстановить ВСЕ блоки")
    print("  номера через пробел - восстановить выбранные блоки (например: 1 3 5)")
    print("  q - Отмена")
    
    choice = input("\nВыбор: ").strip().lower()
    
    if choice == "q":
        print("↩ Возврат в главное меню.")
        return
    
    if choice == "a":
        selected_tree = tree
        selected_blocks = root_blocks
    else:
        try:
            indices = [int(x.strip()) - 1 for x in choice.split() if x.strip().isdigit()]
            if not indices:
                print("❌ Неверный выбор")
                return
            
            selected_blocks = []
            selected_tree = {}
            for idx in indices:
                if 0 <= idx < len(root_blocks):
                    block_name = root_blocks[idx]
                    selected_blocks.append(block_name)
                    selected_tree[block_name] = tree[block_name]
                else:
                    print(f"⚠ Номер {idx+1} вне диапазона")
            
            if not selected_tree:
                print("❌ Не выбрано ни одного блока")
                return
        except:
            print("❌ Ошибка при выборе блоков")
            return
    
    # Сохраняем выбранные блоки во временный файл
    temp_yaml = os.path.join(PLC_DATA_DIR, f"_temp_restore_{os.path.basename(filename)}")
    with open(temp_yaml, 'w', encoding='utf-8') as f:
        yaml.safe_dump(selected_tree, f, allow_unicode=True, sort_keys=False)
    
    print(f"\n📋 Будет восстановлено {len(selected_blocks)} блок(ов):")
    for block in selected_blocks:
        print(f"  • {block}")
    
    confirm = input("\n⚠ ПРОДОЛЖИТЬ ВОССТАНОВЛЕНИЕ? (y/N): ").strip().lower()
    if confirm not in ("y", "yes", "д", "да"):
        print("❌ Восстановление отменено")
        if os.path.exists(temp_yaml):
            os.remove(temp_yaml)
        return
    
    client, _ = _ask_port_and_connect(config, device)
    if client is None:
        if os.path.exists(temp_yaml):
            os.remove(temp_yaml)
        return
    
    try:
        ok = write_tags(client, PLC_DATA_DIR, os.path.basename(temp_yaml))
        if ok:
            print("\n✅ Восстановление завершено успешно!")
        else:
            print("\n❌ Восстановление завершилось с ошибками.")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        if os.path.exists(temp_yaml):
            os.remove(temp_yaml)
        print("🔌 Готово!")


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