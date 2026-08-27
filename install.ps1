# 一键安装 personal-assistant skill（Windows 用本脚本; Linux/macOS 用 install.sh）
# 兼容工具: TRAE(.trae\skills), Claude Code(.claude\skills), OpenCode(.opencode\skill), Codex 等 AGENTS.md 类工具
# 用法: .\install.ps1 -Target "<项目根>" [-Tools trae,claude,opencode,agents] [-Force] [-Global claude|opencode]
param(
    [string]$Target = ".",
    [string[]]$Tools = @(),        # 留空 = 全部: trae, claude, opencode, agents
    [string]$Global = "",          # claude / opencode: 安装到用户级全局目录(忽略 -Target)
    [switch]$Force                 # 目标已存在时静默覆盖
)

$ErrorActionPreference = "Stop"
$skillName = "personal-assistant"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $src "SKILL.md"))) {
    Write-Host "错误: $src 下未找到 SKILL.md, 请在 skill 目录内运行本脚本" -ForegroundColor Red
    exit 1
}
if ($Tools.Count -eq 0) { $Tools = @("trae", "claude", "opencode", "agents") }

function Copy-Skill([string]$dest) {
    New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
    if (Test-Path $dest) {
        if ((Resolve-Path $src).Path -eq (Resolve-Path $dest).Path) {
            Write-Host "跳过(源即目标): $dest"
            return
        }
        if (-not $Force) {
            $answer = Read-Host "目标已存在: $dest , 覆盖? (y/N)"
            if ($answer -notin @("y", "Y")) { Write-Host "已跳过: $dest" -ForegroundColor Yellow; return }
        }
        Remove-Item $dest -Recurse -Force
    }
    Copy-Item -Path $src -Destination $dest -Recurse
    Write-Host "安装完成: $dest" -ForegroundColor Green
}

if ($Global) {
    switch ($Global) {
        "claude"   { Copy-Skill (Join-Path $HOME ".claude\skills\$skillName") }
        "opencode" { Copy-Skill (Join-Path $HOME ".config\opencode\skill\$skillName") }
        default    { Write-Host "不支持的全局目标: $Global (可选: claude, opencode)" -ForegroundColor Red; exit 1 }
    }
    Write-Host ""
    Write-Host "说明: 数据目录在 ~/assistant, 迁移电脑时整体拷贝即可。"
    exit 0
}

$targetRoot = (Resolve-Path $Target).Path
foreach ($t in $Tools) {
    switch ($t.Trim()) {
        "trae"     { Copy-Skill (Join-Path $targetRoot ".trae\skills\$skillName") }
        "claude"   { Copy-Skill (Join-Path $targetRoot ".claude\skills\$skillName") }
        "opencode" { Copy-Skill (Join-Path $targetRoot ".opencode\skill\$skillName") }
        "agents" {
            Copy-Skill (Join-Path $targetRoot "skills\$skillName")
            $agentsFile = Join-Path $targetRoot "AGENTS.md"
            $needAppend = $true
            if (Test-Path $agentsFile) {
                if (Select-String -Path $agentsFile -Pattern "personal-assistant:start" -Quiet) { $needAppend = $false }
            }
            if ($needAppend) {
                Add-Content -Path $agentsFile -Encoding UTF8 -Value @"

<!-- personal-assistant:start -->
## 个人助手（Personal Assistant）

本项目包含一个跨工具的个人助手技能, 记忆数据持久化在 `~/assistant`（markdown 文件）。

当用户要求 **记录/记住内容**、**管理任务**（待办、完成、"今天还有什么任务"）、**提供文件路径要求总结**、或 **询问个人记忆/历史/偏好** 时：先完整阅读 `skills/personal-assistant/SKILL.md` 并遵循其指令执行。脚本位于 `skills/personal-assistant/scripts/`（Windows 用 `python`, Linux/macOS 用 `python3`）。
<!-- personal-assistant:end -->
"@
                Write-Host "已追加 AGENTS.md 指针: $agentsFile" -ForegroundColor Green
            } else {
                Write-Host "AGENTS.md 已包含指针, 跳过"
            }
        }
        default { Write-Host "未知工具: $t (可选: trae, claude, opencode, agents)" -ForegroundColor Yellow }
    }
}

Write-Host ""
Write-Host "说明: 助手数据目录位于本机用户主目录: ~/assistant"
Write-Host "      迁移到其他电脑时, 把整个 assistant 文件夹拷贝到对方用户主目录即可。"
