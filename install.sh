#!/usr/bin/env bash
# 一键安装 personal-assistant skill（Linux/macOS 用本脚本; Windows 用 install.ps1）
# 兼容工具: TRAE(.trae/skills), Claude Code(.claude/skills), OpenCode(.opencode/skill), Codex 等 AGENTS.md 类工具
# 用法: ./install.sh [--target <项目根>] [--tools trae,claude,opencode,agents] [--global claude|opencode] [--force]
set -euo pipefail

SKILL_NAME="personal-assistant"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="."
TOOLS="trae,claude,opencode,agents"
GLOBAL=""
FORCE=0

usage() {
  cat <<'EOF'
用法: ./install.sh [--target <项目根>] [--tools trae,claude,opencode,agents] [--global claude|opencode] [--force]
  --target  目标项目根目录(默认当前目录)
  --tools   要安装的工具, 逗号分隔; 缺省 = 全部; agents = 生成 skills/ 中性副本 + AGENTS.md 指针(Codex 等用)
  --global  安装到用户级全局目录: claude -> ~/.claude/skills; opencode -> ~/.config/opencode/skill
  --force   目标已存在时静默覆盖
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) TARGET="${2:?缺少参数值}"; shift 2 ;;
    --tools)  TOOLS="${2:?缺少参数值}"; shift 2 ;;
    --global) GLOBAL="${2:?缺少参数值}"; shift 2 ;;
    --force)  FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数: $1"; usage; exit 1 ;;
  esac
done

[[ -f "$SRC/SKILL.md" ]] || { echo "错误: $SRC 下未找到 SKILL.md, 请在 skill 目录内运行本脚本"; exit 1; }
TARGET="$(cd "$TARGET" && pwd)"

copy_skill() {
  local dest="$1"
  if [[ -d "$dest" ]] && [[ "$(cd "$SRC" && pwd -P)" == "$(cd "$dest" && pwd -P)" ]]; then
    echo "跳过(源即目标): $dest"
    return 0
  fi
  if [[ -d "$dest" ]]; then
    if [[ $FORCE -eq 0 ]]; then
      local ans=""
      read -p "目标已存在: $dest , 覆盖? (y/N) " ans || ans=""
      [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "已跳过: $dest"; return 0; }
    fi
    rm -rf "$dest"
  fi
  mkdir -p "$(dirname "$dest")"
  cp -r "$SRC" "$dest"
  echo "安装完成: $dest"
}

append_agents() {
  local f="$TARGET/AGENTS.md"
  if [[ -f "$f" ]] && grep -q "personal-assistant:start" "$f"; then
    echo "AGENTS.md 已包含指针, 跳过"
    return 0
  fi
  cat >> "$f" <<'EOF'

<!-- personal-assistant:start -->
## 个人助手（Personal Assistant）

本项目包含一个跨工具的个人助手技能, 记忆数据持久化在 `~/assistant`（markdown 文件）。

当用户要求 **记录/记住内容**、**管理任务**（待办、完成、"今天还有什么任务"）、**提供文件路径要求总结**、或 **询问个人记忆/历史/偏好** 时：先完整阅读 `skills/personal-assistant/SKILL.md` 并遵循其指令执行。脚本位于 `skills/personal-assistant/scripts/`（Windows 用 `python`, Linux/macOS 用 `python3`）。
<!-- personal-assistant:end -->
EOF
  echo "已追加 AGENTS.md 指针: $f"
}

if [[ -n "$GLOBAL" ]]; then
  case "$GLOBAL" in
    claude)   copy_skill "$HOME/.claude/skills/$SKILL_NAME" ;;
    opencode) copy_skill "${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skill/$SKILL_NAME" ;;
    *) echo "不支持的全局目标: $GLOBAL (可选: claude, opencode)"; exit 1 ;;
  esac
  echo ""
  echo "说明: 数据目录在 ~/assistant, 迁移电脑时整体拷贝即可。"
  exit 0
fi

IFS=',' read -ra TOOL_LIST <<< "$TOOLS"
for t in "${TOOL_LIST[@]}"; do
  t="${t// /}"
  case "$t" in
    trae)     copy_skill "$TARGET/.trae/skills/$SKILL_NAME" ;;
    claude)   copy_skill "$TARGET/.claude/skills/$SKILL_NAME" ;;
    opencode) copy_skill "$TARGET/.opencode/skill/$SKILL_NAME" ;;
    agents)   copy_skill "$TARGET/skills/$SKILL_NAME"; append_agents ;;
    *)        echo "未知工具: $t (可选: trae, claude, opencode, agents)" ;;
  esac
done

echo ""
echo "说明: 助手数据目录位于用户主目录 ~/assistant, 迁移电脑时整体拷贝即可。"
