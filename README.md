# reasoning-with-chinese-history

通过《史记》《资治通鉴》的可核验案例，辅助分析现实抉择。技能说明位于 [SKILL.md](reasoning-with-chinese-history/SKILL.md)。

仓库包含简体转写语料、来源清单、脚本和参考文档。SQLite 检索索引与 JSONL 段落文件是生成物，不纳入 Git：SQLite 单文件超过 GitHub 的 100 MB 限制。

## 安装与构建

把 `reasoning-with-chinese-history` 目录复制到 Codex 或 Claude 的 skills 目录，或将两个 skills 目录分别链接到该目录。在技能根目录运行：

```bash
python3 scripts/build_index.py --text-root corpus/text --output-dir corpus/index
python3 scripts/search_corpus.py '韩信' --limit 1 --context 0 --json
```

脚本使用 Python 标准库，索引构建依赖 Python 所附 SQLite 的 FTS5。首次使用前须生成 `corpus/index/search.sqlite3`；目录必须可写，构建时需要足够的临时磁盘空间。

语料固定来源、转换与许可限定见 [来源政策](reasoning-with-chinese-history/references/source-policy.md)及 [manifest.json](reasoning-with-chinese-history/corpus/manifest.json)。
