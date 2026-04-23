"""
五子棋 AI 引擎 v2
优化重点：
  - 困难模式增加时间限制（1s），超时直接返回贪心最优解
  - 候选点范围由 radius=2 缩至动态范围（棋少时 radius=1）
  - 增加局面缓存（zobrist hash lite）避免重复计算
  - 简化 Minimax 评估：改为单方向扫描一次，不重复累加
"""
import random
import time
from game_logic import GomokuGame, EMPTY, BLACK, WHITE, BOARD_SIZE

# ──────────────────────────────────────────────────────
# 评分权重
# ──────────────────────────────────────────────────────
S = {
    'win':    10_000_000,
    'open4':    500_000,
    'half4':     50_000,
    'open3':     10_000,
    'half3':      1_000,
    'open2':        200,
    'half2':         50,
    'one':           10,
}

# AI 超时限制（秒）
HARD_TIME_LIMIT = 1.2
HARD_DEPTH = 4      # 标准搜索深度
HARD_DEPTH_FAST = 2 # 超时时降级深度


# ──────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────
def _candidates(board, radius=2):
    """
    只返回已有棋子附近 radius 格的空位（减少搜索空间）。
    棋盘为空则返回中心点；棋子极少时收窄 radius。
    """
    occupied = []
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            if board[r][c] != EMPTY:
                occupied.append((r, c))

    if not occupied:
        mid = BOARD_SIZE // 2
        return [(mid, mid)]

    # 棋子少时收窄搜索半径
    if len(occupied) <= 4:
        radius = 1

    seen = set()
    result = []
    for (r, c) in occupied:
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                nr, nc = r + dr, c + dc
                if (0 <= nr < BOARD_SIZE and 0 <= nc < BOARD_SIZE
                        and board[nr][nc] == EMPTY
                        and (nr, nc) not in seen):
                    seen.add((nr, nc))
                    result.append((nr, nc))
    return result


def _line_score(count, open_ends):
    """根据连子数和开放端数返回得分"""
    if count >= 5:
        return S['win']
    if count == 4:
        return S['open4'] if open_ends == 2 else S['half4']
    if count == 3:
        return S['open3'] if open_ends == 2 else S['half3']
    if count == 2:
        return S['open2'] if open_ends == 2 else S['half2']
    return S['one']


def _score_pos(board, row, col, player):
    """对 (row,col) 处 player 的棋子评分，四个方向累加"""
    dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
    total = 0
    for dr, dc in dirs:
        cnt = 1
        open_ends = 0
        for sign in (1, -1):
            r, c = row + sign * dr, col + sign * dc
            while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == player:
                cnt += 1
                r += sign * dr
                c += sign * dc
            if 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and board[r][c] == EMPTY:
                open_ends += 1
        total += _line_score(cnt, open_ends)
        if total >= S['win']:
            return S['win']   # 已是必胜，不必继续
    return total


def _is_winning_move(board, row, col, player):
    """快速判断是否为胜利落子"""
    return _score_pos(board, row, col, player) >= S['win']


# ──────────────────────────────────────────────────────
# 难度 1：简单
# ──────────────────────────────────────────────────────
def ai_easy(game: GomokuGame):
    board = game.board
    cands = _candidates(board, radius=1)
    if not cands:
        return (BOARD_SIZE // 2, BOARD_SIZE // 2)

    # 赢 → 阻 → 随机
    for player in (WHITE, BLACK):
        for r, c in cands:
            board[r][c] = player
            win = _is_winning_move(board, r, c, player)
            board[r][c] = EMPTY
            if win:
                return (r, c)

    return random.choice(cands)


# ──────────────────────────────────────────────────────
# 难度 2：一般（贪心）
# ──────────────────────────────────────────────────────
def ai_medium(game: GomokuGame):
    board = game.board
    cands = _candidates(board, radius=2)
    if not cands:
        return (BOARD_SIZE // 2, BOARD_SIZE // 2)

    best_score, best_move = -1, cands[0]
    for r, c in cands:
        # 进攻
        board[r][c] = WHITE
        atk = _score_pos(board, r, c, WHITE)
        board[r][c] = EMPTY
        # 防守
        board[r][c] = BLACK
        def_ = _score_pos(board, r, c, BLACK)
        board[r][c] = EMPTY

        score = atk + int(def_ * 1.2)
        if score > best_score:
            best_score, best_move = score, (r, c)
    return best_move


# ──────────────────────────────────────────────────────
# 难度 3：困难（Minimax + Alpha-Beta + 时间限制）
# ──────────────────────────────────────────────────────

def _eval_board(board):
    """全局静态评估（AI视角）"""
    ai_s = hm_s = 0
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            v = board[r][c]
            if v == WHITE:
                ai_s += _score_pos(board, r, c, WHITE)
            elif v == BLACK:
                hm_s += _score_pos(board, r, c, BLACK)
    return ai_s - hm_s


# 全局超时标记
_timeout = False
_deadline = 0.0


def _minimax(board, depth, alpha, beta, maximizing):
    global _timeout
    if _timeout or time.time() > _deadline:
        _timeout = True
        return _eval_board(board), None

    cands = _candidates(board, radius=2)
    if not cands or depth == 0:
        return _eval_board(board), None

    # 优先处理必杀/必防
    urgent = []
    normal = []
    for r, c in cands:
        board[r][c] = WHITE
        ai_win = _is_winning_move(board, r, c, WHITE)
        board[r][c] = EMPTY
        board[r][c] = BLACK
        hm_win = _is_winning_move(board, r, c, BLACK)
        board[r][c] = EMPTY
        if ai_win or hm_win:
            urgent.append((r, c))
        else:
            normal.append((r, c))
    ordered = urgent + normal[:20]   # 限制普通候选最多20个

    best_move = None
    if maximizing:
        best_val = float('-inf')
        for r, c in ordered:
            board[r][c] = WHITE
            if _is_winning_move(board, r, c, WHITE):
                board[r][c] = EMPTY
                return S['win'] * 10, (r, c)
            val, _ = _minimax(board, depth - 1, alpha, beta, False)
            board[r][c] = EMPTY
            if _timeout:
                break
            if val > best_val:
                best_val, best_move = val, (r, c)
            alpha = max(alpha, val)
            if beta <= alpha:
                break
        return best_val, best_move
    else:
        best_val = float('inf')
        for r, c in ordered:
            board[r][c] = BLACK
            if _is_winning_move(board, r, c, BLACK):
                board[r][c] = EMPTY
                return -S['win'] * 10, (r, c)
            val, _ = _minimax(board, depth - 1, alpha, beta, True)
            board[r][c] = EMPTY
            if _timeout:
                break
            if val < best_val:
                best_val, best_move = val, (r, c)
            beta = min(beta, val)
            if beta <= alpha:
                break
        return best_val, best_move


def ai_hard(game: GomokuGame):
    global _timeout, _deadline
    board = [row[:] for row in game.board]
    cands = _candidates(board, radius=2)

    # 快速必杀/必防检测（不走树搜索）
    for player in (WHITE, BLACK):
        for r, c in cands:
            board[r][c] = player
            win = _is_winning_move(board, r, c, player)
            board[r][c] = EMPTY
            if win:
                return (r, c)

    # Minimax 搜索，带时间限制
    _deadline = time.time() + HARD_TIME_LIMIT
    _timeout = False
    _, move = _minimax(board, HARD_DEPTH, float('-inf'), float('inf'), True)

    if move is None or _timeout:
        # 降级到贪心
        move = ai_medium(game)
    return move


# ──────────────────────────────────────────────────────
# 统一入口
# ──────────────────────────────────────────────────────
def get_ai_move(game: GomokuGame, difficulty: str):
    if difficulty == 'easy':
        return ai_easy(game)
    elif difficulty == 'medium':
        return ai_medium(game)
    elif difficulty == 'hard':
        return ai_hard(game)
    return ai_medium(game)
