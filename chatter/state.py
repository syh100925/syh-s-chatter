"""模块级共享状态（在 create_app/register_into 时初始化）。"""
import logging
import os

# 包所在的项目根目录（chatter/ 的上一级）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 数据目录：默认项目根目录（config.json、*.list、log.txt 所在处）
# 嵌入宿主应用时可通过 create_app(data_dir=...) / register_into(data_dir=...) 更改
DATA_DIR = PROJECT_ROOT

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
STATIC_DIR = os.path.join(PROJECT_ROOT, 'static')

logger = logging.getLogger('syh-chatter')

# ---- 用户数据（从 *.list 文件加载）----
usernames = []
passwords = []
user_colors = []
admins = []

# ---- 配置 ----
settings = {}
server_ip = ''
base_path = ''

# ---- 在线状态 ----
loginings = []

# ---- 数据库 ----
client = None
db = None
database = None
mutes = None
traffic = None

# ---- 当前 Flask 应用 ----
app = None


def read_lines(filename):
    try:
        with open(os.path.join(DATA_DIR, filename), 'r', encoding='utf-8') as stream:
            return [line.strip() for line in stream.read().splitlines()]
    except FileNotFoundError:
        return []


def setup_logger():
    if not logger.handlers:
        file_handler = logging.FileHandler(os.path.join(DATA_DIR, 'log.txt'), encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
