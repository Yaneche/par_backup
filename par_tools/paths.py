# par_tools/paths.py
import os
import sys

def get_base_dir():
    if getattr(sys, "frozen", False):
        # запущено из собранного EXE
        return os.path.dirname(sys.executable)
    # запущено как обычный скрипт
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # ↑ здесь предполагаем, что par_tools лежит в корне проекта

BASE_DIR = get_base_dir()              # папка рядом с EXE (или корень проекта при запуске из .py)

DATA_ROOT = os.path.join(BASE_DIR, "data")

CONFIG_FILE  = os.path.join(DATA_ROOT, "plc_config.json")
PLC_DATA_DIR = os.path.join(DATA_ROOT, "plc_data")
TAGS_FILE    = os.path.join(DATA_ROOT, "Par_Db_tags.json")
XML_LOG_DIR  = os.path.join(DATA_ROOT, "xml_logs")
