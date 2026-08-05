"""MongoDB 客户端（含 mongomock 回退）。"""
from . import state


def make_uri(settings=None):
    settings = settings or state.settings
    db_user = settings.get('db_user', '')
    db_pass = settings.get('db_pass', '')
    if db_user or db_pass:
        return 'mongodb://%s:%s@%s:%s' % (
            db_user, db_pass,
            settings.get('db_ip', '127.0.0.1'),
            settings.get('db_port', '27017'))
    return 'mongodb://%s:%s' % (
        settings.get('db_ip', '127.0.0.1'),
        settings.get('db_port', '27017'))


def create_database_client(settings=None):
    from pymongo import MongoClient
    uri = make_uri(settings)
    mongo_client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    try:
        mongo_client.admin.command('ping')
        return mongo_client
    except Exception as exc:
        state.logger.warning('MongoDB unavailable at %s: %s', uri, exc)
        try:
            import mongomock
        except ImportError:
            state.logger.error(
                'mongomock is not installed; database requests will fail until MongoDB starts')
            return mongo_client
        state.logger.warning(
            'Using in-memory mongomock fallback; messages will not persist across restarts')
        return mongomock.MongoClient()


def init_database(settings=None):
    settings = settings or state.settings
    state.client = create_database_client(settings)
    state.db = state.client['chats']
    state.database = state.db['values']
    state.mutes = state.db['mutes']
    state.traffic = state.db['traffic']
