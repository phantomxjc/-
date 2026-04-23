"""
Flask 五子棋服务 v2
新增功能：
  - 双页面：/ 模式选择  /game 游戏页
  - PvP 房间系统：创建/加入房间（6位房间码）
  - 前后端分离 API，使用 Server-Sent Events 推送 PvP 落子
"""
import uuid
import random
import string
import time
from flask import (Flask, request, jsonify, render_template,
                   session, Response)

from game_logic import GomokuGame, BLACK, WHITE
from ai_engine import get_ai_move

app = Flask(__name__)
app.secret_key = 'gomoku_v2_secret_2026'

# ──────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────
# PvC 游戏：{ session_id -> {game, difficulty} }
_pvc_games: dict = {}

# PvP 房间：{ room_code -> Room }
_pvp_rooms: dict = {}


class PvPRoom:
    """真人对战房间"""
    def __init__(self, code: str, host_sid: str):
        self.code = code
        self.game = GomokuGame()
        self.players = {BLACK: host_sid}   # 1=黑(创建者), 2=白(加入者)
        self.created_at = time.time()
        self.last_active = time.time()
        self._last_move = None             # (row, col, player) 用于 SSE 推送
        self._version = 0                  # 每次落子版本号递增

    def join(self, guest_sid: str) -> bool:
        if WHITE in self.players:
            return False   # 已满
        self.players[WHITE] = guest_sid
        return True

    def get_player_color(self, sid: str):
        for color, s in self.players.items():
            if s == sid:
                return color
        return None

    def is_full(self):
        return len(self.players) == 2

    def to_dict(self, sid: str = None):
        color = self.get_player_color(sid) if sid else None
        winner_map = {0: 'draw', 1: 'black', 2: 'white', None: None}
        state = self.game.get_board_state()
        return {
            'code': self.code,
            'board': state['board'],
            'current_player': 'black' if state['current_player'] == BLACK else 'white',
            'game_over': state['game_over'],
            'winner': winner_map.get(state['winner']),
            'move_count': state['move_count'],
            'my_color': 'black' if color == BLACK else ('white' if color == WHITE else None),
            'is_full': self.is_full(),
            'version': self._version,
        }


def _gen_room_code():
    """生成6位大写字母+数字房间码"""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=6))
        if code not in _pvp_rooms:
            return code


def _cleanup_rooms():
    """清理超过2小时无活动的房间"""
    now = time.time()
    dead = [k for k, r in _pvp_rooms.items() if now - r.last_active > 7200]
    for k in dead:
        del _pvp_rooms[k]


# ──────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────
def _sid():
    s = session.get('sid')
    if not s:
        s = str(uuid.uuid4())
        session['sid'] = s
    return s


def _pvc_state(game: GomokuGame, message='', difficulty='medium'):
    state = game.get_board_state()
    winner_map = {0: 'draw', 1: 'black', 2: 'white', None: None}
    return {
        'board': state['board'],
        'current_player': 'black' if state['current_player'] == BLACK else 'white',
        'game_over': state['game_over'],
        'winner': winner_map.get(state['winner']),
        'move_count': state['move_count'],
        'difficulty': difficulty,
        'message': message,
    }


# ──────────────────────────────────────────────────────
# 页面路由
# ──────────────────────────────────────────────────────
@app.route('/')
def index():
    """模式选择页"""
    _sid()
    return render_template('index.html')


@app.route('/game')
def game_page():
    """游戏页面"""
    _sid()
    mode = request.args.get('mode', 'pvc')
    difficulty = request.args.get('difficulty', 'medium')
    room_code = request.args.get('room', '')
    return render_template('game.html',
                           mode=mode,
                           difficulty=difficulty,
                           room_code=room_code)


# ──────────────────────────────────────────────────────
# PvC API
# ──────────────────────────────────────────────────────
@app.route('/api/pvc/new', methods=['POST'])
def pvc_new():
    sid = _sid()
    data = request.get_json(silent=True) or {}
    difficulty = data.get('difficulty', 'medium')
    if difficulty not in ('easy', 'medium', 'hard'):
        difficulty = 'medium'

    game = GomokuGame()
    game.reset()
    _pvc_games[sid] = {'game': game, 'difficulty': difficulty}
    return jsonify(_pvc_state(game, '游戏开始！黑棋先行。', difficulty))


@app.route('/api/pvc/move', methods=['POST'])
def pvc_move():
    sid = _sid()
    if sid not in _pvc_games:
        return jsonify({'error': '请先开始游戏'}), 400

    data = request.get_json(silent=True) or {}
    try:
        row, col = int(data['row']), int(data['col'])
    except (KeyError, ValueError, TypeError):
        return jsonify({'error': '坐标无效'}), 400

    room = _pvc_games[sid]
    game: GomokuGame = room['game']
    difficulty = room['difficulty']

    if game.game_over:
        return jsonify(_pvc_state(game, '游戏已结束', difficulty))

    ok, winner = game.place_stone(row, col)
    if not ok:
        return jsonify({'error': '该位置不可落子'}), 400

    if game.game_over:
        msg = '平局！' if winner == 0 else '你赢了！🎉' if winner == BLACK else 'AI获胜！再战一局？'
        return jsonify(_pvc_state(game, msg, difficulty))

    # AI 落子
    ai_pos = get_ai_move(game, difficulty)
    if ai_pos:
        game.place_stone(ai_pos[0], ai_pos[1], WHITE)
    if game.game_over:
        state = game.get_board_state()
        msg = '平局！' if state['winner'] == 0 else 'AI获胜！再战一局？'
        return jsonify(_pvc_state(game, msg, difficulty))

    return jsonify(_pvc_state(game, '', difficulty))


@app.route('/api/pvc/undo', methods=['POST'])
def pvc_undo():
    sid = _sid()
    if sid not in _pvc_games:
        return jsonify({'error': '请先开始游戏'}), 400

    room = _pvc_games[sid]
    game: GomokuGame = room['game']
    # 撤销两步（AI + 玩家）
    undone = 0
    for _ in range(2):
        if game.undo_move():
            undone += 1
        else:
            break
    msg = '已悔棋' if undone > 0 else '没有可撤销的步骤'
    return jsonify(_pvc_state(game, msg, room['difficulty']))


@app.route('/api/pvc/state', methods=['GET'])
def pvc_state():
    sid = _sid()
    if sid not in _pvc_games:
        return jsonify({'error': '未初始化'}), 400
    room = _pvc_games[sid]
    return jsonify(_pvc_state(room['game'], '', room['difficulty']))


# ──────────────────────────────────────────────────────
# PvP 房间 API
# ──────────────────────────────────────────────────────
@app.route('/api/pvp/create', methods=['POST'])
def pvp_create():
    """创建房间，返回房间码"""
    sid = _sid()
    _cleanup_rooms()
    code = _gen_room_code()
    room = PvPRoom(code, sid)
    _pvp_rooms[code] = room
    return jsonify({'code': code, **room.to_dict(sid)})


@app.route('/api/pvp/join', methods=['POST'])
def pvp_join():
    """加入房间"""
    sid = _sid()
    data = request.get_json(silent=True) or {}
    code = str(data.get('code', '')).upper().strip()

    if code not in _pvp_rooms:
        return jsonify({'error': '房间不存在，请检查房间码'}), 404

    room = _pvp_rooms[code]
    if room.is_full():
        # 允许已在房间里的人重连
        if room.get_player_color(sid) is not None:
            return jsonify({'reconnect': True, **room.to_dict(sid)})
        return jsonify({'error': '房间已满'}), 400

    room.join(sid)
    room.last_active = time.time()
    return jsonify({'joined': True, **room.to_dict(sid)})


@app.route('/api/pvp/move', methods=['POST'])
def pvp_move():
    """PvP 落子"""
    sid = _sid()
    data = request.get_json(silent=True) or {}
    code = str(data.get('code', '')).upper().strip()

    if code not in _pvp_rooms:
        return jsonify({'error': '房间不存在'}), 404

    room = _pvp_rooms[code]
    color = room.get_player_color(sid)
    if color is None:
        return jsonify({'error': '你不在此房间'}), 403

    game = room.game
    if game.game_over:
        return jsonify(room.to_dict(sid))

    if game.current_player != color:
        return jsonify({'error': '还没轮到你'}), 400

    try:
        row, col = int(data['row']), int(data['col'])
    except (KeyError, ValueError, TypeError):
        return jsonify({'error': '坐标无效'}), 400

    ok, winner = game.place_stone(row, col)
    if not ok:
        return jsonify({'error': '该位置不可落子'}), 400

    room._last_move = (row, col, color)
    room._version += 1
    room.last_active = time.time()
    return jsonify(room.to_dict(sid))


@app.route('/api/pvp/state', methods=['GET'])
def pvp_state():
    """获取房间状态（轮询用）"""
    sid = _sid()
    code = request.args.get('code', '').upper().strip()
    version = int(request.args.get('version', 0))

    if code not in _pvp_rooms:
        return jsonify({'error': '房间不存在'}), 404

    room = _pvp_rooms[code]
    # 没有新数据返回 304-like（version相同）
    d = room.to_dict(sid)
    d['has_update'] = room._version > version
    return jsonify(d)


@app.route('/api/pvp/undo', methods=['POST'])
def pvp_undo():
    """PvP 悔棋（撤销最近一步，任意玩家可请求）"""
    sid = _sid()
    data = request.get_json(silent=True) or {}
    code = str(data.get('code', '')).upper().strip()
    if code not in _pvp_rooms:
        return jsonify({'error': '房间不存在'}), 404

    room = _pvp_rooms[code]
    if room.get_player_color(sid) is None:
        return jsonify({'error': '你不在此房间'}), 403

    room.game.undo_move()
    room._version += 1
    return jsonify(room.to_dict(sid))


# ──────────────────────────────────────────────────────
# 启动
# ──────────────────────────────────────────────────────
if __name__ == '__main__':
    print('五子棋 v2 启动中... 访问 http://127.0.0.1:5000')
    app.run(host='0.0.0.0', port=5000, debug=False)
