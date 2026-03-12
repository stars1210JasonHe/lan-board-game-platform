# AI 棋力提升计划

## Phase 1 — 信息增强（今天）

### 1.1 被攻击棋子信息
- **文件**: `ask_move.py` → `build_user_prompt()`
- **内容**: 用 python-chess 计算当前被攻击的己方棋子，加入 prompt
- **格式**: `Your pieces under attack: Nd4 (attacked by pawn), Rf1 (attacked by bishop)`
- **预期效果**: 大幅减少无意识丢子
- **适用**: chess（python-chess）、xiangqi（手动计算）

### 1.2 最近走棋历史
- **文件**: `euler_play.py` → `_llm_move()` + `ask_move.py`
- **内容**: 传最近 5-10 步走棋历史给 LLM
- **格式**: `Recent moves: 1. e4 e5 2. Nf3 Nc6 3. Bb5`
- **预期效果**: LLM 更好理解局势发展，不重复走棋
- **适用**: chess（SAN）、xiangqi（坐标）

---

## Phase 2 — 推理增强（明天）

### 2.1 启用 thinking/reasoning
- **文件**: `ask_move.py` → `call_openclaw()` 或 `call_anthropic()`
- **内容**: 让 LLM 先输出分析再给走法（chain-of-thought）
- **方法**: prompt 加 "First briefly analyze the position (2-3 sentences), then give your move."
- **解析**: 提取最后一行作为走法
- **预期效果**: 棋力明显提升，但增加 token 消耗和延迟
- **权衡**: token 成本 ↑，延迟 ↑，棋力 ↑↑

### 2.2 走棋后验证（anti-blunder）
- **文件**: `ask_move.py` 或 `euler_play.py`
- **内容**: LLM 返回走法后，用 python-chess 模拟：走完后对手能不能白吃我的子？
- **如果送子**: 重新请求 LLM（最多 2 次重试），提示 "Your move X hangs a piece, pick another"
- **预期效果**: 消除低级丢子错误
- **适用**: chess（python-chess 模拟简单）、xiangqi（需自己写模拟）

---

## Phase 3 — 格式优化（后天）

### 3.1 PGN 格式（chess）
- **内容**: 把完整棋谱（PGN）而不是 FEN/ASCII 发给 LLM
- **研究依据**: LLM 训练数据中大量 PGN，用 PGN 能激活"棋手模式"
- **权衡**: token 消耗随对局增长，中后期可能很长
- **方案**: 发最近 20 步 PGN + 当前 FEN

### 3.2 Few-shot 示例
- **内容**: 在 SKILL.md 加 2-3 个优质走法示例
- **示例**: "Position: ... → Best move: Nf3 (develops knight, controls center, prepares castle)"
- **预期效果**: 轻微改善，增加约 200 token

---

## 优先级总结

| 阶段 | 改动 | 效果 | 成本 | 建议时间 |
|------|------|------|------|----------|
| P1 | 被攻击信息 | ⭐⭐⭐ | 低 | 今天 |
| P1 | 走棋历史 | ⭐⭐ | 低 | 今天 |
| P2 | thinking/reasoning | ⭐⭐⭐ | 中（token↑） | 明天 |
| P2 | anti-blunder 验证 | ⭐⭐⭐ | 中 | 明天 |
| P3 | PGN 格式 | ⭐⭐ | 低 | 后天 |
| P3 | Few-shot | ⭐ | 低 | 后天 |

---

## 不做的

| 改动 | 原因 |
|------|------|
| 换 Opus 模型 | 太贵太慢，不值得 |
| 限制合法走法列表 | 风险高，可能砍掉最佳走法 |
| 降低聊天频率 | 用户说不需要 |
