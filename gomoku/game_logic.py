"""
五子棋核心游戏逻辑
包含：棋盘管理、落子验证、胜负判断
"""

BOARD_SIZE = 15  # 15x15 标准棋盘
EMPTY = 0
BLACK = 1  # 黑棋（先手）
WHITE = 2  # 白棋（后手/AI）

WIN_COUNT = 5  # 五子连珠获胜


class GomokuGame:
    def __init__(self):
        self.board = [[EMPTY] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        self.current_player = BLACK
        self.game_over = False
        self.winner = None
        self.move_history = []

    def reset(self):
        """重置游戏"""
        self.board = [[EMPTY] * BOARD_SIZE for _ in range(BOARD_SIZE)]
        self.current_player = BLACK
        self.game_over = False
        self.winner = None
        self.move_history = []

    def is_valid_move(self, row, col):
        """验证落子合法性"""
        if self.game_over:
            return False
        if not (0 <= row < BOARD_SIZE and 0 <= col < BOARD_SIZE):
            return False
        return self.board[row][col] == EMPTY

    def place_stone(self, row, col, player=None):
        """
        落子
        :param row: 行
        :param col: 列
        :param player: 指定玩家（默认使用当前玩家）
        :return: (success, winner)
        """
        if player is None:
            player = self.current_player

        if not self.is_valid_move(row, col):
            return False, None

        self.board[row][col] = player
        self.move_history.append((row, col, player))

        # 判断胜负
        if self._check_win(row, col, player):
            self.game_over = True
            self.winner = player
            return True, player

        # 判断平局
        if self._check_draw():
            self.game_over = True
            self.winner = 0  # 平局
            return True, 0

        # 切换玩家
        self.current_player = WHITE if player == BLACK else BLACK
        return True, None

    def _check_win(self, row, col, player):
        """检查落子后是否获胜（四个方向）"""
        directions = [
            (0, 1),   # 横向
            (1, 0),   # 纵向
            (1, 1),   # 右斜
            (1, -1),  # 左斜
        ]
        for dr, dc in directions:
            count = 1  # 包含当前落子
            # 正方向延伸
            count += self._count_consecutive(row, col, dr, dc, player)
            # 反方向延伸
            count += self._count_consecutive(row, col, -dr, -dc, player)
            if count >= WIN_COUNT:
                return True
        return False

    def _count_consecutive(self, row, col, dr, dc, player):
        """沿某方向统计连续同色棋子数"""
        count = 0
        r, c = row + dr, col + dc
        while 0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE and self.board[r][c] == player:
            count += 1
            r += dr
            c += dc
        return count

    def _check_draw(self):
        """检查平局（棋盘全满）"""
        for row in self.board:
            if EMPTY in row:
                return False
        return True

    def get_board_state(self):
        """返回棋盘状态字典"""
        return {
            'board': self.board,
            'current_player': self.current_player,
            'game_over': self.game_over,
            'winner': self.winner,
            'move_count': len(self.move_history),
        }

    def undo_move(self):
        """悔棋（撤销最近一步）"""
        if not self.move_history:
            return False
        row, col, player = self.move_history.pop()
        self.board[row][col] = EMPTY
        self.current_player = player
        self.game_over = False
        self.winner = None
        return True

    def get_all_empty_cells(self):
        """获取所有空格坐标"""
        return [
            (r, c)
            for r in range(BOARD_SIZE)
            for c in range(BOARD_SIZE)
            if self.board[r][c] == EMPTY
        ]

    def clone_board(self):
        """克隆当前棋盘（用于AI搜索）"""
        return [row[:] for row in self.board]
